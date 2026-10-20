"""
SVG -> Konturen -> Schnitt-G-Code.

Ablauf:
  1. Inkscape vereinheitlicht: Formen und Text werden zu <path>.
  2. Eigener Parser liest Pfade (M L H V C S Q T A Z, absolut/relativ)
     und wendet alle transform-Attribute an.
  3. Kurven werden in Polylinien zerlegt (Sehnenlaenge ~0,15 mm am Werkstueck).
  4. Reihenfolge: innere Konturen vor aeusseren (sonst faellt das Teil heraus,
     bevor die Loecher geschnitten sind), sonst naechster Nachbar.
"""
import math, os, re, subprocess, tempfile
import xml.etree.ElementTree as ET

NUM = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
TOK = re.compile(rf"([MmLlHhVvCcSsQqTtAaZz])|({NUM})")


# ---------------------------------------------------------------- Affine
def mat_mul(a, b):
    """a*b, Matrizen als (a,b,c,d,e,f) wie in SVG."""
    return (a[0]*b[0] + a[2]*b[1], a[1]*b[0] + a[3]*b[1],
            a[0]*b[2] + a[2]*b[3], a[1]*b[2] + a[3]*b[3],
            a[0]*b[4] + a[2]*b[5] + a[4], a[1]*b[4] + a[3]*b[5] + a[5])


def apply(m, p):
    return (m[0]*p[0] + m[2]*p[1] + m[4], m[1]*p[0] + m[3]*p[1] + m[5])


