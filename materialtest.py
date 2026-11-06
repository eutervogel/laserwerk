#!/usr/bin/env python3
"""
Materialtest: ein Raster aus Feldern, jedes mit anderer Leistung und
anderem Vorschub - und jedes mit seinen Zahlen danebengraviert.

  python3 materialtest.py                      Vorgaben, ab X20 Y20
  python3 materialtest.py --x 50 --y 40
  python3 materialtest.py --s 100,300,500,700,900 --f 1000,2000,4000,6000
  python3 materialtest.py --platz 80x40        passt sich dem Platz an
  python3 materialtest.py --watt 5.5 --smax 1000

Heraus kommt materialtest.nc. Die Datei faengt dort an, wo du es sagst -
geladener G-Code laesst sich in Laserwerk nicht mehr verschieben, deshalb
steht die Stelle hier und nicht dort.

Warum die Zahlen mitgraviert werden: ein Testfeld ohne Beschriftung ist
nach drei Tagen wertlos. Man sieht, dass eins davon gut aussieht, und
weiss nicht mehr, welches es war.

Gerechnet wird in Energie je Millimeter, weil nur die zwischen Maschinen
uebertragbar ist: J/mm = Watt * (S/Smax) / (F/60). Die Tabelle steht beim
Erzeugen auf dem Schirm, damit die Zahl zum Feld nicht erst nachgerechnet
werden muss.
"""
import argparse
import math
import os

# Strichfont fuer Ziffern, in einem Kaestchen von 0..1 breit und 0..1 hoch.
# Keine Fuellung, keine Kurven - ein Laser zeichnet Striche, und bei 3 mm
# Zeichenhoehe ist alles andere ohnehin nicht zu lesen.
SEG = {
    "a": ((0, 1), (1, 1)), "b": ((1, 1), (1, 0.5)), "c": ((1, 0.5), (1, 0)),
    "d": ((0, 0), (1, 0)), "e": ((0, 0.5), (0, 0)), "f": ((0, 1), (0, 0.5)),
    "g": ((0, 0.5), (1, 0.5)),
}
SCHRIFT_J = 0.09      # J/mm - so hell, dass man die Zahlen liest

ZIFFER = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abcdg", "4": "fgbc",
          "5": "afgcd", "6": "afgecd", "7": "abc", "8": "abcdefg",
          "9": "abcdfg", "S": "afgcd", "F": "afge", "/": "bf", "-": "g"}


def zeichen(c, x, y, h, breite=0.62):
    """Striche fuer ein Zeichen, links unten bei (x, y)."""
    raus = []
    for s in ZIFFER.get(c, ""):
        (ax, ay), (bx, by) = SEG[s]
        raus.append(((x + ax * h * breite, y + ay * h),
                     (x + bx * h * breite, y + by * h)))
    return raus


def text(t, x, y, h):
    raus = []
    for c in str(t):
        if c != " ":
            raus += zeichen(c, x, y, h)
        x += h * 0.62 + h * 0.25
    return raus


def breite_von(t, h):
    return len(str(t)) * (h * 0.62 + h * 0.25) - h * 0.25


def feld(x, y, b, h, zeile):
    """Ein gefuelltes Feld, Zeile fuer Zeile - wie eine Gravur."""
    raus = []
    n = max(1, int(round(h / zeile)))
    for i in range(n + 1):
        yy = y + i * h / n
        raus.append(((x, yy), (x + b, yy)) if i % 2 == 0
                    else ((x + b, yy), (x, yy)))
    return raus


def _ausduennen(werte):
    """Jeden zweiten weglassen, die Enden behalten.

    Die Raender sind die interessanten: dort sieht man, ob der Bereich
    ueberhaupt richtig gewaehlt war.
    """
    if len(werte) <= 2:
        return werte
    raus = werte[::2]
    if werte[-1] not in raus:
        raus.append(werte[-1])
    return raus


