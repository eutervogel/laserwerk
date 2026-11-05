"""
Kamerabild auf Maschinenkoordinaten - fuer eine Maschine mit Kamera.

Die Kamera der Falcon2 Pro haengt an einem eigenen USB-Anschluss und meldet
sich als gewoehnliche UVC-Kamera (/dev/videoN), unabhaengig von der
seriellen Verbindung zum Controller. Gelesen wird mit ffmpeg, weil das
ohnehin auf dem Rechner ist; entzerrt wird mit PIL und numpy.

OpenCV braucht es dafuer nicht. Vier Punkte auf vier Punkte abzubilden ist
eine Homographie, und die ist ein lineares Gleichungssystem mit acht
Unbekannten - genau die acht Koeffizienten, die PIL fuer Image.PERSPECTIVE
erwartet. Eine Abhaengigkeit, die nur fuer eine Matrixinversion hereinkaeme,
waere schlecht bezahlt.

ACHTUNG Parallaxe: Die Entzerrung gilt fuer die Hoehe, auf der geeicht
wurde. Ein Werkstueck, das 10 mm hoeher liegt, erscheint nach aussen
verschoben - umso mehr, je weiter es von der Bildmitte entfernt ist. Deshalb
merkt sich die Eichung die Materialdicke, mit der sie entstanden ist.
"""
import glob
import os
import subprocess
import tempfile

import numpy as np
from PIL import Image


def kameras():
    """Angeschlossene Kameras als Liste von (Geraet, Name).

    Ohne v4l2-ctl bleiben die Namen leer - die Geraete findet auch ein
    Blick ins Verzeichnis. Zu jeder Kamera gehoeren oft zwei Knoten
    (Bild und Metadaten); gelesen wird vom ersten, der ein Bild liefert.
    """
    raus = []
    for g in sorted(glob.glob("/dev/video*")):
        name = ""
        try:
            aus = subprocess.run(["v4l2-ctl", "-d", g, "--info"],
                                 capture_output=True, text=True, timeout=4)
            for z in aus.stdout.splitlines():
                if "Card type" in z:
                    name = z.split(":", 1)[1].strip()
                    break
        except (OSError, subprocess.SubprocessError):
            pass
        raus.append((g, name))
    return raus


def bild_holen(geraet, breite=1280, hoehe=720, timeout=15):
    """Ein einzelnes Bild von der Kamera holen, als PIL-Bild.

    ffmpeg statt einer Bibliothek: es kann die Kamera auf MJPEG stellen,
    und genau das brauchen UVC-Kameras fuer die hohen Aufloesungen - in
    YUYV liefern sie die meist nur mit wenigen Bildern je Sekunde.
    """
    ziel = os.path.join(tempfile.mkdtemp(prefix="laserwerk-kamera-"), "bild.png")
    for format_ in ("mjpeg", None):
        befehl = ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "v4l2"]
        if format_:
            befehl += ["-input_format", format_]
        befehl += ["-video_size", "%dx%d" % (breite, hoehe),
                   "-i", geraet, "-frames:v", "1", "-y", ziel]
        try:
            fertig = subprocess.run(befehl, capture_output=True, text=True,
                                    timeout=timeout)
        except (OSError, subprocess.SubprocessError) as e:
            raise RuntimeError("ffmpeg nicht ausfuehrbar: %s" % e)
        if fertig.returncode == 0 and os.path.exists(ziel):
            with Image.open(ziel) as im:
                return im.convert("RGB")
    raise RuntimeError(fertig.stderr.strip().splitlines()[-1]
                       if fertig.stderr.strip() else "kein Bild von " + geraet)


