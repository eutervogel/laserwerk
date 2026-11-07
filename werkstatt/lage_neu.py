"""
Was die alte Eichung ueber das ganze Bett sagt - und was die neuen
Kreuze dagegen sagen.

    python3 lage_neu.py BILD_px.npy BILD_mm.npy DICKE_MM

Zwei Fragen getrennt:

1. Wie weit liegt Laserwerk heute daneben, an welcher Stelle? Dafuer
   werden die gefundenen Bildpunkte mit der *alten* Eichung in
   Millimeter gerechnet und mit den Stellen verglichen, an denen der
   Kopf die Kreuze gebrannt hat.

2. Was kaeme heraus, wenn Lage (Maszstab, Drehung, Versatz) neu aus
   diesen Kreuzen bestimmt wird? Linse und Homographie bleiben, die
   stammen aus der Punktekarte.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lw_kamera as KAM
import lw_presets as P

MASCHINE = "Creality Falcon2 Pro 22 W"

px = np.load(sys.argv[1])
mm = np.load(sys.argv[2])
dicke = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
gut = [i for i in range(len(px))] if len(sys.argv) < 5 else \
      [int(i) for i in sys.argv[4].split(",")]

e = P.maschine_holen(P.load_maschinen(), MASCHINE)[0]["kamera"]
H = float(e.get("hoehe", 0.0))


def ebene(punkte):
    """Bildpunkte -> Ebenenkoordinaten, Hoehe herausgerechnet."""
    ideal = KAM.entzerren_punkte(punkte, e)
    q = KAM._anwenden(np.linalg.inv(np.asarray(e["homographie"])), ideal)
    if dicke and H > dicke:
        n = KAM._nadir(e)
        q = n + (q - n) * ((H - dicke) / H)
    return q


def starr(q, s, grad, t):
    w = np.radians(grad)
    R = np.array([[np.cos(w), -np.sin(w)], [np.sin(w), np.cos(w)]])
    return s * (q @ R.T) + t


q = ebene(px)
alt = starr(q, e["massstab"], e["drehung"], np.asarray(e["versatz"]))

print("Alte Eichung, angewandt auf die neuen Kreuze (Hoehe %.0f mm, Pappe %.1f mm)"
      % (H, dicke))
print()
print("  Kreuz        soll            ist (alte Eichung)      Fehler")
for i, ((sx, sy), (ix, iy)) in enumerate(zip(mm, alt)):
    stern = " " if i in gut else "*"
    print("%s X%3.0f/Y%-3.0f   %6.1f %6.1f      %7.2f %7.2f     %+6.2f %+6.2f  = %5.2f mm"
          % (stern, sx, sy, sx, sy, ix, iy, ix - sx, iy - sy,
             np.hypot(ix - sx, iy - sy)))
f = alt[gut] - mm[gut]
print("\n  Mittlerer Fehler %.2f mm, groesster %.2f mm   (* nicht mitgerechnet)"
      % (np.sqrt((f ** 2).sum(axis=1)).mean(), np.sqrt((f ** 2).sum(axis=1)).max()))

# ---- Lage neu bestimmen: Maszstab, Drehung, Versatz auf die Kreuze
a, b = q[gut], mm[gut]
am, bm = a.mean(axis=0), b.mean(axis=0)
A, B = a - am, b - bm
U, S, Vt = np.linalg.svd(A.T @ B)
R = (U @ Vt).T
if np.linalg.det(R) < 0:
    Vt[-1] *= -1
    R = (U @ Vt).T
s = float((S.sum() if np.linalg.det(U @ Vt) > 0 else S[0] - S[1]) / (A ** 2).sum())
t = bm - s * (am @ R.T)
grad = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
neu = s * (q @ R.T) + t
g = neu[gut] - mm[gut]
rest = np.sqrt((g ** 2).sum(axis=1))

print()
print("Lage neu aus diesen Kreuzen:")
print("  Maszstab  %.5f   (alt %.5f, Unterschied %+.2f %%)"
      % (s, e["massstab"], 100 * (s / e["massstab"] - 1)))
print("  Drehung   %+.4f Grad   (alt %+.4f)" % (grad, e["drehung"]))
print("  Versatz   %.2f / %.2f   (alt %.2f / %.2f)"
      % (t[0], t[1], e["versatz"][0], e["versatz"][1]))
print("  Restfehler %.2f mm im Mittel, %.2f mm groesster   (alt: 0,43 mm auf 140 x 100 mm)"
      % (rest.mean(), rest.max()))
print()
print("  Kreuz        Rest nach der Neuanpassung")
for i in gut:
    print("   X%3.0f/Y%-3.0f   %+6.2f %+6.2f  = %5.2f mm"
          % (mm[i][0], mm[i][1], neu[i][0] - mm[i][0], neu[i][1] - mm[i][1],
             np.hypot(*(neu[i] - mm[i]))))
