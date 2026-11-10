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
import math
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


# ------------------------------------------------------------- Eichung
# Die Eichung ist eine Kette aus drei Stuecken:
#
#   Bildpunkt --Linse--> ideales Bild --Homographie--> Bettebene (mm)
#   Bettebene --Drehung, Versatz--> Maschinenkoordinaten
#
# Das erste Stueck kommt aus vielen Aufnahmen einer Punktekarte, das
# letzte aus Kreuzen, die der Kopf selbst gebrannt hat. Beides steckt in
# einem dict, das sich als JSON ablegen laesst.
#
# ACHTUNG Hoehe: Die Kette gilt fuer die Ebene, in der geeicht wurde. Ein
# Werkstueck liegt hoeher, und die Kamera schaut schraeg - was hoeher
# liegt, erscheint nach aussen verschoben. hoehe sagt, wie weit die
# Kamera ueber der Eichebene steht; damit laesst sich das herausrechnen.

EICHUNG_VERSION = 1


def _dreh(winkel_grad):
    w = math.radians(winkel_grad)
    return np.array([[math.cos(w), -math.sin(w)],
                     [math.sin(w), math.cos(w)]])


def verzeichnen(punkte, eichung):
    """Ideale Bildpunkte -> das, was die Linse daraus macht."""
    p = np.atleast_2d(np.asarray(punkte, dtype=float))
    mitte = np.asarray(eichung["mitte"], dtype=float)
    mass = float(eichung.get("mass", 1000.0))
    d = p - mitte
    r2 = (d[:, 0] ** 2 + d[:, 1] ** 2) / mass ** 2
    f = 1 + eichung["k1"] * r2 + eichung["k2"] * r2 ** 2
    return mitte + d * f[:, None]


def entzerren_punkte(punkte, eichung, runden=40):
    """Umkehrung von verzeichnen().

    Die Formel laesst sich nicht nach r aufloesen - fuenfter Grad. Statt
    einer Naeherungsformel hier die Iteration: sie braucht ein paar
    Durchlaeufe und ist dafuer so genau wie das Modell selbst.
    """
    p = np.atleast_2d(np.asarray(punkte, dtype=float))
    mitte = np.asarray(eichung["mitte"], dtype=float)
    mass = float(eichung.get("mass", 1000.0))
    d = p - mitte
    ideal = d.copy()
    for _ in range(runden):
        r2 = (ideal[:, 0] ** 2 + ideal[:, 1] ** 2) / mass ** 2
        ideal = d / (1 + eichung["k1"] * r2 + eichung["k2"] * r2 ** 2)[:, None]
    return mitte + ideal


def _anwenden(h, p):
    p = np.atleast_2d(np.asarray(p, dtype=float))
    q = np.column_stack([p, np.ones(len(p))]) @ np.asarray(h, dtype=float).T
    return q[:, :2] / q[:, 2:3]


def bild_nach_maschine(punkte, eichung):
    """Bildpunkte -> Maschinenkoordinaten in Millimetern."""
    ideal = entzerren_punkte(punkte, eichung)
    ebene = _anwenden(np.linalg.inv(np.asarray(eichung["homographie"])), ideal)
    R = _dreh(eichung.get("drehung", 0.0))
    return (eichung.get("massstab", 1.0) * (ebene @ R.T)
            + np.asarray(eichung.get("versatz", (0.0, 0.0)), dtype=float))


def _nadir(eichung):
    """Wo die Blickachse die Eichebene trifft - der Punkt, um den sich
    alles dreht, wenn das Werkstueck hoeher liegt."""
    hi = np.linalg.inv(np.asarray(eichung["homographie"]))
    return _anwenden(hi, [eichung["mitte"]])[0]


def maschine_nach_bild(punkte, eichung, dicke=0.0):
    """Maschinenkoordinaten -> Bildpunkte, fuer Material der Dicke 'dicke'.

    Ein Punkt auf einem dicken Brett liegt naeher an der Kamera. Er
    erscheint deshalb dort, wo ein Punkt der Eichebene laege, der weiter
    vom Lotpunkt entfernt ist - um den Faktor H / (H - d).
    """
    p = np.atleast_2d(np.asarray(punkte, dtype=float))
    R = _dreh(eichung.get("drehung", 0.0))
    s = eichung.get("massstab", 1.0) or 1.0
    t = np.asarray(eichung.get("versatz", (0.0, 0.0)), dtype=float)
    ebene = ((p - t) / s) @ R
    h = float(eichung.get("hoehe", 0.0) or 0.0)
    if dicke and h > dicke:
        n = _nadir(eichung)
        ebene = n + (ebene - n) * (h / (h - dicke))
    ideal = _anwenden(np.asarray(eichung["homographie"]), ebene)
    return verzeichnen(ideal, eichung)


