#!/usr/bin/env python3
"""
Einen G-Code durchrechnen, ohne dass sich etwas bewegt.

  python3 trockenlauf.py datei.nc
  python3 trockenlauf.py datei.nc --bild vorschau.png
  python3 trockenlauf.py datei.nc --bei 1864777

Liest die Datei und deutet sie wie GRBL 1.1 im Lasermodus: modaler Zustand,
G90/G91, G20/G21, M3 gegen M4, S und F durchgeschleppt. Daraus kommt, wohin
der Kopf faehrt, wo der Strahl brennt, wie lange es dauert - und was dabei
schiefgehen wuerde.

Es oeffnet keinen seriellen Port und schickt nichts an die Maschine. Ein
Trockenlauf kostet eine Minute, ein halb gravierter Abend zwoelf Stunden.
"""
import argparse
import math
import os
import re
import sys

import lw_presets as P
import lw_text
from lw_job import ACCEL, estimate
from lw_text import T

lw_text.setze(P.load_config().get("sprache", "de"))

# GRBL 1.1 kennt genau diese Befehle. Alles andere quittiert es mit
# "error:20 Unsupported command" und ueberspringt die Zeile - der Job laeuft
# weiter, nur eben anders als gedacht. Genau so faellt es nicht auf.
G_BEKANNT = {
    "G0", "G1", "G2", "G3", "G4", "G10", "G17", "G18", "G19", "G20", "G21",
    "G28", "G28.1", "G30", "G30.1", "G38.2", "G38.3", "G38.4", "G38.5",
    "G40", "G43.1", "G49", "G53", "G54", "G55", "G56", "G57", "G58", "G59",
    "G61", "G80", "G90", "G91", "G91.1", "G92", "G92.1", "G93", "G94",
}
M_BEKANNT = {"M0", "M1", "M2", "M3", "M4", "M5", "M7", "M8", "M9", "M30"}

WORT = re.compile(r"([A-Za-z])\s*(-?\d*\.?\d+)")
KLAMMER = re.compile(r"\([^)]*\)")

EILGANG = 3000.0        # mm/min, $110 der Referenzmaschine
JE_ART = 12             # so viele Fundstellen je Art, dann nur noch zaehlen


class Befund:
    """Ein Fund mit seiner Zeilennummer. Gesammelt, nicht geworfen - ein
    Trockenlauf soll alles auf einmal zeigen und nicht beim ersten Haar
    stehen bleiben."""

    def __init__(self, art, zeile, text):
        self.art, self.zeile, self.text = art, zeile, text