def einpassen(ss, ff, breite, hoehe, kleinstes=3.0, luecke=2.0, schrift=2.5):
    """Raster und Feldgroesse so waehlen, dass es in den Platz passt.

    Felder muessen nicht quadratisch sein. Breite und Hoehe werden
    getrennt gerechnet, sonst begrenzt die knappere Richtung beide und
    die halbe Flaeche bleibt liegen - bei 80 x 40 mm waere aus einem
    13 x 5,5er Feld ein 5,5 x 5,5er geworden.

    Passt es auch dann nicht, fallen Werte weg, und zwar jeder zweite.
    """
    while True:
        frei_b = breite - (breite_von("9999", schrift) + 2.0)
        frei_h = hoehe - (schrift + 3.0)
        fb = (frei_b + luecke) / len(ff) - luecke
        fh = (frei_h + luecke) / len(ss) - luecke
        if fb >= kleinstes and fh >= kleinstes:
            return ss, ff, fb, fh, luecke, schrift
        if fb < kleinstes and len(ff) > 2:
            ff = _ausduennen(ff)
        elif fh < kleinstes and len(ss) > 2:
            ss = _ausduennen(ss)
        else:
            raise SystemExit(
                "Auf %g x %g mm geht selbst ein Raster von 2 x 2 Feldern "
                "nicht - mehr Platz noetig." % (breite, hoehe))


def gitter(ss, ff, x, y, breite, hoehe, zeile=0.1, smax=1000.0,
           schrift=None, schrift_s=None, schrift_f=None):
    """Das Raster als G-Code-Zeilen, eingepasst in ein Rechteck.

    Dieselbe Rechnung wie fuers Kommandozeilenwerkzeug, nur nimmt sie
    hier den Kasten entgegen, statt ihn sich aus Feldgroessen
    auszurechnen. So kann Laserwerk ein Materialtest-Element einfach
    dorthin legen, wo es gerade liegt - geschoben wird mit der Maus, und
    die Zahlen bleiben dieselben.

    Zurueck kommt (zeilen, info) wie bei den anderen Erzeugern.
    """
    schrift = schrift or max(1.8, min(3.0, hoehe / len(ss) * 0.4))
    schrift_f = schrift_f or max(ff)
    schrift_s = schrift_s if schrift_s is not None else max(1, int(smax * 0.4))
    luecke = max(1.0, min(breite, hoehe) / 25.0)
    rand_x = x + breite_von("9999", schrift) + 2.0
    rand_y = y + schrift + 3.0
    fb = (x + breite - rand_x + luecke) / len(ff) - luecke
    fh = (y + hoehe - rand_y + luecke) / len(ss) - luecke
    if fb <= 0 or fh <= 0:
        return None, None

    g = ["G21", "G90", "G94", "M4 S0"]
    pos = [None, None]
    bahnen, bahnfeeds, eilwege = [], [], []
    brenn = 0.0

    def fahre(strecken, sv, fv):
        nonlocal brenn
        lauf = []
        for (x0, y0), (x1, y1) in strecken:
            if pos[0] is None or abs(pos[0] - x0) > 1e-6 or abs(pos[1] - y0) > 1e-6:
                if len(lauf) > 1:
                    bahnen.append(lauf)
                    bahnfeeds.append(fv)
                lauf = []
                g.append("M5 S0")
                g.append("G0 X%.3f Y%.3f" % (x0, y0))
                g.append("M4 S%d" % sv)
                if pos[0] is not None:
                    eilwege.append(math.dist(pos, (x0, y0)))
                pos[0], pos[1] = x0, y0
            if not lauf:
                lauf.append((x0, y0))
            lauf.append((x1, y1))
            g.append("G1 X%.3f Y%.3f S%d F%d" % (x1, y1, sv, fv))
            brenn += math.dist((x0, y0), (x1, y1))
            pos[0], pos[1] = x1, y1
        if len(lauf) > 1:
            bahnen.append(lauf)
            bahnfeeds.append(fv)

    for zi, sv in enumerate(ss):
        yy = rand_y + zi * (fh + luecke)
        fahre(text(sv, rand_x - 2.0 - breite_von(sv, schrift),
                   yy + fh / 2 - schrift / 2, schrift), schrift_s, schrift_f)
        for sp, fv in enumerate(ff):
            fahre(feld(rand_x + sp * (fb + luecke), yy, fb, fh, zeile), sv, fv)
    for sp, fv in enumerate(ff):
        xx = rand_x + sp * (fb + luecke) + fb / 2 - breite_von(fv, schrift) / 2
        fahre(text(fv, xx, y, schrift), schrift_s, schrift_f)
    g += ["M5", "S0"]

    from lw_job import estimate
    info = dict(befehle=len(g), cut_m=brenn / 1000, trav_m=sum(eilwege) / 1000,
                breite=breite, hoehe=hoehe, xmin=x, xmax=x + breite,
                ymin=y, ymax=y + hoehe, felder=len(ss) * len(ff),
                feld_b=fb, feld_h=fh,
                sekunden=estimate(bahnen, max(ff), eilwege,
                                  feeds=bahnfeeds))
    return g, info


