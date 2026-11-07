"""
Ein Bild von der Deckelkamera holen und ablegen - sonst nichts.

    python3 foto.py [NAME]

Holt in 2592 x 1944, der Groesse, in der geeicht wurde. Eine kleinere
Aufloesung ist bei diesem Sensor ein Ausschnitt, kein kleineres Bild -
damit zeigt jeder Koeffizient der Eichung daneben.

An die Maschine geht dabei nichts: gelesen wird nur /dev/video2.

Laserwerk darf offen bleiben, es haelt die Kamera nur waehrend eines
eigenen "Bild holen" fest.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lw_kamera as KAM

GERAET = "/dev/video2"
BREITE, HOEHE = 2592, 1944

name = sys.argv[1] if len(sys.argv) > 1 else time.strftime("foto-%H%M%S")
if not name.endswith(".png"):
    name += ".png"
ziel = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)

bild = KAM.bild_holen(GERAET, BREITE, HOEHE)
if bild.size != (BREITE, HOEHE):
    sys.exit("Kamera lieferte %dx%d statt %dx%d - so ist das Bild unbrauchbar."
             % (bild.size + (BREITE, HOEHE)))
bild.save(ziel)
print(ziel)
print("%dx%d, %.1f MB" % (bild.size + (os.path.getsize(ziel) / 1e6,)))
