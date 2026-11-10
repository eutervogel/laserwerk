"""
Die Kamera einrichten - mit der Maschine als Lineal.

Bisher lief das in zwei Schritten mit zwei Datensaetzen: elf Aufnahmen
einer gedruckten Punktekarte fuer die Linse, danach gebrannte Kreuze fuer
die Lage. Beide lagen nur in der Bildmitte, und darum stand am Rand des
Betts ein Fehler von mehreren Millimetern, den die Fehlerzahl im
Kamerareiter nicht zeigte.

Hier faellt die Karte weg. **Die Maschine ist das bessere Lineal:** sie
weiss auf Hundertstel, wo ihr Kopf steht, waehrend ein Tintenstrahldrucker
20 mm Mittenabstand nicht auf ein Zehntel trifft. Ein Raster gebrannter
Kreuze ueber das ganze Bett belegt jede Ecke der Arbeitsflaeche und
liefert Linse, Homographie und Lage aus *einem* Foto in *einem*
Anpassungsschritt.

Das Bett ist nicht das ganze Bild - bei der Falcon2 fuellt es knapp die
Haelfte der Bildbreite, der Rest ist Gehaeuse. Die Verzeichnung ist
darum nur dort festgelegt, wo das Bett liegt. Das genuegt: ausserhalb
wird nie etwas in Millimeter umgerechnet.

Der Ablauf:

    punkte = raster_punkte(400, 400)        # 25 Kreuze, 30 mm Rand
    zeilen = raster_gcode(punkte)           # ein ganz normaler Job
    ... der Benutzer brennt ihn, dann ein Foto ...
    eichung, funde, guete = eichen(bild, punkte, start=alte_eichung)

Gebrannt wird von hier aus nichts. Diese Datei schreibt Zeilen und
rechnet; die Maschine bedient der Benutzer.

Warum die Anpassung so herum gerechnet wird
-------------------------------------------
Gesucht sind k1, k2, die Verzeichnungsmitte und eine Homographie - zwoelf
Zahlen. Das sieht nach einem grossen nichtlinearen Problem aus, ist aber
keines: **stehen k1, k2 und die Mitte fest, ist die Homographie linear**
zu bestimmen. Uebrig bleibt eine Suche ueber vier Zahlen, und die ist
klein genug fuer ein paar Dutzend Durchlaeufe mit numerischer
Jacobimatrix.

Gemessen wird der Fehler dabei in **Millimetern**, nicht in Bildpunkten.
Das ist nicht dasselbe: die Tonnenverzeichnung staucht den Bildrand, dort
sind Millimeter weniger Bildpunkte wert. Wer in Bildpunkten anpasst,
gewichtet die Bildmitte hoeher - genau die Stelle, an der ohnehin alles
stimmt.
"""
import numpy as np
from PIL import Image, ImageFilter

import lw_kamera as KAM

EICHUNG_VERSION = 1

RASTER = 5                 # Kreuze je Achse
RAND = 30.0                # mm Abstand zur Bettkante
ARM = 8.0                  # mm halbe Balkenlaenge eines Kreuzes
ARM_MARKE = 13.0           # das Kreuz links unten, als Richtungsmarke
S_RASTER = 200             # am Geraet geprueft: markiert Papier, brennt nicht durch
F_RASTER = 1000
MASS = 1000.0              # Bezugslaenge der Verzeichnungsformel, wie in lw_kamera

MINDESTKREUZE = 6          # weniger traegt die Anpassung nicht
# Ab so vielen Kreuzen wird auch die Verzeichnungsmitte gesucht - und das
# ist der Hebel, nicht die Zahl der Kreuze. Am kuenstlichen Modell: mit
# fester Mitte in der Bildmitte bleiben 1,3 mm im Mittel und 3,4 mm am
# Rand stehen, auch mit fuenfundzwanzig Kreuzen. Mit freier Mitte faellt
# der Fehler auf null. Die Linse sitzt eben nicht mittig im Bild.
MITTE_AB = 9


# --------------------------------------------------------------- Raster