def vorschau(ss, ff, breite, hoehe, smax=1000.0, px_je_mm=6.0):
    """Ein Graustufenbild des Rasters - damit sich das Element auf der
    Flaeche zeichnen und schieben laesst wie ein Motiv."""
    from PIL import Image, ImageDraw
    b = max(8, int(round(breite * px_je_mm)))
    h = max(8, int(round(hoehe * px_je_mm)))
    im = Image.new("L", (b, h), 255)
    d = ImageDraw.Draw(im)
    schrift = max(1.8, min(3.0, hoehe / len(ss) * 0.4))
    luecke = max(1.0, min(breite, hoehe) / 25.0)
    rand_x = breite_von("9999", schrift) + 2.0
    rand_y = schrift + 3.0
    fb = (breite - rand_x + luecke) / len(ff) - luecke
    fh = (hoehe - rand_y + luecke) / len(ss) - luecke
    # Zu klein, um ein Raster unterzubringen: ein graues Rechteck statt
    # eines Absturzes. Dass es so nicht aufgeht, sagt das Erzeugen - und
    # bis dahin soll sich das Element wenigstens zeichnen und schieben
    # lassen.
    if fb <= 0 or fh <= 0:
        ImageDraw.Draw(im).rectangle([0, 0, b - 1, h - 1], fill=170)
        return im
    for zi, sv in enumerate(ss):
        yy = rand_y + zi * (fh + luecke)
        for sp in range(len(ff)):
            x0 = (rand_x + sp * (fb + luecke)) * px_je_mm
            y0 = h - (yy + fh) * px_je_mm
            grau = int(255 - 220 * min(1.0, sv / smax))
            d.rectangle([x0, y0, max(x0, x0 + fb * px_je_mm),
                         max(y0, y0 + fh * px_je_mm)], fill=grau)
    return im


def energie(s, f, watt, smax):
    return watt * (float(s) / smax) / (float(f) / 60.0)


