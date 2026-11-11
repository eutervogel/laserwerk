"""Werkstuecke im Kamerabild finden.

Was hier gesucht wird, ist nicht schwer: eine Flaeche, die sich vom
Untergrund abhebt. Schwer war die Linse, und die ist erledigt - das Bild,
das hereinkommt, ist schon entzerrt und steht in Maschinenkoordinaten.
Ein Bildpunkt ist ein fester Bruchteil eines Millimeters, die linke untere
Ecke liegt auf einer bekannten Stelle. Deshalb braucht diese Datei keine
zweite Koordinatenrechnung: sie rechnet den Umriss einmal in Millimeter um
und misst danach nur noch dort. Ein Vorzeichenfehler in der Y-Achse kann
sich so nicht in die Masse schleichen, weil es nach dem Umrechnen keine
Bildkoordinaten mehr gibt.

Den Untergrund sagt der Rand des Bildes - dort liegt das Bett oder die
Wabenplatte, nicht das Brettchen. Das ist die einzige Annahme, und sie ist
die Stelle, an der es schiefgehen kann: liegt das Material bis in die Ecken,
ist der Rand kein Untergrund mehr. Dann hebt sich nichts ab, und es kommt
nichts zurueck - lieber das, als eine Zahl, die nur so aussieht wie eine
Antwort.

Dunkles Material auf dunkler Wabenplatte bleibt der schwere Fall. Beim
Gravieren hilft ein Blatt weisses Papier darunter: der Strahl verlaesst das
Werkstueck nicht, das Papier sieht ihn also nie, und der Untergrund ist mit
einem Griff eindeutig.

Ohne OpenCV und ohne scipy. Laserwerk laeuft auf PIL und numpy, und was
hier fehlt - zusammenhaengende Flaechen, Randverfolgung, konvexe Huelle,
kleinstes gedrehtes Rechteck, Kreisausgleich - sind zusammen ein paar
hundert Zeilen, die sich pruefen lassen. Eine Abhaengigkeit von sechzig
Megabyte dafuer hereinzuholen waere ein schlechter Tausch.
"""

import math

import numpy as np
from PIL import Image, ImageFilter

STUECKE_VERSION = 1

SCHWELLE = 0.18        # so weit muss sich etwas vom Untergrund abheben
RANDRING = 4           # so viele Bildpunkte am Rand sagen den Untergrund
GLAETTEN = 3           # Fenster fuers Oeffnen und Schliessen
MINDEST_MM = 15.0      # kleinere Seite als das ist kein Werkstueck
MAX_ANTEIL = 0.75      # bedeckt die Maske mehr, war der Untergrund falsch
MAX_LAEUFE = 80000     # mehr Zeilenlaeufe heisst: zu unruhig, kein Ergebnis
GENUG = 0.75           # darunter gilt ein Fund als unsicher

# Im Uhrzeigersinn, so wie die Randverfolgung herumlaeuft.
NACHBARN = ((1, 0), (1, 1), (0, 1), (-1, 1),
            (-1, 0), (-1, -1), (0, -1), (1, -1))


# ---------------------------------------------------------------- Maske

