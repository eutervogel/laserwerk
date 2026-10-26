#!/usr/bin/env python3
"""
Haengengebliebenen Job exakt an der Stopp-Stelle fortsetzen.

  python3 fortsetzen.py datei.nc            nur pruefen (sendet nichts)
  python3 fortsetzen.py datei.nc --start    ab der gefundenen Stelle weiter

Voraussetzung: Der Controller wurde seit dem Stopp NICHT zurueckgesetzt
(Laserwerk noch offen, kein STOPP, Kabel nicht gezogen). Dann steht der
Kopf exakt am Ende des zuletzt ausgefuehrten Befehls, und der Nullpunkt
(WCO) ist noch gueltig.

Das Skript oeffnet den Port ein zweites Mal, waehrend Laserwerk ihn noch
haelt. Dabei aendert sich die DTR-Leitung nicht - also kein Reset.
"""
import re, sys, time, glob, os
import serial

import lw_presets as P
import lw_text
from lw_text import T

lw_text.setze(P.load_config().get("sprache", "de"))

TOL = 0.006          # mm, Genauigkeit des Positionsabgleichs
RX_BUF = 127


def port():
    k = sorted(glob.glob("/dev/serial/by-id/*")) or sorted(glob.glob("/dev/ttyUSB*"))
    return os.path.realpath(k[0])


def read_lines(s, sekunden):
    buf, out, t0 = b"", [], time.time()
    while time.time() - t0 < sekunden:
        buf += s.read(s.in_waiting or 1)
        while b"\n" in buf:
            l, buf = buf.split(b"\n", 1)
            l = l.decode(errors="replace").strip()
            if l:
                out.append(l)
    return out


def position(s):
    """WPos = MPos - WCO. WCO kommt nur in jedem 10.-30. Bericht mit."""
    mpos = wco = state = None
    t0 = time.time()
    while time.time() - t0 < 15 and (mpos is None or wco is None):
        s.write(b"?")
        for l in read_lines(s, 0.3):
            if not l.startswith("<"):
                continue
            state = l.strip("<>").split("|")[0]
            m = re.search(r"MPos:([-\d.]+),([-\d.]+),([-\d.]+)", l)
            w = re.search(r"WCO:([-\d.]+),([-\d.]+),([-\d.]+)", l)
            if m: mpos = tuple(map(float, m.groups()))
            if w: wco = tuple(map(float, w.groups()))
    if mpos is None or wco is None:
        sys.exit(T("Position nicht lesbar (kein MPos/WCO empfangen)."))
    return state, mpos, wco, tuple(a - b for a, b in zip(mpos, wco))


def endpunkte(lines):
    """Endposition (x, y, z) nach jeder Zeile, dazu zuletzt gueltiges F.

    Z gehoert dazu, sobald die Datei zustellt (Fraesen, mehrere Tiefen):
    dort liegen Bahnen uebereinander, und ohne Z waere fast jede Stelle
    mehrdeutig - das Skript wuerde abbrechen, obwohl sie mit der Tiefe
    eindeutig bestimmbar ist.
    """
    x = y = z = 0.0
    feed = None
    out = []
    for l in lines:
        mx = re.search(r"X([-\d.]+)", l); my = re.search(r"Y([-\d.]+)", l)
        mz = re.search(r"Z([-\d.]+)", l)
        mf = re.search(r"F([\d.]+)", l)
        if mx: x = float(mx.group(1))
        if my: y = float(my.group(1))
        if mz: z = float(mz.group(1))
        if mf: feed = float(mf.group(1))
        out.append((x, y, z, feed, bool(mx or my or mz)))
    return out


