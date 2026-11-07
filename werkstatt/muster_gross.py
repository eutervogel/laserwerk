"""
Neun Kreuze ueber das ganze Bett statt auf einem Fleck in der Mitte.

    python3 muster_gross.py [RAND] [S] [F]

Das erste Muster lag auf 140 x 100 mm - 9 Prozent des Betts. Maszstab,
Drehung und Versatz der Kamera stehen damit nur dort fest; vorn und
hinten ist alles hochgerechnet. Dieses hier spannt bis RAND Millimeter
an jede Kante (Vorgabe 30), also 340 x 340 mm.

Gebrannt wird nichts von hier aus - die Datei wird nur geschrieben.

Unterlage: vier Blatt A4 (2 x 2) decken 420 x 420 mm. Die Blaetter
duerfen sich ueberlappen und muessen nicht gerade liegen; gesucht werden
die Kreuze, nicht das Papier. Was zaehlt, ist dass kein Kreuz auf eine
Kante faellt.

S200 bei F1000 = 0,264 J/mm, am Geraet geprueft: markiert, brennt nicht
durch. Weisses Papier reflektiert blaues Licht - auf Holz waere das
fuenfmal zu viel.

Vor dem Foto den Kopf wegfahren, sonst verdeckt er ein Kreuz.
"""
import os
import sys

BETT_X = BETT_Y = 400.0     # $130/$131 am Geraet gelesen
ARM = 8.0
ARM_MARKE = 13.0


def kreuz(x, y, arm, s, f):
    return ["G0 X%.3f Y%.3f" % (x - arm, y),
            "M4 S%d" % s,
            "G1 X%.3f Y%.3f F%d" % (x + arm, y, f),
            "M5 S0",
            "G0 X%.3f Y%.3f" % (x, y - arm),
            "M4 S%d" % s,
            "G1 X%.3f Y%.3f F%d" % (x, y + arm, f),
            "M5 S0"]


rand = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
s = int(sys.argv[2]) if len(sys.argv) > 2 else 200
f = int(sys.argv[3]) if len(sys.argv) > 3 else 1000

XS = (rand, BETT_X / 2, BETT_X - rand)
YS = (rand, BETT_Y / 2, BETT_Y - rand)

zeilen = ["G21", "G90", "G94", "M5", "S0"]
punkte = []
for y in YS:
    for x in XS:
        arm = ARM_MARKE if (x, y) == (XS[0], YS[0]) else ARM
        punkte.append((x, y, arm))
        zeilen += kreuz(x, y, arm, s, f)
zeilen += ["M5", "S0"]

eng = [(x, y, a) for x, y, a in punkte
       if x - a < 0 or y - a < 0 or x + a > BETT_X or y + a > BETT_Y]
if eng:
    sys.exit("Kreuz(e) ragen ueber den Verfahrweg: %r - RAND groesser waehlen"
             % (eng,))

ziel = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "muster_gross.nc")
open(ziel, "w").write("\n".join(zeilen) + "\n")

print(ziel)
print("%d Kreuze, %.0f x %.0f mm aufgespannt (vorher 140 x 100)"
      % (len(punkte), XS[-1] - XS[0], YS[-1] - YS[0]))
print("S%d / F%d, Marke links unten bei X %.0f Y %.0f (laengere Arme)"
      % (s, f, XS[0], YS[0]))
for y in reversed(YS):
    print("   " + "  ".join("X%5.0f/Y%-5.0f" % (x, y) for x in XS))