def parse_transform(s):
    m = (1, 0, 0, 1, 0, 0)
    if not s:
        return m
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s):
        v = [float(x) for x in re.findall(NUM, args)]
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale":
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate":
            a = math.radians(v[0]); c, s_ = math.cos(a), math.sin(a)
            t = (c, s_, -s_, c, 0, 0)
            if len(v) == 3:
                t = mat_mul(mat_mul((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
        elif name == "skewX":
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewY":
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = mat_mul(m, t)
    return m


# ---------------------------------------------------------------- Pfade
def _arc_to_cubics(p0, rx, ry, phi, fa, fs, p1):
    """SVG-Bogen -> Liste kubischer Bezier (je <= 90 Grad)."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [(p0, p0, p1, p1)]
    rx, ry = abs(rx), abs(ry)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1 = cp*dx + sp*dy; y1 = -sp*dx + cp*dy
    lam = x1*x1/(rx*rx) + y1*y1/(ry*ry)
    if lam > 1:
        rx *= math.sqrt(lam); ry *= math.sqrt(lam)
    num = rx*rx*ry*ry - rx*rx*y1*y1 - ry*ry*x1*x1
    den = rx*rx*y1*y1 + ry*ry*x1*x1
    co = math.sqrt(max(0, num/den)) if den else 0
    if fa == fs:
        co = -co
    cx1, cy1 = co*rx*y1/ry, -co*ry*x1/rx
    cx = cp*cx1 - sp*cy1 + (p0[0]+p1[0])/2
    cy = sp*cx1 + cp*cy1 + (p0[1]+p1[1])/2
    ang = lambda ux, uy, vx, vy: math.atan2(ux*vy - uy*vx, ux*vx + uy*vy)
    t1 = ang(1, 0, (x1-cx1)/rx, (y1-cy1)/ry)
    dt = ang((x1-cx1)/rx, (y1-cy1)/ry, (-x1-cx1)/rx, (-y1-cy1)/ry)
    if not fs and dt > 0: dt -= 2*math.pi
    if fs and dt < 0: dt += 2*math.pi
    n = max(1, int(math.ceil(abs(dt)/(math.pi/2))))
    d = dt/n
    k = 4/3*math.tan(d/4)
    out = []
    pt = lambda t: (cx + rx*math.cos(t)*cp - ry*math.sin(t)*sp,
                    cy + rx*math.cos(t)*sp + ry*math.sin(t)*cp)
    dv = lambda t: (-rx*math.sin(t)*cp - ry*math.cos(t)*sp,
                    -rx*math.sin(t)*sp + ry*math.cos(t)*cp)
    t = t1
    for _ in range(n):
        a, b = pt(t), pt(t+d)
        da, db = dv(t), dv(t+d)
        out.append((a, (a[0]+k*da[0], a[1]+k*da[1]),
                    (b[0]-k*db[0], b[1]-k*db[1]), b))
        t += d
    return out


def parse_path(d):
    """d-Attribut -> Liste Unterpfade; jeder Unterpfad = Liste Segmente
    ('L', p0, p1) oder ('C', p0, c1, c2, p1); dazu Flag geschlossen."""
    toks = TOK.findall(d)
    i = 0
    subs = []
    cur = None
    pos = start = (0.0, 0.0)
    last_c = last_q = None
    cmd = None

    def num():
        nonlocal i
        v = float(toks[i][1]); i += 1
        return v

    while i < len(toks):
        if toks[i][0]:
            cmd = toks[i][0]; i += 1
        elif cmd is None:
            i += 1; continue
        rel = cmd.islower()
        C = cmd.upper()
        off = pos if rel else (0.0, 0.0)
        if C == "Z":
            if cur is not None:
                if pos != start:
                    cur["seg"].append(("L", pos, start))
                cur["closed"] = True
                pos = start
            last_c = last_q = None
            cmd = None          # Zahlen direkt nach Z werden uebersprungen
            continue
        if i >= len(toks) or not toks[i][1]:
            continue
        if C == "M":
            p = (num()+off[0], num()+off[1])
            cur = {"seg": [], "closed": False}
            subs.append(cur)
            pos = start = p
            cmd = "l" if rel else "L"
            last_c = last_q = None
            continue
        if cur is None:
            cur = {"seg": [], "closed": False}; subs.append(cur)
        if C == "L":
            p = (num()+off[0], num()+off[1]); cur["seg"].append(("L", pos, p)); pos = p
            last_c = last_q = None
        elif C == "H":
            x = num() + (pos[0] if rel else 0); p = (x, pos[1])
            cur["seg"].append(("L", pos, p)); pos = p; last_c = last_q = None
        elif C == "V":
            y = num() + (pos[1] if rel else 0); p = (pos[0], y)
            cur["seg"].append(("L", pos, p)); pos = p; last_c = last_q = None
        elif C == "C":
            c1 = (num()+off[0], num()+off[1]); c2 = (num()+off[0], num()+off[1])
            p = (num()+off[0], num()+off[1])
            cur["seg"].append(("C", pos, c1, c2, p)); last_c = c2; last_q = None; pos = p
        elif C == "S":
            c1 = (2*pos[0]-last_c[0], 2*pos[1]-last_c[1]) if last_c else pos
            c2 = (num()+off[0], num()+off[1]); p = (num()+off[0], num()+off[1])
            cur["seg"].append(("C", pos, c1, c2, p)); last_c = c2; last_q = None; pos = p
        elif C in "QT":
            if C == "Q":
                q = (num()+off[0], num()+off[1])
            else:
                q = (2*pos[0]-last_q[0], 2*pos[1]-last_q[1]) if last_q else pos
            p = (num()+off[0], num()+off[1])
            c1 = (pos[0]+2/3*(q[0]-pos[0]), pos[1]+2/3*(q[1]-pos[1]))
            c2 = (p[0]+2/3*(q[0]-p[0]), p[1]+2/3*(q[1]-p[1]))
            cur["seg"].append(("C", pos, c1, c2, p)); last_q = q; last_c = None; pos = p
        elif C == "A":
            rx, ry, rot = num(), num(), num()
            fa, fs = int(num()), int(num())
            p = (num()+off[0], num()+off[1])
            for b in _arc_to_cubics(pos, rx, ry, math.radians(rot), fa, fs, p):
                cur["seg"].append(("C",) + b)
            pos = p; last_c = last_q = None
    return [s for s in subs if s["seg"]]


# ---------------------------------------------------------------- SVG laden
def _units(v, default=None):
    if v is None:
        return default
    m = re.match(rf"\s*({NUM})\s*([a-z%]*)", v)
    if not m:
        return default
    x, u = float(m.group(1)), m.group(2)
    return x * {"mm": 1, "cm": 10, "in": 25.4, "pt": 25.4/72, "pc": 25.4/6,
                "px": 25.4/96, "": 25.4/96}.get(u, 25.4/96)


def normalize(path):
    """Inkscape: alles zu Pfaden, Text zu Kurven, einfaches SVG."""
    out = tempfile.NamedTemporaryFile(suffix=".svg", delete=False).name
    subprocess.run(["inkscape", path, "--actions=select-all:all;object-to-path",
                    "--export-plain-svg", "--export-text-to-path",
                    f"--export-filename={out}"], check=True, capture_output=True)
    return out


def load_svg(path):
    """-> Liste Unterpfade in mm (Y nach oben), Segmente wie parse_path."""
    tmp = normalize(path)
    try:
        root = ET.parse(tmp).getroot()
    finally:
        os.unlink(tmp)
    vb = root.get("viewBox")
    w_mm = _units(root.get("width")); h_mm = _units(root.get("height"))
    if vb:
        vx, vy, vw, vh = [float(x) for x in re.findall(NUM, vb)]
        sx = (w_mm / vw) if w_mm else 25.4/96
        sy = (h_mm / vh) if h_mm else sx
        base = (sx, 0, 0, sy, -vx*sx, -vy*sy)
    else:
        base = (25.4/96, 0, 0, 25.4/96, 0, 0)
    subs = []

    def walk(el, m):
        tag = el.tag.split("}")[-1]
        if tag in ("defs", "clipPath", "mask", "metadata", "title", "desc", "symbol"):
            return
        m = mat_mul(m, parse_transform(el.get("transform")))
        if tag == "path" and el.get("d"):
            for sp in parse_path(el.get("d")):
                segs = []
                for s in sp["seg"]:
                    segs.append((s[0],) + tuple(apply(m, p) for p in s[1:]))
                subs.append({"seg": segs, "closed": sp["closed"]})
        for ch in el:
            walk(ch, m)

    walk(root, base)
    # SVG hat Y nach unten -> spiegeln
    for sp in subs:
        sp["seg"] = [(s[0],) + tuple((p[0], -p[1]) for p in s[1:]) for s in sp["seg"]]
    return subs


# ---------------------------------------------------------------- DXF
# Eigener Leser statt Inkscape: Inkscapes DXF-Import oeffnet selbst im
# Kommandozeilenbetrieb einen Optionsdialog und wartet auf Eingabe.
DXF_UNITS = {0: 1.0, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 8: 25.4e-6,
             9: 0.0254, 10: 914.4}


def _arc_cubics(cx, cy, r, a0, a1):
    """Kreisbogen (Winkel in rad, gegen den Uhrzeigersinn von a0 nach a1)."""
    while a1 <= a0:
        a1 += 2 * math.pi
    n = max(1, int(math.ceil((a1 - a0) / (math.pi / 2) - 1e-9)))
    d = (a1 - a0) / n
    k = 4 / 3 * math.tan(d / 4)
    out = []
    for i in range(n):
        t0, t1 = a0 + i * d, a0 + (i + 1) * d
        p0 = (cx + r * math.cos(t0), cy + r * math.sin(t0))
        p1 = (cx + r * math.cos(t1), cy + r * math.sin(t1))
        c1 = (p0[0] - k * r * math.sin(t0), p0[1] + k * r * math.cos(t0))
        c2 = (p1[0] + k * r * math.sin(t1), p1[1] - k * r * math.cos(t1))
        out.append(("C", p0, c1, c2, p1))
    return out


def _bulge_segs(p0, p1, b):
    """LWPOLYLINE-Segment mit Woelbung b = tan(Oeffnungswinkel/4)."""
    if abs(b) < 1e-9:
        return [("L", p0, p1)]
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    c = math.hypot(dx, dy)
    if c < 1e-12:
        return []
    r = c * (1 + b * b) / (4 * abs(b))
    # Mittelpunkt: von der Sehnenmitte entlang der linken Normalen; der
    # vorzeichenbehaftete Abstand deckt beide Seiten und Boegen > 180 Grad ab.
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    off = c * (1 - b * b) / (4 * b)
    cx, cy = mx - dy / c * off, my + dx / c * off
    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    a1 = math.atan2(p1[1] - cy, p1[0] - cx)
    if b > 0:
        return _arc_cubics(cx, cy, r, a0, a1)
    segs = _arc_cubics(cx, cy, r, a1, a0)          # rueckwaerts
    return [("C", s_[4], s_[3], s_[2], s_[1]) for s_ in reversed(segs)]


def _bspline(deg, knots, ctrl, n=64):
    """B-Spline mit de Boor abtasten."""
    if len(ctrl) < 2:
        return ctrl
    if not knots or len(knots) != len(ctrl) + deg + 1:
        m = len(ctrl)
        knots = [0] * (deg + 1) + list(range(1, m - deg)) + [m - deg] * (deg + 1)
    lo, hi = knots[deg], knots[len(knots) - deg - 1]
    pts = []
    for i in range(n + 1):
        t = lo + (hi - lo) * i / n
        k = deg
        while k < len(knots) - deg - 2 and t >= knots[k + 1]:
            k += 1
        d = [list(ctrl[j]) for j in range(k - deg, k + 1)]
        for r in range(1, deg + 1):
            for j in range(deg, r - 1, -1):
                ii = j + k - deg
                den = knots[ii + deg - r + 1] - knots[ii]
                a = 0 if den == 0 else (t - knots[ii]) / den
                d[j] = [(1 - a) * d[j - 1][0] + a * d[j][0],
                        (1 - a) * d[j - 1][1] + a * d[j][1]]
        pts.append(tuple(d[deg]))
    return pts


def load_dxf(path):
    """DXF -> Unterpfade in mm (Y nach oben)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = [l.rstrip("\r\n") for l in f]
    pairs = [(raw[i].strip(), raw[i + 1].strip()) for i in range(0, len(raw) - 1, 2)]
    unit = 1.0
    for i, (c, v) in enumerate(pairs):
        if c == "9" and v == "$INSUNITS" and i + 1 < len(pairs):
            unit = DXF_UNITS.get(int(pairs[i + 1][1]), 1.0)
            break
    # Entitaeten des ENTITIES-Abschnitts sammeln
    ents, cur, in_ent = [], None, False
    for i, (c, v) in enumerate(pairs):
        if c == "2" and i > 0 and pairs[i - 1] == ("0", "SECTION"):
            in_ent = v == "ENTITIES"
            continue
        if not in_ent:
            continue
        if c == "0":
            if v == "ENDSEC":
                in_ent = False
            cur = {"type": v, "g": []}
            ents.append(cur)
        elif cur is not None:
            cur["g"].append((c, v))
    subs = []

    def fv(e, code, default=0.0):
        for c, v in e["g"]:
            if c == code:
                return float(v)
        return default

    i = 0
    while i < len(ents):
        e = ents[i]; t = e["type"]
        segs, closed = [], False
        if t == "LINE":
            segs = [("L", (fv(e, "10"), fv(e, "20")), (fv(e, "11"), fv(e, "21")))]
        elif t == "CIRCLE":
            segs = _arc_cubics(fv(e, "10"), fv(e, "20"), fv(e, "40"), 0, 2 * math.pi)
            closed = True
        elif t == "ARC":
            segs = _arc_cubics(fv(e, "10"), fv(e, "20"), fv(e, "40"),
                               math.radians(fv(e, "50")), math.radians(fv(e, "51")))
        elif t == "LWPOLYLINE":
            pts, bul = [], []
            for c, v in e["g"]:
                if c == "10": pts.append([float(v), 0.0]); bul.append(0.0)
                elif c == "20" and pts: pts[-1][1] = float(v)
                elif c == "42" and bul: bul[-1] = float(v)
            closed = int(fv(e, "70")) & 1 == 1
            n = len(pts)
            for k in range(n if closed else n - 1):
                segs += _bulge_segs(tuple(pts[k]), tuple(pts[(k + 1) % n]), bul[k])
        elif t == "POLYLINE":
            closed = int(fv(e, "70")) & 1 == 1
            pts, bul = [], []
            i += 1
            while i < len(ents) and ents[i]["type"] == "VERTEX":
                pts.append((fv(ents[i], "10"), fv(ents[i], "20"))); bul.append(fv(ents[i], "42"))
                i += 1
            n = len(pts)
            for k in range(n if closed else n - 1):
                segs += _bulge_segs(pts[k], pts[(k + 1) % n], bul[k])
            if segs:
                subs.append({"seg": segs, "closed": closed})
            continue            # SEQEND wird uebersprungen
        elif t == "SPLINE":
            deg = int(fv(e, "71", 3))
            knots = [float(v) for c, v in e["g"] if c == "40"]
            cx = [float(v) for c, v in e["g"] if c == "10"]
            cy = [float(v) for c, v in e["g"] if c == "20"]
            fx = [float(v) for c, v in e["g"] if c == "11"]
            fy = [float(v) for c, v in e["g"] if c == "21"]
            if cx:
                pts = _bspline(deg, knots, list(zip(cx, cy)), n=max(32, 16 * len(cx)))
            else:
                pts = list(zip(fx, fy))
            closed = int(fv(e, "70")) & 1 == 1
            segs = [("L", a, b) for a, b in zip(pts, pts[1:])]
        elif t == "ELLIPSE":
            cxe, cye = fv(e, "10"), fv(e, "20")
            mx, my, ratio = fv(e, "11"), fv(e, "21"), fv(e, "40", 1.0)
            t0, t1 = fv(e, "41"), fv(e, "42", 2 * math.pi)
            while t1 <= t0:
                t1 += 2 * math.pi
            n = 96
            pts = []
            for k in range(n + 1):
                tt = t0 + (t1 - t0) * k / n
                pts.append((cxe + mx * math.cos(tt) - ratio * my * math.sin(tt),
                            cye + my * math.cos(tt) + ratio * mx * math.sin(tt)))
            closed = abs((t1 - t0) - 2 * math.pi) < 1e-6
            segs = [("L", a, b) for a, b in zip(pts, pts[1:])]
        if segs:
            segs = [(s_[0],) + tuple((p[0] * unit, p[1] * unit) for p in s_[1:]) for s_ in segs]
            subs.append({"seg": segs, "closed": closed})
        i += 1
    return subs


def load_vector(path):
    return load_dxf(path) if path.lower().endswith(".dxf") else load_svg(path)


def render_preview(polys, px=1500):
    """Konturen als Bild (fuer Vorschau/Seitenverhaeltnis bei DXF)."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = bbox(polys)
    s = px / max(x1 - x0, y1 - y0, 1e-9)
    w, h = int((x1 - x0) * s) + 4, int((y1 - y0) * s) + 4
    im = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(im)
    for pl in polys:
        pts = [(2 + (p[0] - x0) * s, h - 2 - (p[1] - y0) * s) for p in pl["pts"]]
        if pl["closed"]:
            pts.append(pts[0])
        d.line(pts, fill=0, width=2)
    return im


# ---------------------------------------------------------------- Geometrie
def _bez(p0, c1, c2, p1, t):
    u = 1 - t
    return (u*u*u*p0[0] + 3*u*u*t*c1[0] + 3*u*t*t*c2[0] + t*t*t*p1[0],
            u*u*u*p0[1] + 3*u*u*t*c1[1] + 3*u*t*t*c2[1] + t*t*t*p1[1])


def flatten(subs, scale, tol_mm=0.15):
    """Unterpfade -> Polylinien. scale = mm am Werkstueck je SVG-mm."""
    polys = []
    for sp in subs:
        pts = []
        for s in sp["seg"]:
            if not pts:
                pts.append(s[1])
            if s[0] == "L":
                pts.append(s[2])
            else:
                p0, c1, c2, p1 = s[1:]
                ctrl = (math.dist(p0, c1) + math.dist(c1, c2) + math.dist(c2, p1)) * scale
                n = max(2, min(200, int(math.ceil(ctrl / tol_mm))))
                pts += [_bez(p0, c1, c2, p1, k/n) for k in range(1, n+1)]
        # doppelte Punkte raus
        clean = [pts[0]]
        for p in pts[1:]:
            if math.dist(p, clean[-1]) * scale > 0.01:
                clean.append(p)
        if len(clean) >= 2:
            closed = sp["closed"] or (len(clean) > 2 and math.dist(clean[0], clean[-1]) * scale < 0.01)
            if closed and math.dist(clean[0], clean[-1]) * scale < 0.01:
                clean = clean[:-1]
            polys.append({"pts": clean, "closed": closed})
    return join_open(polys, 0.02 / max(scale, 1e-9))


def join_open(polys, tol):
    """Offene Stuecke, deren Enden sich treffen, zu Ketten verbinden.
    CAD-Exporte (FreeCAD-DXF) schreiben Rechtecke oft als 4 einzelne
    Linien - ohne Verbinden gaebe es keine geschlossene Kontur und damit
    keine Innen-vor-aussen-Reihenfolge."""
    closed = [p for p in polys if p["closed"]]
    offen = [list(p["pts"]) for p in polys if not p["closed"]]
    near = lambda a, b: abs(a[0]-b[0]) <= tol and abs(a[1]-b[1]) <= tol
    ketten = []
    while offen:
        k = offen.pop()
        gewachsen = True
        while gewachsen:
            gewachsen = False
            for i, s in enumerate(offen):
                if near(k[-1], s[0]):   k += s[1:]
                elif near(k[-1], s[-1]): k += s[-2::-1]
                elif near(k[0], s[-1]):  k = s[:-1] + k
                elif near(k[0], s[0]):   k = s[:0:-1] + k
                else:
                    continue
                offen.pop(i)
                gewachsen = True
                break
        zu = len(k) > 2 and near(k[0], k[-1])
        if zu:
            k = k[:-1]
        ketten.append({"pts": k, "closed": zu})
    return closed + ketten


def bbox(polys):
    xs = [p[0] for pl in polys for p in pl["pts"]]
    ys = [p[1] for pl in polys for p in pl["pts"]]
    return min(xs), min(ys), max(xs), max(ys)


def fit(polys, w_mm, h_mm, x_off=0.0, y_off=0.0):
    """Auf Zielgroesse skalieren (Seitenverhaeltnis bleibt), unten links auf Offset."""
    x0, y0, x1, y1 = bbox(polys)
    s = min(w_mm / (x1 - x0) if x1 > x0 else 1e9, h_mm / (y1 - y0) if y1 > y0 else 1e9)
    out = []
    for pl in polys:
        out.append({"pts": [((p[0]-x0)*s + x_off, (p[1]-y0)*s + y_off) for p in pl["pts"]],
                    "closed": pl["closed"]})
    return out, s


def rotate(polys, deg):
    if not deg:
        return polys
    a = math.radians(-deg); c, s = math.cos(a), math.sin(a)
    return [{"pts": [(p[0]*c - p[1]*s, p[0]*s + p[1]*c) for p in pl["pts"]],
             "closed": pl["closed"]} for pl in polys]


def _inside(pt, poly):
    x, y = pt
    ins = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i+1) % n]
        if (y1 > y) != (y2 > y) and x < (x2-x1)*(y-y1)/(y2-y1) + x1:
            ins = not ins
    return ins


def mirror(polys, achse, a):
    """Konturen spiegeln: achse 'x' = links/rechts an der Senkrechten X=a,
    achse 'y' = oben/unten an der Waagerechten Y=a."""
    out = []
    for pl in polys:
        if achse == "x":
            pts = [(2 * a - p[0], p[1]) for p in pl["pts"]]
        else:
            pts = [(p[0], 2 * a - p[1]) for p in pl["pts"]]
        out.append({"pts": pts[::-1], "closed": pl["closed"]})
    return out


def order(polys):
    """Innen vor aussen, innerhalb einer Ebene naechster Nachbar."""
    closed = [pl for pl in polys if pl["closed"]]
    for pl in polys:
        pl["tiefe"] = 0
        probe = pl["pts"][0]
        for other in closed:
            if other is not pl and len(other["pts"]) > 2 and _inside(probe, other["pts"]):
                pl["tiefe"] += 1
    rest = sorted(polys, key=lambda p: -p["tiefe"])
    out = []
    pos = (0.0, 0.0)
    for tiefe in sorted({p["tiefe"] for p in rest}, reverse=True):
        layer = [p for p in rest if p["tiefe"] == tiefe]
        while layer:
            best, bi, rev = None, 0, False
            for k, pl in enumerate(layer):
                for r, pt in ((False, pl["pts"][0]), (True, pl["pts"][-1])):
                    if r and pl["closed"]:
                        continue
                    d = math.dist(pos, pt)
                    if best is None or d < best:
                        best, bi, rev = d, k, r
            pl = layer.pop(bi)
            pts = pl["pts"][::-1] if rev else pl["pts"]
            out.append({"pts": pts, "closed": pl["closed"]})
            pos = pts[-1]
    return out


def cut_gcode(polys, s, feed, passes=1, kommentar=""):
    """Polylinien -> G-Code. Rueckgabe (zeilen, info)."""
    g = [f"; Laserwerk Schnitt {kommentar}".rstrip(),
         f"; S{s}/F{feed} = S/F {s/feed:.2f}, {passes} Durchgang/Durchgaenge",
         "; Nullpunkt = linke untere Ecke", "G21", "G90", "G94", "M4 S0"]
    cut = trav = 0.0
    segs = []
    pos = (0.0, 0.0)
    for _ in range(passes):
        for pl in polys:
            p = pl["pts"]
            trav += math.dist(pos, p[0])
            g.append(f"G0 X{p[0][0]:.3f} Y{p[0][1]:.3f}")
            for q_prev, q in zip(p, p[1:]):
                g.append(f"G1 X{q[0]:.3f} Y{q[1]:.3f} S{s} F{feed}")
                d = math.dist(q_prev, q)
                cut += d
                segs.append(d)
            if pl["closed"] and math.dist(p[-1], p[0]) > 1e-6:
                g.append(f"G1 X{p[0][0]:.3f} Y{p[0][1]:.3f} S{s} F{feed}")
                d = math.dist(p[-1], p[0]); cut += d; segs.append(d)
            g.append("G1 S0")
            pos = p[0] if pl["closed"] else p[-1]
    g += ["M5", "G0 X0 Y0"]
    from lw_job import estimate
    x0, y0, x1, y1 = bbox(polys) if polys else (0, 0, 0, 0)
    info = dict(befehle=len(g), cut_m=cut/1000, trav_m=trav/1000,
                konturen=len(polys), breite=x1 - x0, hoehe=y1 - y0,
                xmin=x0, xmax=x1,
                sekunden=estimate(segs, feed, len(polys)*passes) + trav/(1000/60))
    return g, info