def maske(bett, schwelle=SCHWELLE, rand=RANDRING, glaetten=GLAETTEN,
          abdeckung=None):
    """Was sich vom Untergrund abhebt, als Wahrheitsfeld.

    Erst oeffnen (schrumpfen, dann aufblasen): das nimmt Kruemel und
    Rauschen heraus. Dann schliessen (aufblasen, dann schrumpfen): das
    legt kleine Loecher zu, etwa die Maserung in einem Brettchen.

    abdeckung sagt, welche Punkte die Kamera ueberhaupt aufgenommen hat.
    Was sie nicht gesehen hat, ist schwarz - und Schwarz hebt sich
    praechtig ab, ohne etwas zu sein. Es faellt deshalb vorher heraus,
    und der Untergrund wird nur dort gemessen, wo wirklich Bild ist.
    """
    g = bett.convert("L")
    a = np.asarray(g).astype(float) / 255.0
    if a.size == 0:
        return np.zeros((0, 0), dtype=bool)
    r = max(1, min(int(rand), min(a.shape) // 4))
    ring = np.zeros(a.shape, dtype=bool)
    ring[:r] = ring[-r:] = True
    ring[:, :r] = ring[:, -r:] = True
    if abdeckung is not None:
        ring &= abdeckung
    werte = a[ring]
    if werte.size < 500 and abdeckung is not None and abdeckung.any():
        werte = a[abdeckung]        # vorne fehlt zu viel: dann das Ganze
    if werte.size == 0:
        werte = a.ravel()
    untergrund = float(np.median(werte))
    m = (np.abs(a - untergrund) > schwelle)
    if abdeckung is not None:
        m &= abdeckung
    if glaetten >= 3:
        bild = Image.fromarray(m.astype(np.uint8) * 255)
        for f in (ImageFilter.MinFilter(glaetten), ImageFilter.MaxFilter(glaetten),
                  ImageFilter.MaxFilter(glaetten), ImageFilter.MinFilter(glaetten)):
            bild = bild.filter(f)
        m = np.asarray(bild) > 127
        if abdeckung is not None:
            m = m & abdeckung       # das Aufblasen nicht ins Schwarze hinein
    return m


def _randfeld(form, abdeckung):
    """Wo ein Stueck angeschnitten waere.

    Am Bildrand - und am Rand dessen, was die Kamera aufgenommen hat.
    Ein Untersetzer, der halb im unaufgenommenen Streifen liegt, sieht
    aus wie ein kleinerer Untersetzer. Genau das darf nicht als Mass
    durchgehen.
    """
    r = np.zeros(form, dtype=bool)
    r[0] = r[-1] = True
    r[:, 0] = r[:, -1] = True
    if abdeckung is not None:
        aus = ~abdeckung
        r[:-1] |= aus[1:]
        r[1:] |= aus[:-1]
        r[:, :-1] |= aus[:, 1:]
        r[:, 1:] |= aus[:, :-1]
    return r


def sperren_setzen(m, kaesten, mm_je_px, x0, y0):
    """Flaechen aus der Maske nehmen, die kein Werkstueck sein koennen.

    Der Laserkopf liegt im Bild und hebt sich praechtig vom Bett ab - er
    waere sonst der erste Fund. Die Kaesten kommen in Millimetern
    (x0, y0, x1, y1), so wie der Rest des Programms rechnet.
    """
    h = m.shape[0]
    y1 = y0 + h * mm_je_px
    for kx0, ky0, kx1, ky1 in kaesten:
        a0 = int(math.floor((min(kx0, kx1) - x0) / mm_je_px))
        a1 = int(math.ceil((max(kx0, kx1) - x0) / mm_je_px))
        b0 = int(math.floor((y1 - max(ky0, ky1)) / mm_je_px))
        b1 = int(math.ceil((y1 - min(ky0, ky1)) / mm_je_px))
        a0, b0 = max(0, a0), max(0, b0)
        if a1 > a0 and b1 > b0:
            m[b0:b1, a0:a1] = False
    return m


# ------------------------------------------------- zusammenhaengende Flaechen

def _marken(m, grenze=MAX_LAEUFE):
    """Zusammenhaengende Flaechen durchnummerieren (8er-Nachbarschaft).

    Zeilenweise: in jeder Zeile die Laeufe aus Wahr, und wer einen Lauf
    der Zeile darueber beruehrt, bekommt dieselbe Nummer. Beruehrt ein
    Lauf zwei verschiedene, werden die beiden zusammengebunden - ein U
    laeuft oben als zwei Arme los und ist erst unten eines.

    Zurueck kommt (None, 0), wenn es mehr Laeufe sind als die Grenze
    erlaubt: dann ist das Bild zu unruhig, und jede Antwort waere geraten.
    """
    h, w = m.shape
    eltern = [0]
    gesamt = 0

    def wurzel(a):
        while eltern[a] != a:
            eltern[a] = eltern[eltern[a]]
            a = eltern[a]
        return a

    zeilen = []
    vorher = []
    for y in range(h):
        z = m[y]
        if not z.any():
            vorher = []
            zeilen.append([])
            continue
        kanten = np.flatnonzero(np.diff(
            np.concatenate(([False], z, [False])).astype(np.int8)))
        laeufe = []
        for a0, e in zip(kanten[0::2].tolist(), kanten[1::2].tolist()):
            a1 = e - 1
            marke = 0
            for b0, b1, bm in vorher:
                # Ein Bildpunkt Luft: schraeg zaehlt als benachbart.
                if b0 <= a1 + 1 and a0 <= b1 + 1:
                    w2 = wurzel(bm)
                    if marke and marke != w2:
                        eltern[max(marke, w2)] = min(marke, w2)
                        marke = min(marke, w2)
                    elif not marke:
                        marke = w2
            if not marke:
                eltern.append(len(eltern))
                marke = len(eltern) - 1
            laeufe.append((a0, a1, marke))
        gesamt += len(laeufe)
        if gesamt > grenze:
            return None, 0
        zeilen.append(laeufe)
        vorher = laeufe

    neu = {}
    for i in range(1, len(eltern)):
        r = wurzel(i)
        if r not in neu:
            neu[r] = len(neu) + 1
    aus = np.zeros(m.shape, dtype=np.int32)
    for y, laeufe in enumerate(zeilen):
        for a0, a1, mk in laeufe:
            aus[y, a0:a1 + 1] = neu[wurzel(mk)]
    return aus, len(neu)


def _loecher(teil, mindest_px=0):
    """Die Innenloecher einer Flaeche: zuschlagen und die grossen melden.

    Zwei Dinge auf einmal, weil es zwei Fragen sind. Die erste: wie gross
    ist dieses Stueck? Dafuer zaehlt die Flaeche innerhalb des Umrisses,
    nicht die seiner Oberseite ohne Astloch - alle Loecher werden
    zugeschlagen.

    Die zweite Frage ist die wichtigere, und an ihr ist der erste Versuch
    an der echten Maschine gescheitert: ein dunkler Untersetzer auf einem
    weissen Blatt ist genau das - ein Loch im Blatt. Wer es nur
    zuschlaegt, fuellt das Werkstueck weg und meldet das Blatt. Was gross
    genug fuer ein Werkstueck ist, kommt deshalb als eigener Fund heraus.
    Die Maserung eines Brettchens bleibt ein Loch und wird zugeschlagen.

    Der Untergrund wird mit derselben 8er-Nachbarschaft verfolgt wie die
    Flaeche selbst - ein Loch, dessen Ring schraeg einen Bildpunkt offen
    hat, bleibt deshalb offen. Das ist die harmlose Richtung: lieber ein
    Loch nicht zugeschlagen als zwei Stuecke zu einem verschmolzen.
    """
    frei = ~teil
    marken, n = _marken(frei)
    if not n:
        return teil, []
    rand = set(marken[0].tolist()) | set(marken[-1].tolist())
    rand |= set(marken[:, 0].tolist()) | set(marken[:, -1].tolist())
    innen = [k for k in range(1, n + 1) if k not in rand]
    if not innen:
        return teil, []
    gross = []
    if mindest_px:
        for k in innen:
            wo = marken == k
            ys, xs = np.nonzero(wo)
            if min(int(xs.max() - xs.min()) + 1,
                   int(ys.max() - ys.min()) + 1) >= mindest_px:
                gross.append(wo)
    return teil | np.isin(marken, innen), gross


def _umriss_px(teil, grenze=200000):
    """Der Rand einer Flaeche als geschlossener Weg von (x, y).

    Moore-Nachbarschaft: am obersten linken Punkt losgehen und immer
    linksherum am Rand entlangtasten, bis man wieder am Anfang steht.
    """
    p = np.zeros((teil.shape[0] + 2, teil.shape[1] + 2), dtype=bool)
    p[1:-1, 1:-1] = teil
    ys, xs = np.nonzero(p)
    if not len(xs):
        return []
    anfang = (int(xs[0]), int(ys[0]))
    jetzt = anfang
    # Links vom obersten linken Punkt ist Untergrund - sonst waere er es.
    vorher = (anfang[0] - 1, anfang[1])
    weg = []
    while True:
        weg.append(jetzt)
        k = NACHBARN.index((vorher[0] - jetzt[0], vorher[1] - jetzt[1]))
        for i in range(1, 9):
            dx, dy = NACHBARN[(k + i) % 8]
            kand = (jetzt[0] + dx, jetzt[1] + dy)
            if p[kand[1], kand[0]]:
                lx, ly = NACHBARN[(k + i - 1) % 8]
                vorher = (jetzt[0] + lx, jetzt[1] + ly)
                jetzt = kand
                break
        else:
            break                      # ein einzelner Punkt hat keinen Rand
        if jetzt == anfang or len(weg) > grenze:
            break
    return [(x - 1, y - 1) for x, y in weg]


def _duennen(punkte, abstand):
    """Punkte wegwerfen, die naeher liegen als abstand.

    Ein Kreis mit 50 mm Halbmesser hat bei zwei Bildpunkten je Millimeter
    ueber sechshundert Randpunkte. Zum Zeichnen und Messen reicht ein
    Bruchteil, und die Zeichenflaeche wird nicht traege.
    """
    if not punkte:
        return []
    aus = [punkte[0]]
    for p in punkte[1:]:
        if (p[0] - aus[-1][0]) ** 2 + (p[1] - aus[-1][1]) ** 2 >= abstand ** 2:
            aus.append(p)
    if len(aus) > 2 and (aus[-1][0] - aus[0][0]) ** 2 + \
            (aus[-1][1] - aus[0][1]) ** 2 < abstand ** 2:
        aus.pop()
    return aus


def _ebnen(punkte, toleranz):
    """Gerade Stuecke zu geraden Stuecken zusammenfassen (Douglas-Peucker).

    Ein Rechteck braucht vier Punkte, kein Tausend. Der Umriss wird
    danach nicht nur schneller gezeichnet und getroffen - er zeigt auch,
    was er ist. Mit einem Zehntelmillimeter Toleranz bleibt ein Kreis ein
    Kreis: die Sehne wird nur so lang, wie die Wolbung es erlaubt.
    """
    n = len(punkte)
    if n < 3 or toleranz <= 0:
        return punkte
    behalten = [False] * n
    behalten[0] = behalten[-1] = True
    stapel = [(0, n - 1)]
    while stapel:
        a, b = stapel.pop()
        if b <= a + 1:
            continue
        ax, ay = punkte[a]
        bx, by = punkte[b]
        dx, dy = bx - ax, by - ay
        laenge = math.hypot(dx, dy)
        weit, wo = -1.0, a
        for i in range(a + 1, b):
            px, py = punkte[i]
            if laenge < 1e-12:
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs(dx * (py - ay) - dy * (px - ax)) / laenge
            if d > weit:
                weit, wo = d, i
        if weit > toleranz:
            behalten[wo] = True
            stapel.append((a, wo))
            stapel.append((wo, b))
    return [p for p, j in zip(punkte, behalten) if j]


def _abtaster(bett, mm_je_px, x0, y_oben):
    """Eine Funktion, die die Helligkeit an einer Stelle in Millimetern
    liefert - zwischen den Bildpunkten linear."""
    g = np.asarray(bett.convert("L")).astype(np.float32)
    h, w = g.shape

    def lesen(x, y):
        c = np.clip((np.asarray(x, dtype=float) - x0) / mm_je_px - 0.5,
                    0, w - 1.001)
        r = np.clip((y_oben - np.asarray(y, dtype=float)) / mm_je_px - 0.5,
                    0, h - 1.001)
        c0 = np.floor(c).astype(int)
        r0 = np.floor(r).astype(int)
        fc, fr = c - c0, r - r0
        return (g[r0, c0] * (1 - fc) * (1 - fr)
                + g[r0, c0 + 1] * fc * (1 - fr)
                + g[r0 + 1, c0] * (1 - fc) * fr
                + g[r0 + 1, c0 + 1] * fc * fr)
    return lesen


def feinkante(punkte, lesen, spanne=2.0, schritt=0.05, hub=12.0, glatt=None):
    """Die Kante dort suchen, wo das Bild sie wirklich hat.

    Der verfolgte Rand liegt auf dem Bildpunktraster - in halben
    Millimetern, und wo genau er liegt, haengt an der Schwelle, die
    jemand eingestellt hat. Fuer eine Anzeige reicht das. Fuer ein Mass
    nicht, und fuer eine Mitte schon gar nicht.

    Deshalb wird quer zur Kontur durch das graue Bild geschnitten: innen
    eine Helligkeit, aussen eine andere, und die Kante liegt dort, wo die
    Haelfte erreicht ist. Zwischen zwei Abtastpunkten linear - damit
    endet die Kante nicht mehr auf dem Raster.

    Quer heisst: entlang der Normalen der Kontur, nicht in Richtung
    Mitte. Ein Kreis haette beides gleich, ein Brettchen nicht, und eine
    unregelmaessige Form schon gar nicht.

    Wo der Unterschied zwischen innen und aussen kleiner ist als hub,
    gibt es nichts zu finden - dort bleibt der Punkt, wie er war. Lieber
    der alte Punkt als ein neuer, der aus Rauschen gerechnet ist.
    """
    p = np.asarray(punkte, dtype=float)
    if len(p) < 8:
        return [tuple(q) for q in p]
    # Normale aus weiter entfernten Nachbarn. Der verfolgte Rand ist
    # eine Treppe auf dem Bildpunktraster: aus den direkten Nachbarn
    # springt die Richtung um fuenfundvierzig Grad hin und her, und quer
    # dazu zu schneiden heisst, schraeg durch die Kante zu schneiden.
    # Ueber ein Stueck Kontur gemittelt steht sie ruhig.
    k = glatt if glatt else max(2, len(p) // 60)
    tang = np.roll(p, -k, axis=0) - np.roll(p, k, axis=0)
    laenge = np.hypot(tang[:, 0], tang[:, 1])
    laenge[laenge == 0] = 1.0
    u = np.column_stack([tang[:, 1] / laenge, -tang[:, 0] / laenge])
    # Vorzeichen so drehen, dass die Normale nach aussen zeigt. Welche
    # Richtung das ist, haengt am Umlaufsinn - und den auszurechnen ist
    # umstaendlicher, als ihn einmal zu messen.
    mitte = p.mean(axis=0)
    if float(np.sum(u * (p - mitte))) < 0:
        u = -u
    ts = np.arange(-spanne, spanne + 1e-9, schritt)
    prof = np.array([lesen(p[:, 0] + s * u[:, 0], p[:, 1] + s * u[:, 1])
                     for s in ts])
    q = max(2, int(len(ts) * 0.15))
    innen = prof[:q].mean(axis=0)
    aussen = prof[-q:].mean(axis=0)
    halb = (innen + aussen) / 2.0
    aus = []
    for i in range(prof.shape[1]):
        if abs(float(aussen[i] - innen[i])) < hub:
            aus.append((float(p[i, 0]), float(p[i, 1])))
            continue
        s = prof[:, i] - halb[i]
        wechsel = np.nonzero(np.sign(s[:-1]) != np.sign(s[1:]))[0]
        if not len(wechsel):
            aus.append((float(p[i, 0]), float(p[i, 1])))
            continue
        # Die Kreuzung, die der bisherigen Kante am naechsten liegt: bei
        # zwei echten Kanten - Werkstueck und Lichtsaum - ist das die,
        # die gemeint war.
        j = wechsel[np.argmin(np.abs(ts[wechsel]))]
        a, b = abs(float(s[j])), abs(float(s[j + 1]))
        tt = ts[j] + schritt * a / (a + b + 1e-9)
        aus.append((float(p[i, 0] + tt * u[i, 0]),
                    float(p[i, 1] + tt * u[i, 1])))
    return aus


def polygonflaeche(punkte):
    """Flaeche eines geschlossenen Umrisses (Schnuersenkelformel)."""
    p = np.asarray(punkte, dtype=float)
    if len(p) < 3:
        return 0.0
    x, y = p[:, 0], p[:, 1]
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2.0


# ------------------------------------------------------------- Geometrie

def huelle(punkte):
    """Konvexe Huelle, gegen den Uhrzeigersinn (Andrew)."""
    p = sorted(set((float(x), float(y)) for x, y in punkte))
    if len(p) < 3:
        return p

    def halb(folge):
        aus = []
        for q in folge:
            while len(aus) >= 2:
                (ax, ay), (bx, by) = aus[-2], aus[-1]
                if (bx - ax) * (q[1] - ay) - (by - ay) * (q[0] - ax) <= 0:
                    aus.pop()
                else:
                    break
            aus.append(q)
        return aus

    unten = halb(p)
    oben = halb(reversed(p))
    return unten[:-1] + oben[:-1]


def minrechteck(punkte):
    """Das kleinste gedrehte Rechteck um die Punkte.

    Es liegt immer mit einer Seite an einer Seite der konvexen Huelle -
    deshalb genuegt es, die Huelle einmal Kante fuer Kante geradezudrehen
    und den kleinsten Kasten zu behalten.

    Zurueck kommt (mitte, breite, hoehe, winkel) mit breite >= hoehe und
    dem Winkel der langen Seite in Grad.
    """
    h = huelle(punkte)
    if len(h) < 3:
        if not h:
            return (0.0, 0.0), 0.0, 0.0, 0.0
        xs = [q[0] for q in h]
        ys = [q[1] for q in h]
        return (((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0),
                max(xs) - min(xs), max(ys) - min(ys), 0.0)
    a = np.asarray(h, dtype=float)
    beste = None
    for i in range(len(h)):
        kx, ky = a[(i + 1) % len(h)] - a[i]
        laenge = math.hypot(kx, ky)
        if laenge < 1e-9:
            continue
        cos, sin = kx / laenge, ky / laenge
        u = a[:, 0] * cos + a[:, 1] * sin
        v = -a[:, 0] * sin + a[:, 1] * cos
        bu, bv = float(np.ptp(u)), float(np.ptp(v))
        if beste is None or bu * bv < beste[0]:
            mu = (float(u.min()) + float(u.max())) / 2.0
            mv = (float(v.min()) + float(v.max())) / 2.0
            mitte = (mu * cos - mv * sin, mu * sin + mv * cos)
            beste = (bu * bv, mitte, bu, bv, math.degrees(math.atan2(sin, cos)))
    if beste is None:
        return (0.0, 0.0), 0.0, 0.0, 0.0
    _, mitte, bu, bv, grad = beste
    if bv > bu:
        bu, bv, grad = bv, bu, grad + 90.0
    return mitte, bu, bv, (grad + 90.0) % 180.0 - 90.0


def kreis(punkte):
    """Kreisausgleich nach Kasa: (mitte_x, mitte_y, halbmesser, rest).

    rest ist die Streuung der Randpunkte um den gefundenen Kreis in
    derselben Einheit wie die Punkte - das Mass dafuer, ob rund hier
    ueberhaupt die richtige Antwort ist.
    """
    a = np.asarray(punkte, dtype=float)
    if len(a) < 3:
        return 0.0, 0.0, 0.0, float("inf")
    x, y = a[:, 0], a[:, 1]
    A = np.column_stack([2.0 * x, 2.0 * y, np.ones(len(a))])
    b = x * x + y * y
    try:
        loes, _, rang, _ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0, 0.0, 0.0, float("inf")
    cx, cy, c = [float(v) for v in loes]
    unter = c + cx * cx + cy * cy
    if unter <= 0:
        return cx, cy, 0.0, float("inf")
    r = math.sqrt(unter)
    # Punkte auf einer Geraden haben keinen Kreis. Der Ausgleich findet
    # trotzdem einen: einen riesigen, dessen Mitte weit im Nichts liegt -
    # und weil die Gerade gut an ihm anliegt, mit kleinem Rest. Das ist
    # die gefaehrlichste Art von Antwort, und sie faellt hier heraus.
    weite = max(float(np.ptp(x)), float(np.ptp(y)), 1e-9)
    if rang < 3 or r > 1000.0 * weite:
        return cx, cy, r, float("inf")
    d = np.hypot(x - cx, y - cy) - r
    return cx, cy, r, float(np.sqrt(np.mean(d * d)))


def _in_umriss(punkt, umriss):
    """Liegt der Punkt im Umriss? Strahlenzaehlung."""
    x, y = punkt
    drin = False
    n = len(umriss)
    for i in range(n):
        x0, y0 = umriss[i]
        x1, y1 = umriss[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            s = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < s:
                drin = not drin
    return drin


# ----------------------------------------------------------------- Finden

# Suchfenster der Kantenverfeinerung, in Millimetern. Erst weit, damit
# die Kante auch dann gefunden wird, wenn die Maske zwei, drei Millimeter
# daneben anfaengt, dann enger. An einem echten Kamerabild gemessen: mit
# nur zwei Runden streut der Durchmesser ueber verschiedene Schwellen um
# 1,5 mm, mit dreien um 0,7. Eine vierte bringt nichts mehr.
FEINRUNDEN = (4.0, 2.0, 1.0)


def _eines(teil, versatz, nach_mm, mm_je_px, nr, am_rand, mindest_px=0,
           loecher=None, lesen=None):
    """Aus einer zusammenhaengenden Flaeche ein Werkstueck machen.

    Was an grossen Loechern darin steckt, wird in loecher abgelegt - der
    Aufrufer macht daraus eigene Funde.

    Gemessen wird auf dem vollen Rand, gezeichnet auf einem vereinfachten.
    Das ist kein Geiz, sondern notwendig: Douglas-Peucker behaelt
    ausgerechnet die Punkte, die am weitesten abweichen. Fuer eine
    Zeichnung ist das richtig und fuer einen Ausgleich das Schlechteste,
    was man tun kann - er liefe auf einer Auswahl, die zu den Ausreissern
    hin verzerrt ist.
    """
    voll, gross = _loecher(teil, mindest_px)
    if loecher is not None:
        loecher.extend(gross)
    px = _umriss_px(voll)
    if len(px) < 8:
        return None
    ax, ay = versatz
    roh = [nach_mm(x + ax, y + ay) for x, y in px]
    umriss = _ebnen(_duennen(roh, max(0.5, mm_je_px)), max(0.3, mm_je_px * 0.6))
    if len(umriss) < 4:
        return None
    flaeche = float(voll.sum()) * mm_je_px * mm_je_px
    ys, xs = np.nonzero(voll)
    sx, sy = nach_mm(float(xs.mean()) + ax, float(ys.mean()) + ay)

    # Das Mass kommt von der Kante im grauen Bild, nicht vom Raster der
    # Maske: zweimal nachgefasst, erst grob, dann fein.
    messrand = roh
    if lesen is not None and len(roh) >= 32:
        for spanne in FEINRUNDEN:
            messrand = feinkante(messrand, lesen, spanne=spanne)
        f = polygonflaeche(messrand)
        if f > 0:
            flaeche = f
            sx, sy = (float(np.mean([q[0] for q in messrand])),
                      float(np.mean([q[1] for q in messrand])))

    kx = [p[0] for p in messrand]
    ky = [p[1] for p in messrand]
    kasten = (min(kx), min(ky), max(kx), max(ky))

    mitte, rb, rh, grad = minrechteck(messrand)
    cx, cy, r, rest = kreis(messrand)

    rund = (r > 0 and rest <= max(0.4, 0.04 * r)
            and 0.88 <= flaeche / (math.pi * r * r) <= 1.12)
    fuellung = flaeche / (rb * rh) if rb > 0 and rh > 0 else 0.0
    if rund:
        form, mitte, breite, hoehe = "rund", (cx, cy), 2.0 * r, 2.0 * r
        winkel = None
        guete = max(0.0, 1.0 - rest / max(0.4, 0.06 * r))
    elif fuellung >= 0.90:
        form, breite, hoehe = "rechteck", rb, rh
        winkel = (grad + 45.0) % 90.0 - 45.0
        guete = min(1.0, (fuellung - 0.7) / 0.28)
    else:
        form = "frei"
        mitte = ((kasten[0] + kasten[2]) / 2.0, (kasten[1] + kasten[3]) / 2.0)
        breite, hoehe = kasten[2] - kasten[0], kasten[3] - kasten[1]
        winkel = ((grad + 45.0) % 90.0 - 45.0) if rh > 0 and rb / rh >= 1.15 \
            else None
        guete = 0.6 * min(1.0, max(0.0, fuellung / 0.9))
    return dict(nr=nr, form=form, mitte=mitte, schwerpunkt=(sx, sy),
                rest=round(float(rest), 3) if rest != float("inf") else None,
                breite=breite, hoehe=hoehe, winkel=winkel,
                umriss=umriss, kasten=kasten, flaeche=flaeche,
                guete=round(float(guete), 3),
                sicher=bool(guete >= GENUG and not am_rand),
                randlage=bool(am_rand), herkunft="bild")


def finden(bett, mm_je_px, x0=0.0, y0=0.0, schwelle=SCHWELLE,
           mindest_mm=MINDEST_MM, sperren=(), glaetten=GLAETTEN,
           abdeckung=None):
    """Die Werkstuecke in der entzerrten Draufsicht, in Millimetern.

    bett ist das Bild aus KAM.bett_bild, mm_je_px sein Mass (dort
    1/px_je_mm), x0/y0 seine linke untere Ecke in Maschinenkoordinaten.
    Y zeigt im Bild nach unten und in der Maschine nach oben; das dreht
    diese Funktion mit, damit der Aufrufer nicht daran denken muss.

    Zurueck kommt eine Liste von hinten links nach vorne rechts - so,
    wie man die Stuecke auf dem Bett abliest. Jedes Stueck sagt mit
    sicher=False selbst, wenn ihm nicht zu trauen ist.
    """
    m = maske(bett, schwelle=schwelle, glaetten=glaetten,
              abdeckung=abdeckung)
    if m.size == 0:
        return []
    if sperren:
        m = sperren_setzen(m, sperren, mm_je_px, x0, y0)
    flaeche_gesamt = float(abdeckung.sum()) if abdeckung is not None \
        else float(m.size)
    if flaeche_gesamt < 1 or m.sum() / flaeche_gesamt > MAX_ANTEIL:
        return []                      # der Bildrand war kein Untergrund
    marken, n = _marken(m)
    if not n:
        return []
    randfeld = _randfeld(m.shape, abdeckung)

    h = m.shape[0]
    y_oben = y0 + h * mm_je_px

    def nach_mm(px, py):
        return (x0 + (px + 0.5) * mm_je_px, y_oben - (py + 0.5) * mm_je_px)

    lesen = _abtaster(bett, mm_je_px, x0, y_oben)
    mindest_px = max(2, int(round(mindest_mm / mm_je_px)))
    gefunden = []
    for k in range(1, n + 1):
        wo = marken == k
        ys, xs = np.nonzero(wo)
        a0, a1 = int(xs.min()), int(xs.max())
        b0, b1 = int(ys.min()), int(ys.max())
        if min(a1 - a0 + 1, b1 - b0 + 1) < mindest_px:
            continue
        am_rand = bool((wo & randfeld).any())
        loecher = []
        s = _eines(wo[b0:b1 + 1, a0:a1 + 1], (a0, b0), nach_mm, mm_je_px,
                   0, am_rand, mindest_px, loecher, lesen)
        if s:
            gefunden.append(s)
        # Ein grosses Loch liegt mitten im Bild - angeschnitten ist es nie.
        for loch in loecher:
            ly, lx = np.nonzero(loch)
            c0, d0 = int(lx.min()), int(ly.min())
            k = _eines(loch[d0:int(ly.max()) + 1, c0:int(lx.max()) + 1],
                       (a0 + c0, b0 + d0), nach_mm, mm_je_px, 0, False,
                       mindest_px, None, lesen)
            if k:
                gefunden.append(k)
    gefunden.sort(key=lambda s: (-round(s["mitte"][1] / 20.0), s["mitte"][0]))
    for i, s in enumerate(gefunden):
        s["nr"] = i + 1
    return gefunden


# ----------------------------------------------------------- von Hand

def rechteck_stueck(x0, y0, x1, y1, winkel=0.0, nr=0):
    """Ein Werkstueck, das jemand selbst aufgezogen hat."""
    ax, bx = min(x0, x1), max(x0, x1)
    ay, by = min(y0, y1), max(y0, y1)
    umriss = [(ax, ay), (bx, ay), (bx, by), (ax, by)]
    return dict(nr=nr, form="rechteck", mitte=((ax + bx) / 2.0, (ay + by) / 2.0),
                schwerpunkt=((ax + bx) / 2.0, (ay + by) / 2.0),
                breite=bx - ax, hoehe=by - ay, winkel=winkel or None,
                umriss=umriss, kasten=(ax, ay, bx, by),
                flaeche=(bx - ax) * (by - ay), guete=1.0, sicher=True,
                randlage=False, rest=0.0, herkunft="hand")


def kreis_stueck(mx, my, r, nr=0, ecken=48):
    """Ein runder Umriss von Hand - fuer Untersetzer, die der Blick
    besser trifft als die Schwelle."""
    r = abs(float(r))
    umriss = [(mx + r * math.cos(2 * math.pi * i / ecken),
               my + r * math.sin(2 * math.pi * i / ecken))
              for i in range(ecken)]
    return dict(nr=nr, form="rund", mitte=(mx, my), schwerpunkt=(mx, my),
                breite=2 * r, hoehe=2 * r, winkel=None, umriss=umriss,
                kasten=(mx - r, my - r, mx + r, my + r),
                flaeche=math.pi * r * r, guete=1.0, sicher=True,
                randlage=False, rest=0.0, herkunft="hand")


def unter(stuecke, x, y):
    """Welches Stueck liegt unter dieser Stelle? Das kleinste gewinnt,
    sonst waere ein Stueck in einem Ausschnitt nie zu treffen."""
    treffer = [s for s in stuecke if _in_umriss((x, y), s["umriss"])]
    if not treffer:
        return None
    return min(treffer, key=lambda s: s["flaeche"])


def verschieben(stueck, mx, my):
    """Die Mitte eines Stuecks auf eine neue Stelle legen, mit Umriss."""
    dx, dy = mx - stueck["mitte"][0], my - stueck["mitte"][1]
    k = stueck["kasten"]
    stueck = dict(stueck, mitte=(mx, my),
                  schwerpunkt=(stueck["schwerpunkt"][0] + dx,
                               stueck["schwerpunkt"][1] + dy),
                  umriss=[(x + dx, y + dy) for x, y in stueck["umriss"]],
                  kasten=(k[0] + dx, k[1] + dy, k[2] + dx, k[3] + dy))
    return stueck


FORMNAME = {"rund": "rund", "rechteck": "rechteckig", "frei": "unregelmäßig"}


def _ungezaehmt(wert, n=1):
    return ("%." + str(int(n)) + "f") % wert


def lesbar(s, t=None, zahl=_ungezaehmt):
    """Eine Zeile ueber ein Stueck - die, die in die Anzeige gehoert.

    t uebersetzt die festen Woerter und zahl schreibt die Zahlen so, wie
    das Programm sie sonst schreibt. Beides kommt von aussen herein:
    diese Datei rechnet und soll von der Sprache nichts wissen muessen.
    """
    t = t or (lambda x: x)
    if s["form"] == "rund":
        mass = "Ø %s mm" % zahl(s["breite"], 1)
    else:
        mass = "%s x %s mm" % (zahl(s["breite"], 1), zahl(s["hoehe"], 1))
        if s["winkel"]:
            mass += ", %s°" % zahl(s["winkel"], 1)
    zeile = t("{nr}. {form}, {mass}, Mitte X {x} / Y {y}").format(
        nr=s["nr"], form=t(FORMNAME.get(s["form"], s["form"])), mass=mass,
        x=zahl(s["mitte"][0], 1), y=zahl(s["mitte"][1], 1))
    if not s["sicher"]:
        zeile += " " + t("(unsicher)")
    return zeile


def marke(s, zahl=_ungezaehmt):
    """Die kurze Beschriftung am Umriss auf der Zeichenflaeche."""
    if s["form"] == "rund":
        return "%d  Ø %s" % (s["nr"], zahl(s["breite"], 1))
    return "%d  %s x %s" % (s["nr"], zahl(s["breite"], 1), zahl(s["hoehe"], 1))
