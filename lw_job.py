"""
Bild/SVG -> Rastergravur-G-Code, Testmuster, Laufzeitschaetzung.

Grundregeln aus der Praxis:
  - M4 (dynamische Leistung): bei Stillstand/Pause ist der Laser aus.
  - Energie pro mm haengt am Verhaeltnis S/F, nicht an S allein.
  - Bidirektional mit Overscan, Leerstellen mit S0 statt G0 (kein Stottern).
  - Nullpunkt = linke untere Ecke des Motivs, alle Koordinaten positiv.
"""
import io, os, subprocess, tempfile
import numpy as np
from PIL import Image

S_MAX = 1000          # $30
ACCEL = 30.0          # $120 mm/s^2
LOOKAHEAD = 15        # Planner-Bloecke
POINTER_FEED = 600    # Vorschub fuer Sichtkreuz und sichtbaren Rahmen


# ---------------------------------------------------------------- Laden
def load_source(path, px_w=None):
    """Bild oder SVG als Graustufenbild auf weissem Grund laden.
    SVGs werden mit Inkscape gerendert (px_w = gewuenschte Breite)."""
    if path.lower().endswith(".svg"):
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        args = ["inkscape", "--export-type=png", f"--export-filename={tmp}",
                "--export-background=white"]
        if px_w:
            args += ["-w", str(int(px_w))]
        subprocess.run(args + [path], check=True, capture_output=True)
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


def autocrop(im, schwelle=240):
    a = np.asarray(im) < schwelle
    if not a.any():
        return im
    bb = Image.fromarray(a.astype(np.uint8) * 255).getbbox()
    return im.crop(bb)


# ---------------------------------------------------------------- Raster
def prepare(im, w_mm, h_mm, line, invert=False, rotate=0,
            mode="schwelle", schwelle=0.5, gamma=1.0):
    """Liefert Leistungsmatrix 0..1 (1 = volle Leistung), Zeile 0 = oben."""
    if rotate:
        im = im.rotate(-rotate, expand=True, fillcolor=255)
    nx = max(1, int(round(w_mm / line)))
    ny = max(1, int(round(h_mm / line)))
    im = im.resize((nx, ny), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32) / 255.0
    dunkel = 1.0 - a
    if invert:
        dunkel = 1.0 - dunkel
    if mode == "schwelle":
        p = (dunkel >= (1.0 - schwelle)).astype(np.float32)
    else:
        p = np.clip(dunkel, 0, 1) ** gamma
        p[p < 0.08] = 0.0
    return p


def raster_gcode(p, line, s_max, feed, s_min=0, overscan=1.5, x_off=2.0,
                 y_off=0.0, merge=0.06, kommentar=""):
    """Leistungsmatrix -> G-Code-Zeilen. Rueckgabe (zeilen, info)."""
    ny, nx = p.shape
    g = [f"; Laserwerk {kommentar}".rstrip(),
         f"; {nx*line:.1f} x {ny*line:.1f} mm, row {line} mm, "
         f"S{s_max}/F{feed} = S/F {s_max/feed:.2f}",
         "; origin = bottom left corner", "G21", "G90", "G94", "M4 S0"]
    xm = lambda i: x_off + i * line
    cut = trav = 0.0
    xprev = 0.0
    rows = 0
    xmin, xmax = 1e9, -1e9
    segs_len = []
    for r in range(ny):
        vals = p[ny - 1 - r]
        if not vals.any():
            continue
        rows += 1
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
        trav += abs(entry - xprev)
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
            segs_len.append(abs(xe - at))
            at = xe
        ex = at + (-overscan if rev else overscan)
        g.append(f"G1 X{ex:.3f} S0")
        segs_len.append(overscan)
        xmin, xmax = min(xmin, ex), max(xmax, ex)
        xprev = ex
    g += ["M5", "G0 X0 Y0"]
    info = dict(rows=rows, cut_m=cut / 1000, trav_m=trav / 1000,
                befehle=len(g), xmin=xmin, xmax=xmax,
                breite=nx * line, hoehe=ny * line,
                sekunden=estimate(segs_len, feed, rows))
    return g, info


def estimate(segs, feed, stops):
    """Lookahead-Modell: GRBL sieht 15 Bloecke voraus. Kurze Segmente
    bremsen die Achse. Geeicht am Wildschwein-Lauf vom 19.9.:
    30.000 Befehle in 29 min, Modell ergab 36 min -> Faktor 0,80,
    kein zusaetzlicher Aufwand je Befehl messbar."""
    v = feed / 60.0
    d = np.asarray(segs, dtype=float)
    t = 0.0
    for i in range(0, len(d), LOOKAHEAD):
        w = d[i:i + LOOKAHEAD].sum()
        if w <= 0:
            continue
        vp = min(v, (ACCEL * w) ** 0.5)
        t += w / max(vp * 0.75, 0.5)
    return t * 0.80


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
                segs.append(1.8)
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
                segs.append(feld)
                rows += 1
    g += ["M5", "G0 X0 Y0"]
    breite = stufen * feld + (stufen - 1) * gap * 0.2
    hoehe = len(powers) * feld + (len(powers) - 1) * gap
    info = dict(rows=rows, cut_m=sum(segs) / 1000, trav_m=0.0, befehle=len(g),
                xmin=0.6, xmax=3.0 + breite, breite=breite + 2.4, hoehe=hoehe,
                sekunden=estimate(segs, feed, rows))
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
    segs = []
    for a, b, c, e, p in moves:
        L = ((c - a) ** 2 + (e - b) ** 2) ** 0.5
        segs.append(L)
        if p is None:
            trav += L
            continue
        cut += L
        dr.line([((a - x0) * sc, H - 1 - (b - y0) * sc),
                 ((c - x0) * sc, H - 1 - (e - y0) * sc)],
                fill=int(255 * (1 - 0.9 * p)), width=max(1, super_))
    im = im.resize((max(1, W // super_), max(1, H // super_)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    info = dict(breite=x1 - x0, hoehe=y1 - y0, xmin=x0, xmax=x1, ymin=y0, ymax=y1,
                befehle=len(lines), cut_m=cut / 1000, trav_m=trav / 1000,
                sekunden=estimate(segs, feed, 0))
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