class Lauf:
    """Der Controller, wie er die Datei lesen wuerde."""

    def __init__(self, x_max=295.0, y_max=180.0, s_max=1000.0, accel=ACCEL,
                 lasermodus=True):
        self.x_max, self.y_max = x_max, y_max
        self.s_max, self.accel = s_max, accel
        self.lasermodus = lasermodus              # $32
        # Modaler Zustand, genau wie im Controller
        self.x = self.y = self.z = 0.0
        self.bewegung = "G0"
        self.absolut = True                       # G90
        self.zoll = False                         # G20
        self.spindel = "M5"
        self.s = 0.0
        self.f = 0.0
        self.f_gesetzt = False
        self.wartet = False
        # Ergebnis
        self.befunde = []
        self.zahl = {}                            # Art -> wie oft gefunden
        self.befehle = 0
        self.brennweg = self.leerweg = self.eilweg = 0.0
        self.sekunden = 0.0
        self.sf_max = 0.0
        self.segmente = []                        # (x0, y0, x1, y1, s)
        self.lange = []
        self.xs, self.ys = [0.0], [0.0]
        # Strecken nach Vorschub getrennt, damit estimate sie mit seinem
        # Lookahead-Modell rechnen kann - dasselbe wie in der Vorschau.
        self.nach_f = {}
        self.stopps = 0

    # ------------------------------------------------------------- Hilfen
    def merke(self, art, nr, text):
        self.zahl[art] = self.zahl.get(art, 0) + 1
        if self.zahl[art] <= JE_ART:
            self.befunde.append(Befund(art, nr, text))

    def strahl_an(self, d):
        """Brennt der Strahl auf dieser Strecke? M3 brennt immer, M4 nur
        waehrend der Fahrt - und im Lasermodus schaltet G0 ihn ohnehin ab."""
        if self.spindel == "M5" or self.s <= 0:
            return False
        if self.bewegung == "G0" and self.lasermodus:
            return False
        if self.spindel == "M4" and d <= 0:
            return False      # dynamische Leistung: kein Vorschub, kein Strahl
        return True

    # -------------------------------------------------------------- lesen
    def zeile(self, nr, roh):
        text = KLAMMER.sub(" ", roh.split(";")[0]).strip()
        if not text:
            return
        self.befehle += 1
        worte = WORT.findall(text)
        if not worte:
            self.merke("muell", nr, T("unverständlich: {z!r}").format(z=text))
            return

        zahl = {}
        for buchstabe, wert in worte:
            b, w = buchstabe.upper(), float(wert)
            if b in ("G", "M"):
                name = "%s%g" % (b, w)
                (self.g_wort if b == "G" else self.m_wort)(name, nr)
            else:
                zahl[b] = w

        if "F" in zahl:
            self.f = zahl["F"]
            self.f_gesetzt = True
        if "S" in zahl:
            self.s = zahl["S"]
            if self.s > self.s_max:
                self.merke("s_zu_gross", nr, T(
                    "S{s:.0f} über $30={m:.0f} - der Controller kappt auf voll"
                ).format(s=self.s, m=self.s_max))

        if self.wartet:
            # G4 haelt an, ohne zu fahren. Unter M3 bleibt der Strahl dabei
            # an - das frisst in Sekunden ein Loch. Unter M4 passiert nichts.
            p = zahl.get("P", zahl.get("S", 0.0))
            if self.spindel == "M3" and self.s > 0:
                self.merke("wartet_mit_strahl", nr, T(
                    "G4 wartet {p:.2f} s mit M3 S{s:.0f} - der Strahl steht "
                    "und brennt").format(p=p, s=self.s))
            self.sekunden += p
            self.wartet = False
            return

        if any(k in zahl for k in "XYZ"):
            self.fahre(nr, zahl)

    def g_wort(self, name, nr):
        if name in ("G0", "G1", "G2", "G3"):
            self.bewegung = name
        elif name == "G4":
            self.wartet = True
        elif name == "G90":
            self.absolut = True
        elif name == "G91":
            self.absolut = False
        elif name == "G21":
            self.zoll = False
        elif name == "G20":
            self.zoll = True
            self.merke("zoll", nr, T("G20 - ab hier rechnet der Controller in "
                                     "Zoll, alle Maße werden 25,4-mal so groß"))
        elif name == "G92":
            self.merke("g92", nr, T("G92 setzt den Nullpunkt mitten im Job - "
                                    "ein Soft-Reset löscht ihn wieder"))
        if name not in G_BEKANNT:
            self.merke("unbekannt", nr, T(
                "{b} kennt GRBL nicht (error:20) - die Zeile wird "
                "übersprungen").format(b=name))

    def m_wort(self, name, nr):
        if name in ("M3", "M4", "M5"):
            self.spindel = name
        elif name in ("M0", "M1"):
            self.merke("halt", nr, T("{b} hält den Job an, bis jemand am "
                                     "Rechner weiterdrückt").format(b=name))
        if name not in M_BEKANNT:
            self.merke("unbekannt", nr, T(
                "{b} kennt GRBL nicht (error:20) - die Zeile wird "
                "übersprungen").format(b=name))

    # ------------------------------------------------------------- fahren
    def fahre(self, nr, zahl):
        k = 25.4 if self.zoll else 1.0
        if self.absolut:
            nx = zahl.get("X", self.x / k) * k
            ny = zahl.get("Y", self.y / k) * k
            nz = zahl.get("Z", self.z / k) * k
        else:
            nx = self.x + zahl.get("X", 0.0) * k
            ny = self.y + zahl.get("Y", 0.0) * k
            nz = self.z + zahl.get("Z", 0.0) * k

        d = math.dist((self.x, self.y), (nx, ny))
        brennt = self.strahl_an(d)

        if brennt and not self.f_gesetzt:
            self.merke("kein_f", nr, T("G1 ohne je gesetzten Vorschub - GRBL "
                                       "antwortet error:22 und fährt nicht"))
        if brennt and d < 1e-9:
            self.merke("steht", nr, T(
                "Strahl an (S{s:.0f}), aber keine Bewegung - er brennt auf "
                "der Stelle").format(s=self.s))
        if brennt and self.f > 0:
            self.sf_max = max(self.sf_max, self.s / self.f)
        # Lange brennende Striche sind kein Fehler - ein Rechteck besteht aus
        # vieren. Sie sind nur die Stellen, an denen ein vergessenes M5 oder
        # ein als G1 geschriebenes G0 auffallen wuerde. Also auflisten statt
        # melden.
        if brennt and d > 20.0:
            self.lange.append((d, nr, self.x, self.y, nx, ny, self.s))

        for achse, wert, grenze in (("X", nx, self.x_max), ("Y", ny, self.y_max)):
            if wert < -1e-6:
                self.merke("negativ", nr, T("{a} {w:.2f} mm - hinter dem "
                                            "Nullpunkt").format(a=achse, w=wert))
            elif wert > grenze + 1e-6:
                self.merke("ausserhalb", nr, T(
                    "{a} {w:.2f} mm > Verfahrweg {g:.1f} mm"
                ).format(a=achse, w=wert, g=grenze))

        if brennt:
            self.brennweg += d
            self.segmente.append((self.x, self.y, nx, ny, self.s))
        else:
            self.leerweg += d

        # Fuer die Zeit zaehlt nicht, ob der Strahl brennt, sondern wie
        # gefahren wird: G0 im Eilgang, alles andere mit Vorschub. In einer
        # gerasterten Gravur sind die hellen Stellen G1 mit S0 - die laufen
        # mit vollem Vorschub weiter. Sie als Leerfahrt zu rechnen macht den
        # Job um Stunden zu kurz.
        if self.bewegung == "G0":
            self.eilweg += d
            self.stopps += 1
            if d > 0:
                self.sekunden += d / (EILGANG / 60.0)
        elif d > 0:
            self.nach_f.setdefault(self.f, []).append(d)

        self.x, self.y, self.z = nx, ny, nz
        self.xs.append(nx)
        self.ys.append(ny)

    # ------------------------------------------------------------ Ausgabe
    def laufzeit(self):
        """Mit demselben Modell wie die Vorschau in Laserwerk. Das ist an
        echten Laeufen geeicht - eine eigene Rechnung waere es nicht."""
        t = self.sekunden
        for f, segs in self.nach_f.items():
            if f > 0 and segs:
                t += estimate(segs, f, self.stopps)
        return t

    def bericht(self):
        z = []
        z.append(T("Befehle:        {n}").format(n=self.befehle))
        z.append(T("X:              {a:.2f} .. {b:.2f} mm   (Verfahrweg {g:.1f})"
                   ).format(a=min(self.xs), b=max(self.xs), g=self.x_max))
        z.append(T("Y:              {a:.2f} .. {b:.2f} mm   (Verfahrweg {g:.1f})"
                   ).format(a=min(self.ys), b=max(self.ys), g=self.y_max))
        z.append(T("Brennweg:       {m:.2f} m").format(m=self.brennweg / 1000))
        z.append(T("ohne Strahl:    {m:.2f} m  (davon {e:.2f} m im Eilgang)"
                   ).format(m=self.leerweg / 1000, e=self.eilweg / 1000))
        t = self.laufzeit()
        z.append(T("Laufzeit:       ca. {min:.0f} min ({h:.1f} h)"
                   ).format(min=t / 60, h=t / 3600))
        z.append(T("größtes S/F:    {sf:.2f}{warn}").format(
            sf=self.sf_max,
            warn=T("  - über 0.20 brennt sichtbar ein") if self.sf_max > 0.20 else ""))
        z.append(T("Kopf am Ende:   X {x:.2f}  Y {y:.2f}").format(x=self.x, y=self.y))
        z.append(T("Spindel am Ende: {m}").format(m=self.spindel))
        if self.spindel != "M5":
            z.append(T("  ACHTUNG: der Job endet ohne M5."))
        if self.lange:
            z.append("")
            z.append(T("Längste brennende Striche (kein Fehler, nur zum Nachsehen):"))
            for d, nr, x0, y0, x1, y1, s in sorted(self.lange, reverse=True)[:5]:
                z.append(T("  {d:6.1f} mm  Zeile {nr:<8} ({x0:.1f}, {y0:.1f}) -> "
                           "({x1:.1f}, {y1:.1f})  S{s:.0f}").format(
                    d=d, nr=nr, x0=x0, y0=y0, x1=x1, y1=y1, s=s))
        return "\n".join(z)

    def befundtext(self):
        if not self.befunde:
            return T("Keine Befunde.")
        z = [T("--- Befunde ---")]
        arten = []
        for b in self.befunde:
            if b.art not in arten:
                arten.append(b.art)
        for art in arten:
            treffer = [b for b in self.befunde if b.art == art]
            z.append("")
            z.append("%s (%d)" % (art, self.zahl[art]))
            for b in treffer:
                z.append("  %-10s %s" % (b.zeile, b.text))
            if self.zahl[art] > len(treffer):
                z.append(T("  ... und {n} weitere").format(
                    n=self.zahl[art] - len(treffer)))
        return "\n".join(z)

    def bild(self, pfad, px_je_mm=4.0):
        """Was auf dem Brett stehen wuerde: brennende Wege dunkel, je nach S."""
        from PIL import Image, ImageDraw
        if not self.segmente:
            return None
        b = int(self.x_max * px_je_mm) + 2
        h = int(self.y_max * px_je_mm) + 2
        img = Image.new("L", (b, h), 255)
        d = ImageDraw.Draw(img)
        for x0, y0, x1, y1, s in self.segmente:
            ton = int(255 - 225 * min(1.0, s / max(1.0, self.s_max)))
            d.line([(x0 * px_je_mm, h - y0 * px_je_mm),
                    (x1 * px_je_mm, h - y1 * px_je_mm)], fill=ton)
        img.save(pfad)
        return pfad