def main():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--x", type=float, default=20.0)
    p.add_argument("--y", type=float, default=20.0)
    p.add_argument("--s", default="100,300,500,700,900")
    p.add_argument("--f", default="1000,2000,3000,4500,6000")
    p.add_argument("--feld", type=float, default=12.0)
    p.add_argument("--luecke", type=float, default=4.0)
    p.add_argument("--zeile", type=float, default=0.1)
    p.add_argument("--watt", type=float, default=22.0)
    p.add_argument("--smax", type=float, default=1000.0)
    p.add_argument("--schrift", type=float, default=3.0)
    p.add_argument("--schrift-j", type=float, default=SCHRIFT_J,
                   dest="schrift_j")
    p.add_argument("--platz", default=None,
                   help="vorhandener Platz, z.B. 80x40")
    p.add_argument("--ziel", default=None)
    p.add_argument("-h", "--help", action="store_true")
    a = p.parse_args()
    if a.help:
        print(__doc__)
        return
    if a.platz:
        try:
            a.platz = [float(v) for v in a.platz.lower().replace(",", "x")
                       .split("x")[:2]]
        except ValueError:
            raise SystemExit("--platz braucht zwei Masse, etwa 80x40")

    ss = [int(v) for v in a.s.split(",") if v.strip()]
    ff = [int(v) for v in a.f.split(",") if v.strip()]
    feld_b = feld_h = a.feld
    if a.platz:
        ss, ff, feld_b, feld_h, a.luecke, a.schrift = einpassen(ss, ff, *a.platz)
        print("Auf %g x %g mm eingepasst: %d x %d Felder zu %.1f x %.1f mm"
              % (a.platz[0], a.platz[1], len(ss), len(ff), feld_b, feld_h))
        print("   Leistungen %s" % ", ".join(str(v) for v in ss))
        print("   Vorschuebe %s" % ", ".join(str(v) for v in ff))
        print()
    schritt_x = feld_b + a.luecke
    schritt_y = feld_h + a.luecke
    # Links die Leistungen, unten die Vorschuebe - Platz dafuer lassen.
    rand_x = a.x + breite_von("9999", a.schrift) + 2.0
    rand_y = a.y + a.schrift + 3.0

    g = ["; Laserwerk Materialtest",
         "; %d Leistungen x %d Vorschuebe, Feld %.1f x %.1f mm, "
         "Zeilenabstand %g mm" % (len(ss), len(ff), feld_b, feld_h, a.zeile),
         "; %.1f W, Smax %g" % (a.watt, a.smax),
         "; links die Leistung S, unten der Vorschub F",
         "; origin = bottom left corner", "G21", "G90", "G94", "M4 S0"]
    pos = [0.0, 0.0]

    def fahre(strecken, s, f):
        for (x0, y0), (x1, y1) in strecken:
            if abs(pos[0] - x0) > 1e-6 or abs(pos[1] - y0) > 1e-6:
                g.append("M5 S0")
                g.append("G0 X%.3f Y%.3f" % (x0, y0))
                g.append("M4 S%d" % s)
            g.append("G1 X%.3f Y%.3f S%d F%d" % (x1, y1, s, f))
            pos[0], pos[1] = x1, y1

    # Beschriftung: lesbar, nicht tief. Ein fester Anteil von Smax taugt
    # dafuer nicht - an 22 W waeren 5 % nur 0,011 J/mm und auf Holz nicht
    # zu sehen. Gerechnet wird deshalb aus einer Zielenergie, dann stimmt
    # es an jeder Maschine.
    schrift_f = max(ff)
    schrift_s = max(1, min(int(a.smax), int(round(
        a.schrift_j * a.smax * (schrift_f / 60.0) / max(0.1, a.watt)))))

    for zi, s in enumerate(ss):
        y = rand_y + zi * schritt_y
        # Nur die Zahl, kein "S" davor: im Strichfont ist ein S nicht von
        # einer 5 zu unterscheiden, und "5900" liest sich als Zahl. Welche
        # Achse welche ist, sagt die Lage - links die Leistung, unten der
        # Vorschub.
        fahre(text(s, a.x + breite_von("9999", a.schrift)
                   - breite_von(s, a.schrift),
                   y + feld_h / 2 - a.schrift / 2, a.schrift),
              schrift_s, schrift_f)
        for sp, f in enumerate(ff):
            fahre(feld(rand_x + sp * schritt_x, y, feld_b, feld_h,
                       a.zeile), s, f)
    for sp, f in enumerate(ff):
        x = (rand_x + sp * schritt_x + feld_b / 2
             - breite_von(f, a.schrift) / 2)
        fahre(text(f, x, a.y, a.schrift), schrift_s, schrift_f)

    g += ["M5", "S0", "G0 X0 Y0"]
    ziel = a.ziel or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "materialtest.nc")
    with open(ziel, "w") as h:
        h.write("\n".join(g) + "\n")

    b = rand_x - a.x + len(ff) * schritt_x - a.luecke
    ho = rand_y - a.y + len(ss) * schritt_y - a.luecke
    print("geschrieben: %s" % ziel)
    print("Flaeche X %.1f..%.1f   Y %.1f..%.1f   (%.1f x %.1f mm)"
          % (a.x, a.x + b, a.y, a.y + ho, b, ho))
    print()
    print("Energie je Millimeter (J/mm):")
    print("        " + "".join("%9s" % ("F%d" % f) for f in ff))
    for s in ss:
        print("  S%-5d" % s + "".join(
            "%9.3f" % energie(s, f, a.watt, a.smax) for f in ff))
    print()
    print("  zum Vergleich: Sichtkreuz 0,026 - sichtbare Spur im Holz ab 0,066")
    print("  Beschriftung laeuft mit S%d/F%d = %.3f J/mm"
          % (schrift_s, schrift_f, energie(schrift_s, schrift_f, a.watt, a.smax)))


if __name__ == "__main__":
    main()