def bett_bild(bild, eichung, x0, y0, x1, y1, px_je_mm=2.0, dicke=0.0):
    """Das Kamerabild als Draufsicht in Maschinenkoordinaten.

    Heraus kommt ein Bild, in dem ein Bildpunkt genau 1/px_je_mm
    Millimeter ist und dessen linke untere Ecke auf (x0, y0) liegt - also
    direkt das, was unter die Zeichenflaeche gehoert. Y zeigt in der
    Maschine nach oben und im Bild nach unten; das dreht diese Funktion
    mit, damit der Aufrufer nicht daran denken muss.

    Gerechnet wird rueckwaerts: fuer jeden Punkt des Ergebnisses die
    Stelle im Kamerabild. Vorwaerts bliebe das halbe Bild leer.
    """
    q = np.asarray(bild.convert("RGB"))
    u, v, drin, breite, hoehe = _bett_raster(
        (q.shape[1], q.shape[0]), eichung, x0, y0, x1, y1, px_je_mm, dicke)
    H, W = q.shape[:2]
    aus = np.zeros((hoehe * breite, 3), dtype=np.uint8)
    aus[drin] = q[np.clip(v[drin], 0, H - 1), np.clip(u[drin], 0, W - 1)]
    return Image.fromarray(aus.reshape(hoehe, breite, 3))


def _bett_raster(bildgroesse, eichung, x0, y0, x1, y1, px_je_mm, dicke):
    """Fuer jeden Punkt der Draufsicht die Stelle im Kamerabild.

    Eine Stelle fuer die Rechnung, von der das Bild und seine Abdeckung
    beide leben - sonst koennten die zwei verschiedener Meinung darueber
    sein, welcher Punkt des Bettes ueberhaupt aufgenommen wurde.
    """
    W, H = int(bildgroesse[0]), int(bildgroesse[1])
    breite = max(1, int(round((x1 - x0) * px_je_mm)))
    hoehe = max(1, int(round((y1 - y0) * px_je_mm)))
    sx = (np.arange(breite) + 0.5) / px_je_mm + x0
    sy = y1 - (np.arange(hoehe) + 0.5) / px_je_mm
    gx, gy = np.meshgrid(sx, sy)
    ziel = np.column_stack([gx.ravel(), gy.ravel()])
    quelle = maschine_nach_bild(ziel, eichung, dicke)
    u = np.rint(quelle[:, 0]).astype(int)
    v = np.rint(quelle[:, 1]).astype(int)
    drin = (u >= 0) & (u < W) & (v >= 0) & (v < H)
    return u, v, drin, breite, hoehe


def bett_abdeckung(bildgroesse, eichung, x0, y0, x1, y1, px_je_mm=2.0,
                   dicke=0.0):
    """Welche Punkte der Draufsicht die Kamera ueberhaupt aufgenommen hat.

    Das Objektiv sieht das Bett nicht ganz: vorne faellt ein Streifen
    heraus, und bett_bild legt dort Schwarz hin, weil es nichts anderes
    hinlegen kann. Schwarz ist aber keine Auskunft, und wer darin nach
    Werkstuecken sucht, findet den unaufgenommenen Streifen als erstes
    Stueck. Deshalb sagt diese Funktion getrennt, wo ueberhaupt etwas
    steht - gerechnet mit derselben Abbildung wie das Bild selbst.
    """
    _, _, drin, breite, hoehe = _bett_raster(
        bildgroesse, eichung, x0, y0, x1, y1, px_je_mm, dicke)
    return drin.reshape(hoehe, breite)


def eichung_lesbar(eichung):
    """Eine Zeile, die sagt, was die Eichung taugt.

    Mit der Flaeche, auf der sie gemessen wurde. Ein Fehler ohne seine
    Flaeche sagt nichts: 0,43 mm klingt hervorragend und galt doch nur
    fuer 140 x 100 mm in der Bettmitte - aussen waren es 6,5 mm, und
    niemand konnte das der Zeile ansehen.
    """
    if not eichung:
        return ""
    sp = eichung.get("spanne_mm")
    if isinstance(sp, (list, tuple)) and len(sp) == 2:
        wo = "über %.0f x %.0f mm" % tuple(sp)
    elif isinstance(sp, (int, float)) and sp:
        wo = "über %.0f mm Spanne" % sp
    else:
        wo = "Fläche nicht vermerkt"
    n = eichung.get("kreuze")
    womit = ("%d Kreuze" % n) if n else ("%d Aufnahmen" % eichung.get("aufnahmen", 0))
    return ("%s, Fehler %.2f mm %s (%s), geeicht bei %.0f mm Materialstärke"
            % (eichung.get("geraet", "?"), eichung.get("fehler_mm", 0.0),
               wo, womit, eichung.get("dicke", 0.0)))