def raster_punkte(x_max, y_max, rand=RAND, n=RASTER):
    """Die Soll-Stellen der Kreuze in Maschinenkoordinaten.

    Von vorn links nach hinten rechts, zeilenweise - dieselbe Reihenfolge,
    in der die Suche sie spaeter erwartet.
    """
    n = max(2, int(n))
    if rand < 0 or 2 * rand >= min(x_max, y_max):
        raise ValueError("Rand passt nicht auf das Bett")
    xs = [rand + (x_max - 2 * rand) * i / (n - 1.0) for i in range(n)]
    ys = [rand + (y_max - 2 * rand) * i / (n - 1.0) for i in range(n)]
    return [(x, y) for y in ys for x in xs]


def raster_gcode(punkte, x_max=None, y_max=None, s=S_RASTER, f=F_RASTER,
                 arm=ARM, arm_marke=ARM_MARKE, parken=(0.0, 0.0)):
    """Der Brennauftrag fuer das Raster, als Liste von Zeilen.

    Das erste Kreuz - vorn links - bekommt laengere Arme. Damit ist auf
    dem Foto auf einen Blick zu sehen, ob das Blatt verdreht liegt oder
    ob X und Y vertauscht sind; ohne diese Marke sieht ein gedrehtes
    Raster aus wie ein richtiges.

    Am Ende faehrt der Kopf an 'parken'. Er steht sonst ueber dem zuletzt
    gebrannten Kreuz und verdeckt es auf dem Foto.
    """
    if not punkte:
        raise ValueError("keine Punkte")
    if x_max and y_max:
        eng = [(x, y) for x, y in punkte
               if x - arm_marke < 0 or y - arm_marke < 0
               or x + arm_marke > x_max or y + arm_marke > y_max]
        if eng:
            raise ValueError("Kreuze ragen ueber den Verfahrweg: %r" % (eng,))
    zeilen = ["G21", "G90", "G94", "M5", "S0"]
    for i, (x, y) in enumerate(punkte):
        a = arm_marke if i == 0 else arm
        zeilen += ["G0 X%.3f Y%.3f" % (x - a, y),
                   "M4 S%d" % s,
                   "G1 X%.3f Y%.3f F%d" % (x + a, y, f),
                   "M5 S0",
                   "G0 X%.3f Y%.3f" % (x, y - a),
                   "M4 S%d" % s,
                   "G1 X%.3f Y%.3f F%d" % (x, y + a, f),
                   "M5 S0"]
    zeilen += ["M5", "S0", "G0 X%.3f Y%.3f" % tuple(parken)]
    return zeilen


# -------------------------------------------------------- Kreuze suchen

