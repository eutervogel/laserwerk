"""
Bild/SVG -> Rastergravur-G-Code, Testmuster, Laufzeitschaetzung.

Grundregeln aus der Praxis:
  - M4 (dynamische Leistung): bei Stillstand/Pause ist der Laser aus.
  - Energie pro mm haengt am Verhaeltnis S/F, nicht an S allein.
  - Bidirektional mit Overscan, Leerstellen mit S0 statt G0 (kein Stottern).
  - Nullpunkt = linke untere Ecke des Motivs, alle Koordinaten positiv.
"""
import base64, binascii, io, os, re, subprocess, tempfile
import math
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image, ImageFilter

S_MAX = 1000          # $30
POINTER_FEED = 600    # Vorschub fuer Sichtkreuz und sichtbaren Rahmen

# Werte der Maschine. Die Vorgaben sind die des Geraets, auf dem Laserwerk
# entstanden ist (450 nm, 5,5 W, GRBL 1.1f) - setze_maschine() holt sie aus
# der Konfiguration, wo sie nach dem ersten '$$' der angeschlossenen
# Maschine stehen. Ein anderer Laser rechnet voellig anders: 500 statt
# 30 mm/s^2 und 8000 statt 3000 mm/min Eilgang sind keine Feinheiten.
ACCEL = 30.0          # $120/$121 mm/s^2
EILGANG = 3000.0      # $110/$111 mm/min
KREUZUNG = 0.01       # $11 junction deviation, mm
WATT = 5.5            # optische Leistung bei S_MAX, Watt


def setze_maschine(cfg):
    """Beschleunigung, Eilgang, Kreuzungstoleranz und Leistung uebernehmen.

    Als Vorgabe in der Signatur waeren sie beim Import festgenagelt - ein
    spaeter gelesenes $$ kaeme nicht mehr an. Deshalb stehen sie im Modul
    und werden hier gesetzt.
    """
    global ACCEL, EILGANG, KREUZUNG, WATT
    for name, schluessel, kleinste in (("ACCEL", "accel", 1.0),
                                       ("EILGANG", "eilgang", 60.0),
                                       ("KREUZUNG", "kreuzung", 1e-4),
                                       ("WATT", "watt", 0.1)):
        try:
            wert = float(cfg.get(schluessel))
        except (TypeError, ValueError):
            continue
        if wert >= kleinste:
            globals()[name] = wert
    return dict(accel=ACCEL, eilgang=EILGANG, kreuzung=KREUZUNG, watt=WATT)


# ---------------------------------------------------------------- Laden
SVG_DATEN = re.compile(r'^data:image/svg\+xml;base64,(.*)$', re.S)
TIEFE = 6                 # so viele Ebenen Bild-in-Bild, dann ist Schluss


def _eingebettete_svg(href):
    """Steckt in diesem href eine SVG? Dann ihr Text, sonst None."""
    m = SVG_DATEN.match((href or "").strip())
    if not m:
        return None
    try:
        return base64.b64decode(m.group(1)).decode("utf-8", "replace")
    except (ValueError, binascii.Error):
        return None


def _xlink_text(t, tiefe=TIEFE):
    """Den href jedes <image> auf xlink:href umschreiben, auch in SVGs, die
    als Bild in diesem Bild stecken. Rueckgabe (Text, wurde etwas geaendert).
    """
    aus, i, getan = [], 0, False
    while True:
        j = t.find("<image", i)
        if j < 0:
            aus.append(t[i:])
            break
        k = t.find(">", j)
        if k < 0:
            aus.append(t[i:])
            break
        tag = t[j:k]
        # Eine Ebene tiefer: steckt im href selbst eine SVG, hat die
        # dasselbe Problem - und Inkscape zeichnet sie, waehrend ihr
        # eigenes Bild darin fehlt.
        if tiefe > 0:
            m = re.search(r'(?:xlink:)?href\s*=\s*"([^"]*)"', tag)
            innen = _eingebettete_svg(m.group(1)) if m else None
            if innen:
                neu, drin = _xlink_text(innen, tiefe - 1)
                if drin:
                    tag = tag.replace(m.group(1), "data:image/svg+xml;base64,"
                                      + base64.b64encode(neu.encode()).decode())
                    getan = True
        tag, n = re.subn(r'(?<!xlink:)\bhref\s*=', "xlink:href=", tag, count=1)
        getan = getan or bool(n)
        aus.append(t[i:j])
        aus.append(tag)
        i = k
    return "".join(aus), getan