def homographie(ziel, quelle):
    """Die acht Koeffizienten fuer Image.PERSPECTIVE.

    PIL rechnet rueckwaerts: fuer jeden Punkt (x, y) des ERGEBNISSES sucht
    es die Stelle im Urbild. Deshalb steht hier das Ziel links.

        u = (a x + b y + c) / (g x + h y + 1)
        v = (d x + e y + f) / (g x + h y + 1)

    Nach a..h umgestellt ist das je Punktpaar zwei lineare Gleichungen, bei
    vier Paaren also acht - eindeutig loesbar, solange die vier Punkte kein
    Dreieck bilden.
    """
    if len(ziel) != 4 or len(quelle) != 4:
        raise ValueError("vier Punkte, nicht mehr und nicht weniger")
    A, b = [], []
    for (x, y), (u, v) in zip(ziel, quelle):
        A.append([x, y, 1, 0, 0, 0, -x * u, -y * u])
        b.append(u)
        A.append([0, 0, 0, x, y, 1, -x * v, -y * v])
        b.append(v)
    try:
        return tuple(np.linalg.solve(np.array(A, dtype=float),
                                     np.array(b, dtype=float)))
    except np.linalg.LinAlgError:
        raise ValueError("die vier Punkte liegen auf einer Linie")


def entzerren(bild, punkte_px, punkte_mm, mm_je_px=0.2, rand=0.0):
    """Das Kamerabild in die Draufsicht der Maschine rechnen.

    punkte_px sind vier Stellen im Bild, punkte_mm dieselben vier Stellen in
    Maschinenkoordinaten - zum Beispiel vier Kreuze, die der Kopf selbst
    gefahren hat. Heraus kommt (bild, x0, y0, mm_je_px): ein Bild, in dem
    ein Bildpunkt genau mm_je_px Millimeter ist, und die Lage seiner linken
    unteren Ecke.

    Y steht in Maschinenkoordinaten nach oben, im Bild nach unten. Das
    dreht diese Funktion mit, damit der Aufrufer nicht daran denken muss.
    """
    if mm_je_px <= 0:
        raise ValueError("mm_je_px muss groesser als null sein")
    xs = [p[0] for p in punkte_mm]
    ys = [p[1] for p in punkte_mm]
    x0, x1 = min(xs) - rand, max(xs) + rand
    y0, y1 = min(ys) - rand, max(ys) + rand
    breite = max(1, int(round((x1 - x0) / mm_je_px)))
    hoehe = max(1, int(round((y1 - y0) / mm_je_px)))
    ziel = [((mx - x0) / mm_je_px, (y1 - my) / mm_je_px)
            for mx, my in punkte_mm]
    coeffs = homographie(ziel, [tuple(p) for p in punkte_px])
    aus = bild.transform((breite, hoehe), Image.PERSPECTIVE, coeffs,
                         Image.BICUBIC)
    return aus, x0, y0, mm_je_px


def eichung_pruefen(punkte_px, punkte_mm, mm_je_px=0.2):
    """Wie gut die Eichung sitzt: groesster Fehler in Millimetern.

    Mit genau vier Punkten geht die Homographie exakt durch alle vier, der
    Fehler ist also null - das sagt nur, dass die Rechnung stimmt. Erst ein
    fuenfter Punkt prueft die Eichung wirklich. Deshalb nimmt diese Funktion
    beliebig viele: die ersten vier eichen, der Rest wird gemessen.
    """
    if len(punkte_px) < 5:
        return 0.0
    coeffs = homographie([(mx / mm_je_px, my / mm_je_px)
                          for mx, my in punkte_mm[:4]],
                         [tuple(p) for p in punkte_px[:4]])
    a, b, c, d, e, f, g, h = coeffs
    schlimmster = 0.0
    for (px, py), (mx, my) in zip(punkte_px[4:], punkte_mm[4:]):
        x, y = mx / mm_je_px, my / mm_je_px
        n = g * x + h * y + 1
        if abs(n) < 1e-12:
            continue
        u, v = (a * x + b * y + c) / n, (d * x + e * y + f) / n
        schlimmster = max(schlimmster,
                          ((u - px) ** 2 + (v - py) ** 2) ** 0.5 * mm_je_px)
    return schlimmster