def lies(pfad, lauf, bei=None):
    """Datei durchlaufen. Rueckgabe: wo der Befehl `bei` steht, oder None."""
    halt = None
    with open(pfad, "r", errors="replace") as f:
        for nr, roh in enumerate(f, 1):
            vorher = lauf.befehle
            lauf.zeile(nr, roh)
            if bei and vorher < bei <= lauf.befehle:
                halt = (nr, lauf.x, lauf.y, lauf.spindel, lauf.s, lauf.f)
    return halt


def main():
    cfg = P.load_config()
    p = argparse.ArgumentParser(description=T("G-Code durchrechnen, ohne zu fahren"))
    p.add_argument("datei")
    p.add_argument("--x-max", type=float, default=cfg.get("x_max", 295.0))
    p.add_argument("--y-max", type=float, default=cfg.get("y_max", 180.0))
    p.add_argument("--s-max", type=float, default=1000.0,
                   help="$30 der Maschine")
    p.add_argument("--accel", type=float, default=cfg.get("accel", ACCEL),
                   help="$120 in mm/s^2")
    p.add_argument("--laser-aus", action="store_true",
                   help="rechnen, als waere $32=0 (G0 brennt dann mit)")
    p.add_argument("--bild", default=None, help="Vorschau als PNG schreiben")
    p.add_argument("--bei", type=int, default=None,
                   help="sagen, wo der Kopf bei diesem Befehl stand")
    a = p.parse_args()

    lauf = Lauf(a.x_max, a.y_max, a.s_max, a.accel, not a.laser_aus)
    halt = lies(a.datei, lauf, a.bei)

    print("=" * 66)
    print(T("Trockenlauf: {d}  ({kb:.1f} kB)").format(
        d=os.path.basename(a.datei), kb=os.path.getsize(a.datei) / 1024))
    print("=" * 66)
    print(lauf.bericht())
    if halt:
        print()
        print(T("Befehl {n} steht in Zeile {z}: X {x:.2f}  Y {y:.2f}  {m} "
                "S{s:.0f} F{f:.0f}").format(n=a.bei, z=halt[0], x=halt[1],
                                            y=halt[2], m=halt[3], s=halt[4],
                                            f=halt[5]))
    print()
    print(lauf.befundtext())
    if a.bild:
        print()
        print(T("Bild: {p}").format(p=lauf.bild(a.bild)))
    return 1 if lauf.befunde else 0


if __name__ == "__main__":
    sys.exit(main())