def hat_z(lines):
    """Stellt die Datei Z zu? Reine Lasergravuren tun das nicht."""
    return any(re.search(r"Z[-\d.]", l) for l in lines)


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(T(
            "\nHaengengebliebenen Job exakt an der Stopp-Stelle fortsetzen.\n\n"
            "  python3 fortsetzen.py datei.nc            nur pruefen (sendet nichts)\n"
            "  python3 fortsetzen.py datei.nc --start    ab der gefundenen Stelle weiter\n\n"
            "Voraussetzung: Der Controller wurde seit dem Stopp NICHT zurueckgesetzt\n"
            "(Laserwerk noch offen, kein STOPP, Kabel nicht gezogen). Dann steht der\n"
            "Kopf exakt am Ende des zuletzt ausgefuehrten Befehls, und der Nullpunkt\n"
            "(WCO) ist noch gueltig.\n"))
    datei, start = a[0], "--start" in a
    lines = [l for l in (z.split(";")[0].strip() for z in open(datei)) if l]
    ep = endpunkte(lines)

    p = port()
    s = serial.Serial(p, 115200, timeout=0.1)     # DTR bleibt gesetzt -> kein Reset
    time.sleep(0.3)
    s.reset_input_buffer()
    state, mpos, wco, wpos = position(s)
    print(T("Port {p}").format(p=p))
    print(T("Zustand {z}   MPos {m}   WCO {w}").format(
        z=state, m=mpos[:3], w=wco[:3]))
    print(T("Werkstueckposition  X {x:.3f}  Y {y:.3f}  Z {z:.3f}").format(
        x=wpos[0], y=wpos[1], z=wpos[2]))

    # Z nur vergleichen, wenn die Datei es ueberhaupt anfaehrt - sonst steht
    # der Kopf auf irgendeiner Fokushoehe und kein Treffer passt.
    mit_z = hat_z(lines)
    treffer = [i for i, (x, y, z, f, bew) in enumerate(ep)
               if bew and abs(x - wpos[0]) <= TOL and abs(y - wpos[1]) <= TOL
               and (not mit_z or abs(z - wpos[2]) <= TOL)]
    if not treffer:
        s.close()
        sys.exit(T("Keine Zeile endet an dieser Position - wurde der Controller "
                   "zurueckgesetzt oder der Kopf bewegt? Dann nicht fortsetzen."))
    if len(treffer) > 1:
        # mehrere Kandidaten: der letzte gehoert zum weitesten Fortschritt,
        # aber das ist nicht eindeutig - lieber anzeigen und abbrechen
        print(T("Mehrdeutig: Zeilen {z}").format(z=treffer[:10]))
        s.close()
        sys.exit(T("Stelle nicht eindeutig - nicht automatisch fortsetzen."))
    idx = treffer[0]
    feed = next((ep[i][3] for i in range(idx, -1, -1) if ep[i][3]), 1000.0)
    rest = lines[idx + 1:]
    print(T("\nStopp-Stelle gefunden: nach Zeile {i} von {n} ({p:.1f} %)").format(
        i=idx + 1, n=len(lines), p=(idx + 1) * 100 / len(lines)))
    print(T("  letzte ausgefuehrte Zeile: {z}").format(z=lines[idx]))
    print(T("  naechste Zeile:            {z}").format(z=rest[0] if rest else "-"))
    print(T("  noch {n} Befehle, Vorschub F{f:g}").format(n=len(rest), f=feed))
    if not state.startswith("Idle"):
        s.close()
        sys.exit(T("Maschine ist nicht im Zustand Idle ({z}) - erst klaeren."
                   ).format(z=state))
    if not start:
        s.close()
        print(T("\nNur geprueft, nichts gesendet. "
                "Zum Fortsetzen mit --start aufrufen."))
        return

    pre = ["G21", "G90", "G94", f"F{feed:g}", "M4 S0"]
    queue = pre + rest
    pend, sent, done, err = [], 0, 0, 0
    t0 = time.time()
    buf = b""
    print(T("\nlaeuft - Strg-C = anhalten am naechsten Zeilenende "
            "(Position bleibt, spaeter mit --start weiter)\n"))
    try:
        while done < len(queue):
            while sent < len(queue) and sum(pend) + len(queue[sent]) + 1 <= RX_BUF:
                c = queue[sent] + "\n"
                s.write(c.encode()); pend.append(len(c)); sent += 1
            buf += s.read(s.in_waiting or 1)
            while b"\n" in buf:
                l, buf = buf.split(b"\n", 1)
                l = l.decode(errors="replace").strip()
                if l == "ok" or l.startswith("error"):
                    if pend: pend.pop(0)
                    done += 1
                    if l.startswith("error"):
                        err += 1
                    if done % 2000 == 0:
                        el = time.time() - t0
                        print(T("\r{p} %  noch ~{min:.0f} min  Fehler {err}   ").format(
                            p=done * 100 // len(queue),
                            min=el / done * (len(queue) - done) / 60, err=err),
                            end="", flush=True)
                elif l.startswith("ALARM"):
                    s.write(b"!")
                    sys.exit(T("\n{z} - angehalten.").format(z=l))
                # Statusberichte (auch auf Laserwerks '?') einfach ignorieren
        print(T("\nfertig in {min:.0f} min, {err} Uebertragungsfehler").format(
            min=(time.time() - t0) / 60, err=err))
    except KeyboardInterrupt:
        # Nicht mitten im Segment anhalten: nichts mehr nachschieben und die
        # gepufferten Befehle zu Ende fahren lassen. Dann steht der Kopf
        # wieder exakt auf einem Zeilenende und ist erneut auffindbar.
        print(T("\nAnhalten: sende nichts mehr, Puffer wird abgearbeitet ..."))
        t1 = time.time()
        while done < sent and time.time() - t1 < 60:
            buf += s.read(s.in_waiting or 1)
            while b"\n" in buf:
                l, buf = buf.split(b"\n", 1)
                if l.strip() in (b"ok",) or l.strip().startswith(b"error"):
                    done += 1
        time.sleep(1.0)
        print(T("steht. Laser aus (M4, keine Bewegung), Position und Nullpunkt "
                "erhalten.\nWeitermachen: python3 fortsetzen.py DATEI --start"))
    finally:
        s.close()


if __name__ == "__main__":
    main()