def xlink_notdurft(path):
    """Kopie der SVG, in der eingebettete Bilder auch ankommen - oder None.

    Inkscape 1.2 zeichnet <image href="..."> nicht, es will das alte
    xlink:href. Neuere Zeichenprogramme schreiben aber das schlichte href
    (SVG 2). Beim Rendern fehlt dann genau das eingebettete Motiv, und
    uebrig bleibt nur die Strichzeichnung drumherum.

    Dasselbe gilt eine Ebene tiefer: wer eine Schnittvorlage noch einmal
    einrahmt, bekommt die ganze alte Vorlage als data:image/svg+xml in die
    neue gelegt. Inkscape zeichnet diese innere SVG - und laesst darin
    wieder genau das Motiv weg. Herausgekommen ist zweimal ein Rahmen und
    kein Bild.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        t = f.read()
    t, getan = _xlink_text(t)
    if not getan:
        return None
    if "xmlns:xlink" not in t:
        t = t.replace("<svg", '<svg xmlns:xlink="http://www.w3.org/1999/xlink"', 1)
    tmp = tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False,
                                      encoding="utf-8")
    tmp.write(t)
    tmp.close()
    return tmp.name


# Was in einer SVG gezeichnet wird, und was nur Vorlage fuer anderes ist.
# Die zweite Gruppe bleibt immer stehen: ein Clip-Pfad oder Verlauf wird
# gebraucht, auch wenn nur noch das Bild uebrig ist.
VEKTORTAGS = ("path", "line", "polyline", "polygon", "rect", "circle",
              "ellipse", "text")
VORLAGETAGS = ("defs", "clipPath", "mask", "marker", "symbol", "pattern",
               "linearGradient", "radialGradient", "filter", "style",
               "title", "desc", "metadata")
SVGNS = "http://www.w3.org/2000/svg"
XLINKNS = "http://www.w3.org/1999/xlink"


def _tagname(el):
    return str(el.tag).split("}")[-1]


def _svg_zaehlen(el, bilder, vektoren):
    for k in el:
        name = _tagname(k)
        if name in VORLAGETAGS:
            continue                     # wird nicht selbst gezeichnet
        if name == "image":
            bilder.append(k)
        elif name in VEKTORTAGS:
            vektoren.append(k)
        else:
            _svg_zaehlen(k, bilder, vektoren)   # g, a, switch ...


def svg_anteile(path):
    """(Bilder, Vektorelemente) in einer SVG - Vorlagen wie defs zaehlen nicht.

    Beides in einer Datei ist der Normalfall bei Schnittvorlagen: das Motiv
    als eingebettetes Bild, die Schnittlinien als Pfade drumherum. Wer so
    eine Datei rastert, graviert sich die Schnittlinien ins Motiv - und die
    Vorlage ist hin.
    """
    bilder, vektoren = [], []
    _svg_zaehlen(ET.parse(path).getroot(), bilder, vektoren)
    return len(bilder), len(vektoren)


def svg_innenlinien(path, tiefe=TIEFE):
    """Wie viele Vektorelemente in SVGs stecken, die selbst nur als Bild in
    dieser SVG liegen. Die werden weder graviert noch geschnitten - ihr
    Rahmen ist der einer aelteren Vorlage, und das sollte man erfahren."""
    def zaehle(wurzel, t):
        bilder, vektoren = [], []
        _svg_zaehlen(wurzel, bilder, vektoren)
        n = 0
        if t > 0:
            for b in bilder:
                innen = (_eingebettete_svg(b.get("href"))
                         or _eingebettete_svg(b.get("{%s}href" % XLINKNS)))
                if innen:
                    r = ET.fromstring(innen)
                    eigene, tiefer = [], []
                    _svg_zaehlen(r, tiefer, eigene)
                    n += len(eigene) + zaehle(r, t - 1)
        return n
    try:
        return zaehle(ET.parse(path).getroot(), tiefe)
    except (ET.ParseError, OSError):
        return 0


def _ast_behalten(el):
    """Diesen Zweig aufraeumen. Rueckgabe: bleibt etwas uebrig?"""
    name = _tagname(el)
    if name == "image" or name in VORLAGETAGS:
        return True                      # Bild selbst, Vorlagen unangetastet
    drin = False
    for k in list(el):
        if _ast_behalten(k):
            drin = True
        else:
            el.remove(k)
    return drin


def _nur_bilder_baum(wurzel, tiefe=TIEFE):
    """Alles wegnehmen, was kein Bild ist - auch in SVGs, die als Bild in
    diesem Bild stecken. Rueckgabe: ist etwas weggefallen?"""
    bilder, vektoren = [], []
    _svg_zaehlen(wurzel, bilder, vektoren)
    getan = False
    if bilder and vektoren:
        for k in list(wurzel):
            if not _ast_behalten(k):
                wurzel.remove(k)
        getan = True
    if tiefe <= 0:
        return getan
    # Der Rahmen einer eingerahmten Schnittvorlage liegt nicht im Dokument,
    # sondern in dem Bild, als das die alte Vorlage darin steckt. Von aussen
    # ist er nicht zu erreichen - und wuerde mitgraviert.
    for bild in bilder:
        for attr in ("href", "{%s}href" % XLINKNS):
            innen = _eingebettete_svg(bild.get(attr))
            if not innen:
                continue
            r = ET.fromstring(innen)
            if _nur_bilder_baum(r, tiefe - 1):
                bild.set(attr, "data:image/svg+xml;base64," + base64.b64encode(
                    ET.tostring(r, encoding="utf-8")).decode())
                getan = True
    return getan


def nur_bilder(path):
    """Kopie der SVG, in der nur die eingebetteten Bilder gezeichnet werden -
    oder None, wenn es nichts wegzulassen gibt.

    Die Wurzel mit viewBox und Groesse bleibt, ebenso jede Gruppe, in der
    noch ein Bild steckt: das Bild liegt danach an genau derselben Stelle
    wie vorher, nur ohne die Striche drumherum.
    """
    ET.register_namespace("", SVGNS)
    ET.register_namespace("xlink", XLINKNS)
    baum = ET.parse(path)
    if not _nur_bilder_baum(baum.getroot()):
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".svg", delete=False)
    tmp.close()
    baum.write(tmp.name, encoding="utf-8", xml_declaration=True)
    return tmp.name


def load_source(path, px_w=None, nur_bild=False):
    """Bild oder SVG als Graustufenbild auf weissem Grund laden.
    SVGs werden mit Inkscape gerendert (px_w = gewuenschte Breite).

    nur_bild: enthaelt die SVG ein eingebettetes Bild UND Vektorlinien, wird
    nur das Bild gerendert - siehe svg_anteile().
    """
    if path.lower().endswith(".svg"):
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        args = ["inkscape", "--export-type=png", f"--export-filename={tmp}",
                "--export-background=white"]
        if px_w:
            args += ["-w", str(int(px_w))]
        gestrippt = nur_bilder(path) if nur_bild else None
        ersatz = xlink_notdurft(gestrippt or path)
        try:
            subprocess.run(args + [ersatz or gestrippt or path], check=True,
                           capture_output=True)
        finally:
            for weg in (ersatz, gestrippt):
                if weg:
                    os.unlink(weg)
        im = Image.open(tmp)
        im.load()
        os.unlink(tmp)
    else:
        im = Image.open(path)
        im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    return im.convert("L")


def inhalt_bb(im, schwelle=240):
    """Umriss alles Nichtweissen in Pixeln, oder None. Wer das Bild
    zuschneidet, muss wissen, wieviel vorne und oben wegfaellt - sonst
    verliert alles, was sich auf das Blatt bezieht, seinen Bezug."""
    a = np.asarray(im) < schwelle
    if not a.any():
        return None
    return Image.fromarray(a.astype(np.uint8) * 255).getbbox()


def autocrop(im, schwelle=240):
    bb = inhalt_bb(im, schwelle)
    return im.crop(bb) if bb else im


# ---------------------------------------------------------------- Raster
def bildkorrektur(im, helligkeit=0.0, kontrast=0.0, schaerfe=0.0):
    """Tonwerte und Schaerfe vor dem Rastern.

    Fotos kommen selten so, dass sie auf Holz funktionieren: der
    Hintergrund ist hellgrau statt weiss und wird deshalb als duenner
    Punkteteppich mitgebrannt, und feine Zeichnung geht beim Verkleinern
    verloren. Beides laesst sich hier geradeziehen.

    helligkeit, kontrast: -100 bis +100.  schaerfe: 0 bis 100.
    Geschaerft wird nach dem Verkleinern - vorher waere es wirkungslos.
    """
    if schaerfe:
        im = im.filter(ImageFilter.UnsharpMask(
            radius=2, percent=int(max(0.0, min(schaerfe, 100.0)) * 2.5),
            threshold=3))
    if not helligkeit and not kontrast:
        return im
    a = np.asarray(im).astype(np.float32) / 255.0
    c = 2.0 ** (float(kontrast) / 50.0)            # +100 -> 4x, -100 -> 0,25x
    a = (a - 0.5) * c + 0.5 + float(helligkeit) / 200.0
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8), "L")


def auto_tonwerte(im, unten=1.0, oben=20.0):
    """Helligkeit und Kontrast so, dass der Hintergrund weiss wird.

    Nimmt das untere und obere Perzentil als Schwarz- und Weisspunkt und
    rechnet daraus die beiden Regler zurueck - der Benutzer sieht also,
    was 'Auto' getan hat, und kann weiterdrehen.

    Das obere Perzentil ist mit 20 bewusst beherzt gewaehlt. Fuer einen
    Bildschirm waere das zu viel, fuer Holz nicht: was heller als etwa
    vier Fuenftel ist, soll blankes Holz bleiben und nicht als duenner
    Punkteteppich mitbrennen. Strichgrafik ruehrt das nicht an, die hat
    dort ohnehin nichts liegen.
    """
    a = np.asarray(im.convert("L")).astype(np.float32) / 255.0
    lo = float(np.percentile(a, unten))
    hi = float(np.percentile(a, 100.0 - oben))
    if hi - lo < 0.02:
        return 0.0, 0.0
    c = min(4.0, max(0.25, 1.0 / (hi - lo)))
    h = ((0.5 - lo) / (hi - lo) - 0.5) * 200.0
    return round(max(-100.0, min(100.0, h)), 1), round(50.0 * math.log2(c), 1)


def prepare(im, w_mm, h_mm, line, invert=False, rotate=0,
            mode="schwelle", schwelle=0.5, gamma=1.0,
            helligkeit=0.0, kontrast=0.0, schaerfe=0.0):
    """Liefert Leistungsmatrix 0..1 (1 = volle Leistung), Zeile 0 = oben."""
    if rotate:
        im = im.rotate(-rotate, expand=True, fillcolor=255)
    nx = max(1, int(round(w_mm / line)))
    ny = max(1, int(round(h_mm / line)))
    im = im.resize((nx, ny), Image.LANCZOS)
    im = bildkorrektur(im, helligkeit, kontrast, schaerfe)
    a = np.asarray(im).astype(np.float32) / 255.0
    dunkel = 1.0 - a
    if invert:
        dunkel = 1.0 - dunkel
    if mode == "schwelle":
        p = (dunkel >= (1.0 - schwelle)).astype(np.float32)
    elif mode == "raster":
        # Punktdichte statt Leistung: jeder Punkt brennt gleich stark, der
        # Tonwert kommt aus der Anzahl. Das umgeht die Kennlinie des
        # Materials - entscheidend bei Holz mit scharfer Schwelle, wo
        # zwischen "zeichnet nicht" und "verkohlt" kaum Platz ist.
        d = np.clip(dunkel, 0, 1) ** gamma
        grau = Image.fromarray(((1.0 - d) * 255).astype(np.uint8), "L")
        sw = grau.convert("1", dither=Image.FLOYDSTEINBERG)
        p = (np.asarray(sw) == 0).astype(np.float32)   # schwarz = brennen
    else:
        p = np.clip(dunkel, 0, 1) ** gamma
        p[p < 0.08] = 0.0
    return p


def anlauf_noetig(feed, accel):
    """Wie weit die Achse braucht, um den Vorschub zu erreichen.

    Im Lasermodus mit M4 skaliert GRBL die Leistung mit der tatsaechlichen
    Geschwindigkeit. Faengt eine Zeile an, bevor die Achse auf Tempo ist,
    brennt ihr Anfang zu schwach - bei 30 mm/s^2 und F1000 sind das
    4,6 mm, in denen die Leistung erst hochlaeuft. Der Anlauf muss also
    mindestens so lang sein, sonst steht im Werkstueck etwas anderes als
    in der Vorschau.

    s = v^2 / (2a), v in mm/s.
    """
    v = max(1e-6, float(feed) / 60.0)
    return v * v / (2.0 * max(1e-6, float(accel)))


def raster_gcode(p, line, s_max, feed, s_min=0, overscan=1.5, x_off=2.0,
                 y_off=0.0, merge=0.06, kommentar=""):
    """Leistungsmatrix -> G-Code-Zeilen. Rueckgabe (zeilen, info)."""
    ny, nx = p.shape
    g = [f"; Laserwerk {kommentar}".rstrip(),
         f"; {nx*line:.1f} x {ny*line:.1f} mm, row {line} mm, "
         f"S{s_max}/F{feed} = S/F {s_max/feed:.2f}",
         "; origin = bottom left corner", "G21", "G90", "G94", "M4 S0"]
    xm = lambda i: x_off + i * line
    marken = []                      # (Befehlsnummer, Art, Nummer, gesamt)
    cut = trav = 0.0
    xprev = yprev = 0.0
    rows = 0
    xmin, xmax = 1e9, -1e9
    # Je Zeile eine Bahn - die Achse faehrt sie in einem Zug durch, auch wenn
    # der Leistungsverlauf sie in viele Befehle zerlegt. Dazwischen der
    # Sprung in die naechste Zeile im Eilgang.
    bahnen, eilwege = [], []
    for r in range(ny):
        vals = p[ny - 1 - r]
        if not vals.any():
            continue
        rows += 1
        marken.append(len(g))
        y = y_off + r * line
        rev = rows % 2 == 0
        idx = np.flatnonzero(vals)
        lo, hi = int(idx[0]), int(idx[-1])
        # Leistung auf Stufen der Breite 'merge' rasten, dann Stufenwechsel
        # vektorisiert suchen - gleiche Nachbarn werden ein Segment.
        q = np.round(vals[lo:hi + 1] / merge).astype(np.int32)
        cuts = np.flatnonzero(np.diff(q)) + 1
        a_s = np.concatenate(([0], cuts))
        b_s = np.concatenate((cuts, [len(q)]))
        seg = [(lo + int(a), lo + int(b), min(1.0, float(q[a]) * merge))
               for a, b in zip(a_s, b_s)]
        if rev:
            seg = list(reversed(seg))
        start = xm(seg[0][1] if rev else seg[0][0])
        entry = start + (overscan if rev else -overscan)
        g.append(f"G0 X{entry:.3f} Y{y:.3f}")
        sprung = math.hypot(entry - xprev, y - yprev)
        eilwege.append(sprung)
        trav += sprung
        g.append(f"G1 X{start:.3f} S0 F{feed}")
        xmin, xmax = min(xmin, entry), max(xmax, entry)
        at = start
        for a_, b_, v in seg:
            xe = xm(a_ if rev else b_)
            if v <= 0:
                sv = 0
            else:
                sv = int(round(s_min + v * (s_max - s_min)))
            g.append(f"G1 X{xe:.3f} S{sv}")
            if sv:
                cut += abs(xe - at)
            at = xe
        ex = at + (-overscan if rev else overscan)
        g.append(f"G1 X{ex:.3f} S0")
        bahnen.append(abs(ex - entry))
        xmin, xmax = min(xmin, ex), max(xmax, ex)
        xprev, yprev = ex, y
    g += ["M5", "G0 X0 Y0"]
    heim = math.hypot(xprev, yprev)
    eilwege.append(heim)
    trav += heim
    info = dict(rows=rows, cut_m=cut / 1000, trav_m=trav / 1000,
                befehle=len(g), xmin=xmin, xmax=xmax,
                breite=nx * line, hoehe=ny * line,
                marken=[(idx, "zeile", k + 1, rows)
                        for k, idx in enumerate(marken)],
                sekunden=estimate(bahnen, feed, eilwege))
    return g, info


def fahrzeit(weg, v, accel=None):
    """Zeit fuer eine Strecke aus dem Stand bis zum Stillstand. v in mm/s.

    Trapez, solange die Strecke reicht, um v zu erreichen; sonst ein
    Dreieck, bei dem die Spitze unter v bleibt.
    """
    if weg <= 0 or v <= 0:
        return 0.0
    a = max(1e-6, float(ACCEL if accel is None else accel))
    if weg >= v * v / a:
        return 2 * v / a + (weg - v * v / a) / v
    return 2 * (weg / a) ** 0.5


def _ecktempo(u1, u2, accel, delta):
    """Tempo, mit dem GRBL ueber eine Ecke zwischen zwei Richtungen faehrt.

    Dieselbe Rechnung wie in GRBLs Planer: aus $11 und der Beschleunigung
    folgt, wie viel Tempo ein Richtungswechsel noch durchlaesst. Geradeaus
    ist die Grenze unendlich, eine Kehrtwende laesst nichts uebrig.
    """
    dot = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
    s = math.sqrt(max(0.0, 0.5 * (1.0 + dot)))     # cos(halber Wechsel)
    if s >= 1.0 - 1e-9:
        return float("inf")
    return math.sqrt(max(1e-9, accel) * delta * s / (1.0 - s))


def bahnzeit(pts, v, accel=None, delta=None):
    """Zeit fuer eine Punktfolge aus dem Stand bis zum Stillstand.

    Wie GRBLs Planer: an jeder Ecke begrenzt $11 das Tempo, dann ein Lauf
    rueckwaerts (rechtzeitig bremsen) und einer vorwaerts (nur so schnell,
    wie die Strecke hergibt). Eine Kontur als eine gerade Strecke zu
    rechnen war bei 2500 Abschnitten mit lauter Richtungswechseln fast um
    die Haelfte zu kurz - genau die Datei, bei der die Ansage daneben lag.
    """
    seg = []
    for a, b in zip(pts, pts[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L > 1e-9:
            seg.append((L, ((b[0] - a[0]) / L, (b[1] - a[1]) / L)))
    if not seg:
        return 0.0
    if len(seg) == 1:
        return fahrzeit(seg[0][0], v, accel)
    a = max(1e-6, float(ACCEL if accel is None else accel))
    delta = KREUZUNG if delta is None else delta
    n = len(seg)
    tempo = [0.0] * (n + 1)                 # erlaubtes Tempo an jedem Punkt
    for i in range(1, n):
        tempo[i] = min(v, _ecktempo(seg[i - 1][1], seg[i][1], a, delta))
    for i in range(n - 1, -1, -1):
        tempo[i] = min(tempo[i],
                       math.sqrt(tempo[i + 1] ** 2 + 2 * a * seg[i][0]))
    for i in range(n):
        tempo[i + 1] = min(tempo[i + 1],
                           math.sqrt(tempo[i] ** 2 + 2 * a * seg[i][0]))
    t = 0.0
    for i, (L, _) in enumerate(seg):
        ve, vx = tempo[i], tempo[i + 1]
        vp = min(v, math.sqrt((ve * ve + vx * vx) / 2 + a * L))
        if vp <= 0:
            continue
        la = max(0.0, (vp * vp - ve * ve) / (2 * a))
        lb = max(0.0, (vp * vp - vx * vx) / (2 * a))
        t += (vp - ve) / a + (vp - vx) / a + max(0.0, L - la - lb) / vp
    return t


def energie(s, f, passes=1, watt=None):
    """Energie je Millimeter in J/mm - das Mass, ob etwas schneidet.

    s zaehlt auf der Skala 0..S_MAX, f in mm/min. Nicht uebertragbar auf
    eine andere Maschine: watt ist die optische Leistung dieser Diode.
    """
    try:
        watt = WATT if watt is None else watt
        return watt * (float(s) / S_MAX) / (float(f) / 60.0) * max(1, int(passes))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def estimate(bahnen, feed, eilwege=(), accel=None, eil=None):
    """Laufzeit aus den Bahnen, die die Maschine faehrt.

    Eine Bahn ist, was ohne Halt durchlaeuft: eine ganze Gravurzeile, eine
    ganze Kontur. In wie viele Befehle der G-Code sie zerlegt, ist der Achse
    egal - fuer einen Leistungswechsel bremst sie nicht ab. Genau da lag das
    alte Modell daneben: es rechnete in Bloecken zu 15 Befehlen und bremste
    um so staerker, je feiner die Zerlegung war. Bei einer Graustufengravur
    kam dabei ungefaehr das Richtige heraus, bei Strichgrafik lag es rund ein
    Viertel zu niedrig - der Faktor 0,80, der das Modell an genau einem
    Graustufenlauf geeicht hat, zog alles andere mit nach unten.

    Was wirklich Zeit kostet, ist jeder Halt: am Zeilenende und an jeder
    Kontur beschleunigt die Achse aus dem Stand und bremst wieder ab - und
    jede Ecke dazwischen.

    Eine Bahn ist deshalb entweder eine Zahl (gerade Strecke, zum Beispiel
    eine Gravurzeile) oder eine Punktfolge. Im zweiten Fall zaehlen die
    Richtungswechsel mit: eine nachgezeichnete Kontur bremst an jeder Ecke,
    und das ist der Unterschied zwischen "Laserwerk sagt 43 min" und einer
    Stunde.
    """
    v = feed / 60.0
    ve = (EILGANG if eil is None else eil) / 60.0
    t = sum(fahrzeit(w, ve, accel) for w in eilwege)
    for b in bahnen:
        t += (bahnzeit(b, v, accel) if hasattr(b, "__len__")
              else fahrzeit(b, v, accel))
    return t


def preview_image(p):
    """Vorschau als PIL-Bild (gravierte Stellen dunkel) - fuer freies Zoomen."""
    return Image.fromarray(((1 - p) * 255).astype(np.uint8))


def preview_png(p, max_px=520):
    """Vorschau (gravierte Stellen dunkel) als PNG-Bytes fuer Tk."""
    img = Image.fromarray(((1 - p) * 255).astype(np.uint8))
    img.thumbnail((max_px, max_px), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), img.size


# ---------------------------------------------------------------- Tests
def fokustest_z(z_mitte, spanne, schritt, s, feed, laenge=12.0, abstand=3.0):
    """Striche bei verschiedenen Z-Hoehen. Links = tiefstes Z.
    Setzt eine gueltige Z-Referenz voraus (G92 Z = Materialdicke)."""
    n = int(round(spanne / schritt)) + 1
    zs = [round(z_mitte - spanne / 2 + i * schritt, 3) for i in range(n)]
    g = ["; focus test along Z", "G21", "G90", "G94", "M4 S0"]
    for i, z in enumerate(zs):
        x = 2.0 + i * abstand
        g += [f"G0 Z{z:.3f}", f"G0 X{x:.3f} Y2.000",
              f"G1 Y{2+laenge:.3f} S{s} F{feed}", "G1 S0"]
    g += ["M5", f"G0 Z{z_mitte:.3f}", "G0 X0 Y0"]
    return g, zs


def materialtest(powers, feeds, feld=6.0, gap=2.5, line=0.12):
    """Raster aus Feldern: Spalten = Leistung, Zeilen = Vorschub."""
    g = ["; material test", "G21", "G90", "G94", "M4 S0"]
    for r, f in enumerate(feeds):
        yb = 3.0 + r * (feld + gap)
        for c, s in enumerate(powers):
            xb = 3.0 + c * (feld + gap)
            g.append(f"; S{s} F{f} -> S/F {s/f:.2f}")
            for i in range(int(feld / line)):
                y = yb + i * line
                a, b = (xb, xb + feld) if i % 2 == 0 else (xb + feld, xb)
                g += [f"G0 X{a:.2f} Y{y:.2f}", f"G1 X{b:.2f} S{s} F{f}", "G1 S0"]
    g += ["M5", "G0 X0 Y0"]
    return g


def graustufentest(powers, feed, stufen=6, feld=7.0, gap=2.5, line=0.12,
                   boden=0.3, s_min=None):
    """Streifen aus Graustufenfeldern: eine Zeile je Leistung, darin ein
    Tonwertkeil von hell nach dunkel.

    Jedes Feld bekommt genau die Leistung, die eine Gravur an dieser Stelle
    auch bekaeme: s = boden*S + ton*(S - boden*S). So zeigt der Streifen,
    ab welchem Ton das Material ueberhaupt anspricht und ab welchem es
    zulaeuft - und der Vergleich der Zeilen sagt, welche Leistung passt.

    Unten die kleinste Leistung, links der hellste Ton.
    Rueckgabe (zeilen, info) wie bei raster_gcode.
    """
    g = ["; greyscale test", "; rows = power, columns = tone, light to dark",
         "G21", "G90", "G94", "M4 S0"]
    segs = []
    eilwege = []
    at = (0.0, 0.0)
    rows = 0
    for r, s_max in enumerate(powers):
        yb = 3.0 + r * (feld + gap)
        unten = int(round(s_max * boden)) if s_min is None else int(s_min)
        unten = min(unten, max(0, s_max - 1))
        g.append(f"; S{s_max} F{feed}")
        # Striche links: so viele wie die Zeilennummer. Sonst weiss man am
        # fertigen Brettchen nicht mehr, welche Zeile welche Leistung war.
        for k in range(r + 1):
            y = yb + 0.6 + k * 1.2
            for j in range(3):                   # 0,3 mm dick
                yy = y + j * line
                g += [f"G0 X0.6 Y{yy:.2f}",
                      f"G1 X2.4 S{s_max} F{feed}", "G1 S0"]
                eilwege.append(math.dist(at, (0.6, yy)))
                segs.append(1.8)
                at = (2.4, yy)
                rows += 1
        for c in range(stufen):
            ton = (c + 1) / stufen                     # hellstes Feld nicht leer
            sv = int(round(unten + ton * (s_max - unten)))
            xb = 3.0 + c * (feld + gap * 0.2)
            g.append(f"; Ton {ton:.2f} -> S{sv}")
            for i in range(int(feld / line)):
                y = yb + i * line
                a_, b_ = (xb, xb + feld) if i % 2 == 0 else (xb + feld, xb)
                g += [f"G0 X{a_:.2f} Y{y:.2f}",
                      f"G1 X{b_:.2f} S{sv} F{feed}", "G1 S0"]
                eilwege.append(math.dist(at, (a_, y)))
                segs.append(feld)
                at = (b_, y)
                rows += 1
    g += ["M5", "G0 X0 Y0"]
    breite = stufen * feld + (stufen - 1) * gap * 0.2
    hoehe = len(powers) * feld + (len(powers) - 1) * gap
    info = dict(rows=rows, cut_m=sum(segs) / 1000,
                trav_m=sum(eilwege) / 1000, befehle=len(g),
                xmin=0.6, xmax=3.0 + breite, breite=breite + 2.4, hoehe=hoehe,
                sekunden=estimate(segs, feed, eilwege))
    return g, info


def gcode_preview(lines, px_per_mm, s_max=S_MAX, super_=3):
    """Fremden G-Code nachzeichnen: jede Fahrt mit Laser an, Graustufe nach S.
    Beachtet G0/G1/G2/G3 (Boegen als Sehne), G90/G91, M3/M4/M5, modale Werte.
    Rueckgabe: (png, (x0, y0, x1, y1), info) - info wie bei raster_gcode."""
    import re
    from PIL import ImageDraw
    word = re.compile(r"([A-Z])\s*([-+]?\d*\.?\d+)")
    x = y = 0.0
    mode, s, feed = 0, 0.0, 1000.0
    rel, laser = False, False
    moves = []                      # (x0, y0, x1, y1, leistung 0..1 oder None)
    for raw in lines:
        l = re.sub(r"\(.*?\)|;.*", "", raw).upper()
        if not l.strip():
            continue
        w = word.findall(l)
        for k, v in w:
            if k == "G":
                g = float(v)
                if g in (0, 1, 2, 3): mode = int(g)
                elif g == 90: rel = False
                elif g == 91: rel = True
            elif k == "M":
                m = int(float(v))
                if m in (3, 4): laser = True
                elif m in (5, 2, 30): laser = False
            elif k == "S": s = float(v)
            elif k == "F": feed = float(v) or feed
        d = dict(w)
        if "X" not in d and "Y" not in d:
            continue
        nx = (x + float(d["X"])) if rel and "X" in d else float(d.get("X", x))
        ny = (y + float(d["Y"])) if rel and "Y" in d else float(d.get("Y", y))
        on = laser and mode != 0 and s > 0
        moves.append((x, y, nx, ny, min(1.0, s / s_max) if on else None))
        x, y = nx, ny
    if not moves:
        return None, (0, 0, 0, 0), None
    xs = [c for m in moves for c in (m[0], m[2])]
    ys = [c for m in moves for c in (m[1], m[3])]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sc = px_per_mm * super_
    W = max(2, int((x1 - x0) * sc) + 2)
    H = max(2, int((y1 - y0) * sc) + 2)
    im = Image.new("L", (W, H), 255)
    dr = ImageDraw.Draw(im)
    cut = trav = 0.0
    # Fremder G-Code sagt nicht, wo eine Bahn aufhoert: alles, was ohne G0
    # dazwischen weiterlaeuft, ist eine. Wie viel Tempo die Ecken darin
    # durchlassen, rechnet estimate - hier wurde frueher pauschal bei
    # ueber 60 Grad angehalten und alles darunter geschenkt.
    bahnen, eilwege = [], []
    lauf = []
    for a, b, c, e, p in moves:
        L = ((c - a) ** 2 + (e - b) ** 2) ** 0.5
        if p is None:
            if len(lauf) > 1:
                bahnen.append(lauf)
            lauf = []
            eilwege.append(L)
            trav += L
            continue
        if not lauf:
            lauf.append((a, b))
        lauf.append((c, e))
        cut += L
        dr.line([((a - x0) * sc, H - 1 - (b - y0) * sc),
                 ((c - x0) * sc, H - 1 - (e - y0) * sc)],
                fill=int(255 * (1 - 0.9 * p)), width=max(1, super_))
    im = im.resize((max(1, W // super_), max(1, H // super_)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    if len(lauf) > 1:
        bahnen.append(lauf)
    info = dict(breite=x1 - x0, hoehe=y1 - y0, xmin=x0, xmax=x1, ymin=y0, ymax=y1,
                befehle=len(lines), cut_m=cut / 1000, trav_m=trav / 1000,
                sekunden=estimate(bahnen, feed, eilwege))
    return buf.getvalue(), (x0, y0, x1, y1), info


def extent(lines):
    import re
    xs, ys = [], []
    for l in lines:
        c = l.split(";")[0]
        mx = re.search(r"X(-?[\d.]+)", c)
        my = re.search(r"Y(-?[\d.]+)", c)
        if mx: xs.append(float(mx.group(1)))
        if my: ys.append(float(my.group(1)))
    if not xs:
        return 0, 0, 0, 0
    return min(xs), max(xs), min(ys), max(ys)


def z_extent(lines):
    """Tiefster und hoechster Z-Wert einer Datei, oder None ohne Z.

    Beim Lasern kommt Z hoechstens im Fokustest vor; beim Fraesen ist es
    die Zustellung, und zu tief heisst: in die Unterlage.
    """
    import re
    werte = []
    for l in lines:
        c = l.split(";")[0].upper()
        m = re.search(r"Z(-?[\d.]+)", c)
        if m:
            try:
                werte.append(float(m.group(1)))
            except ValueError:
                pass
    return (min(werte), max(werte)) if werte else None


def brenn_extent(lines):
    """Ausdehnung dessen, was wirklich gebrannt wird.

    extent() nimmt jede Koordinate mit - also auch den Anlauf links und
    rechts der Zeilen und das abschliessende 'G0 X0 Y0'. Ein Rahmen daraus
    beginnt an der Nullecke statt am Motiv. Hier zaehlen nur Fahrten mit
    eingeschaltetem Strahl, jeweils Anfang und Ende der Strecke.
    """
    import re
    x = y = 0.0
    s = 0.0
    modus = 0                      # G0/G1/G2/G3 gelten modal weiter
    aus = True                     # bis zum ersten M3/M4
    xs, ys = [], []
    for l in lines:
        c = l.split(";")[0].strip().upper()
        if not c:
            continue
        if "M5" in c:
            aus = True
        if "M3" in c or "M4" in c:
            aus = False
        mg = re.match(r"G(\d+)", c)
        if mg:
            modus = int(mg.group(1))
        ms = re.search(r"S(-?[\d.]+)", c)
        if ms:
            s = float(ms.group(1))
        mx = re.search(r"X(-?[\d.]+)", c)
        my = re.search(r"Y(-?[\d.]+)", c)
        if not (mx or my):
            continue
        nx = float(mx.group(1)) if mx else x
        ny = float(my.group(1)) if my else y
        if modus in (1, 2, 3) and s > 0 and not aus:
            xs += [x, nx]
            ys += [y, ny]
        x, y = nx, ny
    if not xs:
        return extent(lines)       # nichts gefunden: lieber zu gross als falsch
    return min(xs), max(xs), min(ys), max(ys)


def frame_lines(lines, s=0, feed=600):
    """Rechteck um den Job abfahren. Mit s>0 laeuft der Laser schwach mit,
    damit man den Rahmen sieht - im Lasermodus geht das nur waehrend G1."""
    x0, x1, y0, y1 = brenn_extent(lines)
    ecken = [(x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    g = ["G21", "G90", "G94", "M5", f"G0 X{x0:.2f} Y{y0:.2f}"]
    if s > 0:
        g.append(f"M3 S{int(s)}")
        g += [f"G1 X{x:.2f} Y{y:.2f} F{int(feed)}" for x, y in ecken]
        g += ["M5"]
    else:
        g += [f"G0 X{x:.2f} Y{y:.2f}" for x, y in ecken]
    return g


def kreuz_lines(s, feed=600, arm=3.0):
    """Sichtkreuz um die aktuelle Position, danach exakt zurueck."""
    g = [f"M3 S{int(s)}", "G91"]
    for ax in ("X", "Y"):
        g += [f"G1 {ax}-{arm:.2f} F{int(feed)}", f"G1 {ax}{2*arm:.2f}",
              f"G1 {ax}-{arm:.2f}"]
    return g + ["M5", "G90"]
