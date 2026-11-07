"""
Ein kleines Raster aus neun Kreuzen, um einen Mittelpunkt herum.

    python3 muster.py CX CY [S] [F]

CX, CY ist die Stelle, die ungefaehr in der Mitte des Blattes liegt -
fahr den Kopf dorthin und lies ab, was Laserwerk anzeigt. Genau muss das
nicht sein: das Raster ist 166 x 126 mm, ein A4 ist 210 x 297. Selbst
wenn du dich um drei Zentimeter vertust, liegt alles noch auf dem Papier.

Das ist die Bruecke zwischen Kamerabild und Maschine: neun Punkte, deren
Koordinaten feststehen. Mehr als vier davon im Bild reichen schon.

Das Kreuz links unten ist laenger als die anderen. Sonst saehe das Raster
um 90 Grad gedreht gleich aus und die Zuordnung haette vier gleich gute
Antworten.

Der Kopf bleibt am Ende stehen, wo er ist - fahr ihn vor dem Foto weg,
sonst verdeckt er ein Kreuz.

Zur Leistung: S200 bei F1000, also 20 %. Das sind 0,264 J/mm - fuenfmal
so viel wie auf Holz noetig waere, und das hat einen Grund: weisses
Papier reflektiert blaues Licht, Holz schluckt es. Energie je Millimeter
ist zwischen Maschinen uebertragbar, zwischen Materialien nicht.

Am Geraet geprueft: 20 % markiert, darueber brennt es durch.
"""
import os
import sys

DX = 70.0                   # halbe Rasterbreite
DY = 50.0                   # halbe Rasterhoehe
ARM = 8.0
ARM_MARKE = 13.0
WATT = 22.0
SMAX = 1000.0               # mit $$ bestaetigt: $30=1000


def kreuz(x, y, arm, s, f):
    return ["G0 X%.3f Y%.3f" % (x - arm, y),
            "M4 S%d" % s,
            "G1 X%.3f Y%.3f F%d" % (x + arm, y, f),
            "M5 S0",
            "G0 X%.3f Y%.3f" % (x, y - arm),
            "M4 S%d" % s,
            "G1 X%.3f Y%.3f F%d" % (x, y + arm, f),
            "M5 S0"]


if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

cx, cy = float(sys.argv[1]), float(sys.argv[2])
s = int(sys.argv[3]) if len(sys.argv) > 3 else 200
f = int(sys.argv[4]) if len(sys.argv) > 4 else 1000

XS = (cx - DX, cx, cx + DX)
YS = (cy - DY, cy, cy + DY)

zeilen = ["G21", "G90", "G94", "M5", "S0"]
punkte = []
for y in YS:
    for x in XS:
        arm = ARM_MARKE if (x, y) == (XS[0], YS[0]) else ARM
        punkte.append((x, y, arm))
        zeilen += kreuz(x, y, arm, s, f)
zeilen += ["M5", "S0"]

if min(x - a for x, _, a in punkte) < 0 or min(y - a for _, y, a in punkte) < 0:
    print("Achtung: so liegt das Raster teilweise im Minus - der Kopf kann")
    print("da nicht hin. Nimm einen Mittelpunkt weiter von der Nullecke weg.")
    sys.exit(1)

ziel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "muster.nc")
with open(ziel, "w") as h:
    h.write("\n".join(zeilen) + "\n")

j = WATT * (s / SMAX) / (f / SMAX * SMAX / 60.0)
weg = sum(4 * a for _, _, a in punkte)
xr = (min(x - a for x, _, a in punkte), max(x + a for x, _, a in punkte))
yr = (min(y - a for _, y, a in punkte), max(y + a for _, y, a in punkte))
print("Mitte X %.0f  Y %.0f" % (cx, cy))
print("Neun Kreuze:")
for x, y, a in punkte:
    print("   X %6.1f  Y %6.1f%s" % (x, y, "   <- Marke" if a != ARM else ""))
print()
print("Raster  X %.0f..%.0f   Y %.0f..%.0f   =  %.0f x %.0f mm"
      % (xr[0], xr[1], yr[0], yr[1], xr[1] - xr[0], yr[1] - yr[0]))
print("A4 ist 210 x 297 - ringsum bleiben mindestens %.0f mm Luft,"
      % ((210 - (yr[1] - yr[0])) / 2))
print("auch wenn die Mitte um drei Zentimeter danebenliegt.")
print("S%d / F%d  =  %.3f J/mm bei %.0f W,  Brennweg %.0f mm, ca. %.0f s"
      % (s, f, WATT * (s / SMAX) / (f / 60.0), WATT, weg, weg / f * 60))
print()
print("geschrieben:", ziel)