def _kasten(a, bh, bb):
    """Mittelwert ueber ein bh x bb grosses Fenster, ueber eine Summentabelle.

    Ein Kreuz ist ein waagerechter *und* ein senkrechter Balken durch
    denselben Punkt. Zwei solche Kastenmittel, danach das Minimum beider:
    gross wird das nur dort, wo beide Balken liegen. Eine einzelne
    Schramme oder eine Blattkante faellt durch.
    """
    s = np.zeros((a.shape[0] + 1, a.shape[1] + 1), dtype=np.float64)
    s[1:, 1:] = a.cumsum(0).cumsum(1)
    y0 = np.clip(np.arange(a.shape[0]) - bh // 2, 0, a.shape[0])
    y1 = np.clip(np.arange(a.shape[0]) + bh // 2 + 1, 0, a.shape[0])
    x0 = np.clip(np.arange(a.shape[1]) - bb // 2, 0, a.shape[1])
    x1 = np.clip(np.arange(a.shape[1]) + bb // 2 + 1, 0, a.shape[1])
    f = (s[np.ix_(y1, x1)] - s[np.ix_(y0, x1)]
         - s[np.ix_(y1, x0)] + s[np.ix_(y0, x0)])
    return f / np.maximum(1, (y1 - y0)[:, None] * (x1 - x0)[None, :])


def spur(bild, saum=41):
    """Was im Bild dunkler ist als seine Umgebung - und wo gesucht werden darf.

    Nicht schwellen, sondern die Beleuchtung herausrechnen: Bild minus
    stark verwischtes Bild. Danach ist der Kontrast ueberall gleich, egal
    wie hell die Stelle ausgeleuchtet war - und auf Pappe ist die Spur nur
    ein paar Graustufen tief.

    Der Rand der Unterlage wirft einen harten Schattenstrich, und der
    schlaegt jedes Kreuz. Ein schmaler Saum nimmt ihn mit; breit darf er
    nicht sein, sonst nimmt er die aeusseren Kreuze gleich mit.
    """
    grau = bild.convert("L")
    a = np.asarray(grau).astype(np.float32)
    radius = max(8, grau.width // 100)
    grund = np.asarray(grau.filter(ImageFilter.GaussianBlur(radius))).astype(np.float32)
    hoch = np.clip(grund - a, 0, None)
    hell = np.asarray(grau.filter(ImageFilter.GaussianBlur(max(3, radius // 3))))
    unterlage = (hell.astype(np.float32) > np.percentile(grund, 60))
    saum = max(3, int(saum) | 1)
    innen = _kasten(unterlage.astype(np.float32), saum, saum) > 0.999
    return hoch, innen


def kreuze_suchen(bild, vorhersage, arm_px=34, fenster=None, dick=5,
                  streuung=None, vorarbeit=None):
    """Die gebrannten Kreuze im Bild finden, jedes in einem Fenster.

    Frei zu suchen ist der falsche Weg: die Spur auf Pappe ist ein paar
    Graustufen tief, der Maschinenrahmen ringsum dagegen voller harter
    Kanten, die jeden Formfilter schlagen. Die Vorhersage - aus der alten
    Eichung oder aus vier angeklickten Eckkreuzen - ist nicht falsch, nur
    ungenau. Sie sagt auf ein paar Millimeter, wo jedes Kreuz liegt, und
    damit ist der Fund auch gleich zugeordnet.

    **Im Fenster gewinnt nicht die staerkste Antwort, sondern die
    naechste.** Wer das uebersieht, findet die Kanten der Unterlage: zwei
    uebereinandergelegte Blaetter kreuzen sich, und so eine Kreuzung ist
    um ein Vielfaches dunkler als eine gebrannte Spur. Am 10.11.2026 hat
    genau das aus fuenfundzwanzig Kreuzen sieben Fehlgriffe gemacht und
    eine Eichung mit 14 mm Fehler. Die Vorhersage liegt dagegen auf ein
    paar Bildpunkte genau - also zaehlt die Antwort mal einer Glocke um
    die Vorhersage, und die Kante zwei Zentimeter weiter faellt durch.

    Zurueck kommen die Fundstellen und zu jeder eine Guete. Guete 0 heisst
    'nicht gefunden' - dann steht an der Stelle die Vorhersage, damit der
    Aufrufer zeichnen kann, wo er gesucht hat.
    """
    vorhersage = np.atleast_2d(np.asarray(vorhersage, dtype=float))
    arm_px = max(4, int(round(arm_px)))
    if fenster is None:
        fenster = _fensterbreite(vorhersage, arm_px)
    fenster = max(arm_px + 4, int(fenster))
    streuung = max(2.0, float(streuung if streuung else fenster / 2.0))
    dick = max(1, int(dick) | 1)

    punkt = kreuzantwort(bild, arm_px, dick, vorarbeit)
    H, W = punkt.shape
    yy, xx = np.mgrid[-fenster:fenster + 1, -fenster:fenster + 1]
    glocke = np.exp(-(xx ** 2 + yy ** 2) / (2.0 * streuung ** 2))

    funde, guete = [], []
    for px, py in vorhersage:
        x0, y0 = int(px) - fenster, int(py) - fenster
        a0, b0 = max(0, x0), max(0, y0)
        a1 = min(W, x0 + 2 * fenster + 1)
        b1 = min(H, y0 + 2 * fenster + 1)
        if a1 - a0 < 3 or b1 - b0 < 3:
            funde.append((px, py))
            guete.append(0.0)
            continue
        f = (punkt[b0:b1, a0:a1]
             * glocke[b0 - y0:b1 - y0, a0 - x0:a1 - x0])
        if f.max() <= 0:
            funde.append((px, py))
            guete.append(0.0)
            continue
        dy, dx = divmod(int(f.argmax()), f.shape[1])
        mitte = _feinlage(punkt, a0 + dx, b0 + dy)
        funde.append(mitte)
        guete.append(float(punkt[b0 + dy, a0 + dx]))
    return np.array(funde, dtype=float), np.array(guete, dtype=float)


def spurbild(hoch):
    """Die Spur als Bild zum Ansehen: dunkel, wo etwas gebrannt ist.

    Im rohen Kamerabild ist eine gebrannte Spur ein paar Graustufen tief
    und liegt unter einem Beleuchtungsverlauf. Herausgerechnet und
    aufgedreht ist sie ein schwarzes Kreuz auf Weiss - das kann man
    ansehen und anklicken.
    """
    return Image.fromarray(
        np.clip(255.0 - np.asarray(hoch) * 8.0, 0, 255).astype(np.uint8))


def kreuzantwort(bild, arm_px, dick=5, vorarbeit=None):
    """Wie sehr jede Stelle im Bild nach einem Kreuz aussieht.

    'vorarbeit' ist das Ergebnis von spur() - der teure Teil, und er
    haengt nicht an der Armlaenge. Wer zweimal mit verschiedenen Armen
    sucht, rechnet ihn sonst zweimal.
    """
    hoch, innen = vorarbeit if vorarbeit else spur(bild)
    dick = max(1, int(dick) | 1)
    arm_px = max(4, int(round(arm_px)))
    punkt = np.minimum(_kasten(hoch, dick, 2 * arm_px + 1),
                       _kasten(hoch, 2 * arm_px + 1, dick))
    return np.where(innen, punkt, 0.0)


def _feinlage(punkt, gx, gy, rand=6):
    """Die Mitte genauer als auf den Bildpunkt.

    Gewogen wird die Kreuzantwort selbst, nicht die Spur: die Antwort hat
    genau in der Mitte ihre Spitze, waehrend die Spur auch entlang der
    Arme dunkel ist - und wenn daneben eine fremde Kante liegt, zieht die
    den Schwerpunkt der Spur zu sich herueber.
    """
    H, W = punkt.shape
    y0, y1 = max(0, gy - rand), min(H, gy + rand + 1)
    x0, x1 = max(0, gx - rand), min(W, gx + rand + 1)
    s = punkt[y0:y1, x0:x1]
    w = np.clip(s - s.min(), 0, None)
    if w.sum() <= 0:
        return float(gx), float(gy)
    ay, ax = np.mgrid[y0:y1, x0:x1]
    return float((ax * w).sum() / w.sum()), float((ay * w).sum() / w.sum())


def _fensterbreite(vorhersage, arm_px):
    """Halb so breit wie der engste Abstand zweier Kreuze - so koennen sich
    zwei Fenster nie um dasselbe Kreuz streiten."""
    if len(vorhersage) < 2:
        return 6 * arm_px
    d = vorhersage[:, None, :] - vorhersage[None, :, :]
    w = np.hypot(d[..., 0], d[..., 1])
    w[np.arange(len(w)), np.arange(len(w))] = np.inf
    return int(max(arm_px + 4, min(6 * arm_px, 0.45 * w.min())))


# ------------------------------------------------------------ Anpassen

def _normieren(p):
    """Verschieben und skalieren, damit die Ausgleichsrechnung nicht an
    den Groessenordnungen scheitert: Millimeter gehen bis 400, Bildpunkte
    bis 2600, und ihr Produkt steht in derselben Matrix."""
    p = np.asarray(p, dtype=float)
    mitte = p.mean(axis=0)
    weite = np.abs(p - mitte).mean()
    weite = weite if weite > 1e-9 else 1.0
    T = np.array([[1 / weite, 0, -mitte[0] / weite],
                  [0, 1 / weite, -mitte[1] / weite],
                  [0, 0, 1.0]])
    return (p - mitte) / weite, T


def homographie_viele(von, nach, runden=3):
    """Eine Homographie durch beliebig viele Punktpaare, als 3x3-Matrix.

    lw_kamera.homographie() will genau vier Paare - damit ist sie exakt
    loesbar und prueft nichts. Hier sind es fuenfundzwanzig, und gesucht
    ist der beste Kompromiss.

    Die lineare Loesung minimiert nicht den Abstand, sondern den mit dem
    Nenner multiplizierten Abstand. Ein paar Durchlaeufe, in denen jede
    Zeile durch ihren eigenen Nenner geteilt wird, machen daraus den
    richtigen Abstand - billiger als eine nichtlineare Anpassung und hier
    genau so gut.
    """
    von = np.atleast_2d(np.asarray(von, dtype=float))
    nach = np.atleast_2d(np.asarray(nach, dtype=float))
    if len(von) != len(nach) or len(von) < 4:
        raise ValueError("mindestens vier Punktpaare, und gleich viele")
    a, Tv = _normieren(von)
    b, Tn = _normieren(nach)
    w = np.ones(len(a))
    H = np.eye(3)
    for _ in range(max(1, runden)):
        A = np.zeros((2 * len(a), 8))
        r = np.zeros(2 * len(a))
        for i, ((x, y), (u, v)) in enumerate(zip(a, b)):
            A[2 * i] = [x, y, 1, 0, 0, 0, -x * u, -y * u]
            A[2 * i + 1] = [0, 0, 0, x, y, 1, -x * v, -y * v]
            r[2 * i], r[2 * i + 1] = u, v
            A[2 * i:2 * i + 2] /= w[i]
            r[2 * i:2 * i + 2] /= w[i]
        loesung, *_ = np.linalg.lstsq(A, r, rcond=None)
        H = np.append(loesung, 1.0).reshape(3, 3)
        w = np.maximum(1e-6, a @ H[2, :2] + H[2, 2])
    return np.linalg.inv(Tn) @ H @ Tv


def _ideal(punkte_px, k1, k2, mitte):
    return KAM.entzerren_punkte(punkte_px,
                                {"k1": k1, "k2": k2,
                                 "mitte": list(mitte), "mass": MASS})


def _anpassung(punkte_px, punkte_mm, p):
    """Zu gegebenem (k1, k2, Mitte) die beste Homographie und ihr Rest.

    Das ist der Kern: die vier Zahlen in p sind die einzigen, nach denen
    wirklich gesucht werden muss. Steht die Linse fest, ist der Rest eine
    Ausgleichsgerade.
    """
    k1, k2, cx, cy = p
    ideal = _ideal(punkte_px, k1, k2, (cx, cy))
    H = homographie_viele(ideal, punkte_mm)
    ist = KAM._anwenden(H, ideal)
    return ist - np.asarray(punkte_mm, dtype=float), H


def _lm(rest, p0, runden=80):
    """Levenberg-Marquardt mit numerischer Jacobimatrix.

    Vier Unbekannte und fuenfzig Gleichungen - da lohnt keine von Hand
    abgeleitete Jacobimatrix. Vier zusaetzliche Auswertungen je Schritt
    kosten nichts, und eine falsch abgeleitete Formel kostet einen Tag.
    """
    p = np.asarray(p0, dtype=float).copy()
    r = rest(p)
    best = float((r ** 2).sum())
    lam = 1e-3
    for _ in range(runden):
        J = np.zeros((len(r), len(p)))
        for i in range(len(p)):
            h = max(1e-7, abs(p[i]) * 1e-4)
            q = p.copy()
            q[i] += h
            J[:, i] = (rest(q) - r) / h
        A = J.T @ J
        g = J.T @ r
        schritt = None
        for _ in range(14):
            daempfung = np.diag(np.maximum(np.diag(A), 1e-12))
            try:
                d = np.linalg.solve(A + lam * daempfung, -g)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            rn = rest(p + d)
            s = float((rn ** 2).sum())
            if s < best:
                p, r, best, schritt = p + d, rn, s, d
                lam = max(lam * 0.3, 1e-10)
                break
            lam *= 10
        if schritt is None or np.linalg.norm(schritt) < 1e-11:
            break
    return p, best


def anpassen(punkte_px, punkte_mm, bildgroesse, hoehe=0.0, dicke=0.0,
             mitte_frei=None, vorlage=None):
    """Aus gefundenen Kreuzen eine vollstaendige Eichung rechnen.

    punkte_px sind die Stellen im Bild, punkte_mm die Stellen, an denen
    der Kopf sie gebrannt hat. Heraus kommt ein Eichungs-dict, wie es
    lw_kamera erwartet.

    Massstab, Drehung und Versatz stehen darin auf eins, null und null:
    sie waren frueher noetig, weil die Homographie aus der Punktekarte kam
    und in deren Koordinaten rechnete. Jetzt bildet die Homographie direkt
    von Maschinenmillimetern ab, und eine Aehnlichkeitsabbildung
    obendrauf haette keine eigene Bedeutung mehr.
    """
    px = np.atleast_2d(np.asarray(punkte_px, dtype=float))
    mm = np.atleast_2d(np.asarray(punkte_mm, dtype=float))
    if len(px) != len(mm):
        raise ValueError("zu jedem Bildpunkt gehoert ein Millimeterpunkt")
    if len(px) < MINDESTKREUZE:
        raise ValueError("mindestens %d Kreuze, gefunden sind %d"
                         % (MINDESTKREUZE, len(px)))
    breite, hoehe_px = int(bildgroesse[0]), int(bildgroesse[1])
    if mitte_frei is None:
        mitte_frei = len(px) >= MITTE_AB
    mitte0 = (breite / 2.0, hoehe_px / 2.0)

    def rest(p):
        p = np.asarray(p, dtype=float)
        voll = p if mitte_frei else np.append(p[:2], mitte0)
        return _anpassung(px, mm, voll)[0].ravel()

    # Erst grob nach k1 absuchen. Die Verzeichnung ist stark - aus k1 = 0
    # heraus laeuft die Anpassung in ein Nebental und bleibt dort sitzen.
    bestes, bester = None, np.inf
    for k1 in np.linspace(-0.6, 0.3, 19):
        try:
            r = rest([k1, 0.0] + ([mitte0[0], mitte0[1]] if mitte_frei else []))
        except (ValueError, np.linalg.LinAlgError):
            continue
        s = float((r ** 2).sum())
        if s < bester:
            bestes, bester = k1, s
    if bestes is None:
        raise ValueError("die Kreuze tragen keine Eichung - liegen sie auf "
                         "einer Linie?")
    start = [bestes, 0.0] + ([mitte0[0], mitte0[1]] if mitte_frei else [])
    p, _ = _lm(rest, start)
    voll = p if mitte_frei else np.append(p[:2], mitte0)
    abstand, H = _anpassung(px, mm, voll)

    eichung = dict(vorlage or {})
    eichung.update({
        "version": EICHUNG_VERSION,
        "bild": [breite, hoehe_px],
        "k1": float(voll[0]), "k2": float(voll[1]),
        "mitte": [float(voll[2]), float(voll[3])], "mass": MASS,
        "homographie": np.linalg.inv(H).tolist(),
        "massstab": 1.0, "drehung": 0.0, "versatz": [0.0, 0.0],
        "hoehe": float(hoehe), "dicke": float(dicke),
        "kreuze": int(len(px)),
        "spanne_mm": [float(np.ptp(mm[:, 0])), float(np.ptp(mm[:, 1]))],
    })
    weit = np.hypot(abstand[:, 0], abstand[:, 1])
    eichung["fehler_mm"] = float(weit.max())
    eichung["fehler_mittel_mm"] = float(weit.mean())
    return eichung


def fehler(eichung, punkte_px, punkte_mm):
    """Was die Eichung an diesen Kreuzen danebenliegt, in Millimetern.

    Gerechnet wird durch lw_kamera, nicht durch die Anpassung - sonst
    prueft sich die Rechnung an sich selbst und merkt nicht, wenn das
    Ergebnis gar nicht in der Form abgelegt wurde, die das Programm
    spaeter liest.
    """
    ist = KAM.bild_nach_maschine(punkte_px, eichung)
    d = ist - np.atleast_2d(np.asarray(punkte_mm, dtype=float))
    weit = np.hypot(d[:, 0], d[:, 1])
    return float(weit.mean()), float(weit.max()), weit


# ----------------------------------------------------------- Der Ablauf

def eichung_aus_ecken(ecken_px, ecken_mm, bildgroesse, hoehe=0.0, dicke=0.0):
    """Ein Wegweiser aus vier angeklickten Eckkreuzen, ohne Linse.

    Beim allerersten Eichen gibt es keine alte Eichung, die sagt, wo die
    Kreuze liegen - und ohne diesen Wegweiser ist die Suche aussichtslos.
    Vier Ecken reichen fuer eine Homographie. Die Verzeichnung fehlt
    darin, die inneren Kreuze liegen also daneben; fuer ein Suchfenster
    reicht es, und nach dem ersten Anpassen stimmt es.
    """
    H = homographie_viele(np.asarray(ecken_mm, dtype=float),
                          np.asarray(ecken_px, dtype=float), runden=1)
    return {"version": EICHUNG_VERSION,
            "bild": [int(bildgroesse[0]), int(bildgroesse[1])],
            "k1": 0.0, "k2": 0.0,
            "mitte": [bildgroesse[0] / 2.0, bildgroesse[1] / 2.0],
            "mass": MASS, "homographie": H.tolist(),
            "massstab": 1.0, "drehung": 0.0, "versatz": [0.0, 0.0],
            "hoehe": float(hoehe), "dicke": float(dicke)}


def _armlaenge_px(eichung, punkte_mm, dicke, arm=ARM):
    """Wie lang ein Kreuzarm an dieser Stelle im Bild ist.

    Nicht raten: die Eichung weiss es. Ein fester Wert in Bildpunkten
    stimmt nur fuer die eine Kamera, fuer die er einmal ausprobiert wurde.
    """
    mm = np.atleast_2d(np.asarray(punkte_mm, dtype=float))
    a = KAM.maschine_nach_bild(mm, eichung, dicke)
    b = KAM.maschine_nach_bild(mm + np.array([arm, 0.0]), eichung, dicke)
    return float(np.median(np.hypot(*(b - a).T)))


def suchen(bild, punkte_mm, start=None, ecken_px=None, dicke=0.0,
           hoehe=None, mindestguete=0.25):
    """Die beiden Suchdurchgaenge - ohne die abschliessende Anpassung.

    'start' ist die bisherige Eichung, 'ecken_px' sind vier angeklickte
    Eckkreuze - eins von beidem muss da sein, sonst weiss niemand, wo zu
    suchen ist.

    Zwei Durchgaenge, weil der erste Wegweiser grob ist: die alte Eichung
    liegt ein paar Millimeter daneben, vier Ecken ohne Linse mehr. Nach
    der ersten Anpassung sitzt die Vorhersage auf einem halben Millimeter,
    und dann findet die enge Suche auch die Kreuze, die im ersten
    Durchgang knapp am Fenster vorbeilagen.

    Getrennt von eichen(), damit zwischen Suchen und Anpassen noch ein
    Mensch dazwischentreten kann: die Lupe im Kamerareiter zeigt jeden
    Fund gross und laesst die Mitte von Hand setzen.

    Zurueck kommen Fundstellen, Gueten, welche brauchbar sind, die Hoehe,
    mit der gerechnet wurde, und die Spur als Bild - die wird beim Suchen
    ohnehin gerechnet, und die Lupe braucht genau sie.
    """
    mm = np.atleast_2d(np.asarray(punkte_mm, dtype=float))
    wegweiser = start
    if wegweiser is None:
        if ecken_px is None:
            raise ValueError("ohne alte Eichung braucht es vier Eckkreuze")
        wegweiser = eichung_aus_ecken(
            ecken_px, [mm[0], mm[_zeile(mm) - 1], mm[-_zeile(mm)], mm[-1]],
            bild.size, hoehe or 0.0, dicke)
    if hoehe is None:
        hoehe = float(wegweiser.get("hoehe", 0.0) or 0.0)

    funde = guete = gut = None
    vorarbeit = spur(bild)
    for durchgang in range(2):
        vorher = KAM.maschine_nach_bild(mm, wegweiser, dicke)
        arm_px = _armlaenge_px(wegweiser, mm, dicke)
        # Im zweiten Durchgang eng: die Vorhersage sitzt dann auf einem
        # halben Millimeter, und jede fremde Kante, die draussen bleibt,
        # kann auch nicht mehr gewinnen.
        fenster = max(12, int(1.5 * arm_px)) if durchgang else None
        funde, guete = kreuze_suchen(bild, vorher, arm_px=arm_px,
                                     fenster=fenster, vorarbeit=vorarbeit)
        gut = _brauchbar(guete, mindestguete)
        if gut.sum() < MINDESTKREUZE:
            raise ValueError(
                "nur %d von %d Kreuzen gefunden - zu wenig fuer eine Eichung"
                % (int(gut.sum()), len(mm)))
        if not durchgang:
            wegweiser = getrimmt(funde, mm, bild.size, gut, hoehe=hoehe,
                                 dicke=dicke, vorlage=wegweiser)[0]
    return funde, guete, gut, float(hoehe), spurbild(vorarbeit[0])


def eichen(bild, punkte_mm, start=None, ecken_px=None, dicke=0.0,
           hoehe=None, mindestguete=0.25, vorlage=None):
    """Suchen und anpassen in einem - der Weg ohne Zwischenfrage.

    Zurueck kommen Eichung, Fundstellen und Gueten. Wo die Guete null ist,
    wurde kein Kreuz gefunden oder es ist als Ausreisser geflogen - die
    Stelle ist dann nicht eingerechnet.
    """
    mm = np.atleast_2d(np.asarray(punkte_mm, dtype=float))
    funde, guete, gut, hoehe, _ = suchen(bild, mm, start, ecken_px, dicke,
                                         hoehe, mindestguete)
    eichung, behalten = getrimmt(funde, mm, bild.size, gut, hoehe=hoehe,
                                 dicke=dicke, vorlage=vorlage)
    return eichung, funde, np.where(behalten, guete, 0.0)


AUSREISSER = 3.0           # so viel mal dem mittleren Rest ist zu weit
TRIMMGRENZE = 0.5          # mm - darunter wird nie aussortiert


def getrimmt(funde, punkte_mm, bildgroesse, gut, hoehe=0.0, dicke=0.0,
             vorlage=None, runden=5):
    """Anpassen, Ausreisser verwerfen, neu anpassen - bis es steht.

    Ein einziger Fehlgriff reicht, um die ganze Eichung zu verziehen: die
    Ausgleichsrechnung kann ihn nicht als falsch erkennen, sie verteilt
    seinen Fehler auf alle anderen. Am 10.11.2026 hat ein Stapel
    ueberlappender Blaetter genau das geliefert - wo sich zwei Blattkanten
    kreuzen, steht ein Kreuz, das viel dunkler ist als die gebrannte Spur.

    Wer erst anpasst und dann wegwirft, was weit abliegt, laesst den
    Fehlgriff den Rest nicht mitreissen. Gemessen wird gegen den
    *mittleren* Rest, nicht gegen eine feste Zahl: wie genau eine Eichung
    werden kann, haengt am Bild.

    Unter einem halben Millimeter wird nie aussortiert. Sonst frisst sich
    die Trimmung durch eine schon gute Anpassung, bis nur noch die vier
    Punkte uebrig sind, die jede Homographie exakt trifft.
    """
    funde = np.atleast_2d(np.asarray(funde, dtype=float))
    punkte_mm = np.atleast_2d(np.asarray(punkte_mm, dtype=float))
    behalten = np.array(gut, dtype=bool)
    eichung = None
    for _ in range(max(1, runden)):
        eichung = anpassen(funde[behalten], punkte_mm[behalten], bildgroesse,
                           hoehe, dicke, vorlage=vorlage)
        rest = fehler(eichung, funde, punkte_mm)[2]
        grenze = max(AUSREISSER * float(np.median(rest[behalten])),
                     TRIMMGRENZE)
        neu = behalten & (rest <= grenze)
        if neu.sum() < MINDESTKREUZE or bool((neu == behalten).all()):
            break
        behalten = neu
    return eichung, behalten


def _zeile(mm):
    """Wie viele Kreuze in einer Zeile stehen - aus den Soll-Punkten selbst.

    Die Reihenfolge ist zeilenweise, also beginnt eine neue Zeile dort, wo
    Y springt.
    """
    for i in range(1, len(mm)):
        if abs(mm[i][1] - mm[0][1]) > 1e-6:
            return i
    return len(mm)


def _brauchbar(guete, mindestguete):
    """Welche Funde zaehlen.

    Nicht gegen eine feste Zahl - wie dunkel die Spur wird, haengt an
    Material, Licht und Leistung. Gemessen wird gegen den *mittleren*
    Fund, nicht gegen den besten: ein einziger Fehlgriff auf einer
    Blattkante ist zehnmal dunkler als jede gebrannte Spur, und gegen den
    gemessen faellt dann das ganze echte Raster durch.
    """
    g = np.asarray(guete, dtype=float)
    da = g > 0
    if not da.any():
        return da
    return da & (g >= mindestguete * float(np.median(g[da])))


def pruefen(bild, eichung, punkte_mm, dicke=0.0, mindestguete=0.25):
    """Was die gespeicherte Eichung heute noch taugt, an einem frischen Bild.

    Derselbe Weg wie beim Eichen, nur ohne Anpassen. Das ist der Knopf,
    der den Fehler Wochen frueher gezeigt haette: eine Eichung verrutscht
    nicht laut, sie verrutscht still.
    """
    mm = np.atleast_2d(np.asarray(punkte_mm, dtype=float))
    vorher = KAM.maschine_nach_bild(mm, eichung, dicke)
    funde, guete = kreuze_suchen(bild, vorher,
                                 arm_px=_armlaenge_px(eichung, mm, dicke))
    gut = _brauchbar(guete, mindestguete)
    if not gut.any():
        raise ValueError("kein einziges Kreuz gefunden")
    mittel, groesster, _ = fehler(eichung, funde[gut], mm[gut])
    return mittel, groesster, funde, np.where(gut, guete, 0.0)
