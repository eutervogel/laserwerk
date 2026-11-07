"""
Die gebrannten Kreuze im Kamerabild finden - mit der alten Eichung als Wegweiser.

    python3 kreuze_finden.py BILD.png [DICKE_MM]

Frei zu suchen ist hier der falsche Weg: die Spur auf Pappe ist ein paar
Graustufen tief, der Maschinenrahmen ringsum dagegen voller harter Kanten,
die jeden Formfilter schlagen. Die alte Eichung ist aber nicht falsch,
nur ungenau - ein paar Millimeter. Also sagt sie, wo jedes Kreuz
ungefaehr liegt, und gesucht wird nur in einem Fenster darum.

Damit ist auch der Fund eindeutig zugeordnet: Kreuz 1 ist das bei
X 30 / Y 30, nicht irgendeines.
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lw_kamera as KAM
import lw_presets as P

MASCHINE = "Creality Falcon2 Pro 22 W"
XS, YS = (30.0, 200.0, 370.0), (30.0, 200.0, 370.0)
FENSTER = 90      # halbe Kantenlaenge des Suchfensters in Bildpunkten
ARM = 34          # halbe Balkenlaenge; die aeusseren Kreuze liegen dicht am Rand
DICK = 5


def kasten(a, bh, bb):
    """Mittel ueber ein bh x bb grosses Fenster, ueber eine Summentabelle."""
    s = np.zeros((a.shape[0] + 1, a.shape[1] + 1), dtype=np.float64)
    s[1:, 1:] = a.cumsum(0).cumsum(1)
    y0 = np.clip(np.arange(a.shape[0]) - bh // 2, 0, a.shape[0])
    y1 = np.clip(np.arange(a.shape[0]) + bh // 2 + 1, 0, a.shape[0])
    x0 = np.clip(np.arange(a.shape[1]) - bb // 2, 0, a.shape[1])
    x1 = np.clip(np.arange(a.shape[1]) + bb // 2 + 1, 0, a.shape[1])
    f = (s[np.ix_(y1, x1)] - s[np.ix_(y0, x1)]
         - s[np.ix_(y1, x0)] + s[np.ix_(y0, x0)])
    return f / np.maximum(1, (y1 - y0)[:, None] * (x1 - x0)[None, :])


pfad = sys.argv[1]
dicke = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0

eichung = P.maschine_holen(P.load_maschinen(), MASCHINE)[0]["kamera"]
soll = [(x, y) for y in YS for x in XS]
vorher = KAM.maschine_nach_bild(soll, eichung, dicke=dicke)

bild = Image.open(pfad).convert("L")
a = np.asarray(bild).astype(np.float32)
grund = np.asarray(bild.filter(ImageFilter.GaussianBlur(25))).astype(np.float32)
hoch = np.clip(grund - a, 0, None)            # dunkle Spur -> positiv
punkt = np.minimum(kasten(hoch, DICK, 2 * ARM + 1),
                   kasten(hoch, 2 * ARM + 1, DICK))

# Der Rand der Pappe wirft einen harten Schattenstrich, und der schlaegt
# jedes Kreuz. Die aeusseren Kreuze liegen aber nur etwa 60 Punkte vom
# Rand weg - ein schmaler Saum von 30 nimmt den Strich mit und die
# Kreuze nicht.
unterlage = (np.asarray(bild.filter(ImageFilter.GaussianBlur(9)))
             .astype(np.float32) > np.percentile(grund, 60))
innen = kasten(unterlage.astype(np.float32), 41, 41) > 0.999
punkt[~innen] = 0
print("Suchflaeche %.1f %% des Bildes" % (100.0 * innen.mean()))

print("Eichung: Hoehe %.0f mm, Eichebene %.1f mm, Bild fuer Dicke %.1f mm"
      % (eichung.get("hoehe", 0), eichung.get("dicke", 0), dicke))
print()
print("  Kreuz        Maschine        vorhergesagt         gefunden      "
      "Versatz   Spur")
funde = []
for (mx, my), (px, py) in zip(soll, vorher):
    x0, x1 = int(px) - FENSTER, int(px) + FENSTER + 1
    y0, y1 = int(py) - FENSTER, int(py) + FENSTER + 1
    f = punkt[y0:y1, x0:x1]
    if f.max() <= 0:
        print("  X%3.0f/Y%-3.0f   kein Kreuz im Fenster" % (mx, my))
        funde.append((float(px), float(py)))
        continue
    i = int(f.argmax())
    dy, dx = divmod(i, f.shape[1])
    gx, gy = x0 + dx, y0 + dy
    # Mitte genauer: Schwerpunkt der Spur um den Treffer
    s0, s1 = int(gy) - ARM - 8, int(gy) + ARM + 9
    t0, t1 = int(gx) - ARM - 8, int(gx) + ARM + 9
    w = hoch[s0:s1, t0:t1] * innen[s0:s1, t0:t1]
    g = np.clip(w - np.percentile(w, 70), 0, None)
    yy, xx = np.mgrid[s0:s1, t0:t1]
    sx = float((xx * g).sum() / g.sum())
    sy = float((yy * g).sum() / g.sum())
    funde.append((sx, sy))
    print("  X%3.0f/Y%-3.0f   %8.2f %8.2f   %8.2f %8.2f   %+6.1f %+6.1f  %3.0f"
          % (mx, my, px, py, sx, sy, sx - px, sy - py, w.max()))

np.save(os.path.splitext(pfad)[0] + "_px.npy", np.array(funde))
np.save(os.path.splitext(pfad)[0] + "_mm.npy", np.array(soll))
print("\n%s" % (os.path.splitext(pfad)[0] + "_px.npy"))

sicht = np.clip(hoch * 10 + 20, 0, 255)
aus = Image.fromarray(sicht.astype(np.uint8)).convert("RGB")
mal = ImageDraw.Draw(aus)
for i, ((sx, sy), (px, py)) in enumerate(zip(funde, vorher)):
    mal.rectangle([px - FENSTER, py - FENSTER, px + FENSTER, py + FENSTER],
                  outline=(70, 120, 255), width=3)
    mal.line([sx - 25, sy, sx + 25, sy], fill=(90, 255, 90), width=3)
    mal.line([sx, sy - 25, sx, sy + 25], fill=(90, 255, 90), width=3)
    mal.text((px - FENSTER, py - FENSTER - 22), str(i + 1), fill=(255, 90, 90))
pruef = os.path.splitext(pfad)[0] + "_fund.png"
aus.resize((aus.width // 3, aus.height // 3)).save(pruef)
print(pruef)
