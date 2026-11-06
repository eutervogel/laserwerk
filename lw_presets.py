"""
Material-Presets und Einstellungen, gespeichert unter ~/.config/laserwerk/.

ACHTUNG: Die Werte stammen von EINER Maschine (450 nm, 5,5 W, GRBL 1.1f).
Anderer Laser, andere Linse, anderer Fokus - andere Werte. Sie sind ein
Startpunkt fuer einen eigenen Materialtest, kein Rezept. Uebertragbar ist
das Verhaeltnis S/F, also die Energie je Millimeter; die Leistungen selbst
beziehen sich auf die Skala 0..1000 und werden beim Senden auf $30 der
angeschlossenen Maschine umgerechnet.

An einer anderen Leistung gilt dieselbe Energie bei S/F mal 5,5/Watt: wer
diese Werte auf einen 22-W-Laser uebertraegt, braucht ein Viertel davon -
sonst verbrennt das erste Brett. Die eingetragene Leistung steht unter
"Maschine", die Energie je Millimeter neben jedem Schnitt.

Z-Logik: Die Z-Referenz wird so gesetzt, dass Z = Materialdicke im Fokus
bedeutet. Ein Preset faehrt dann auf Z = dicke + korrektur. Die Dicke bringt
es selbst mit, die Korrektur nicht: die sagt, wo die Brennebene wirklich zur
Z-Referenz liegt, und das haengt an Linse und Aufbau, nicht am Material. Sie
steht deshalb einmal in der Konfiguration und gilt fuer jedes Preset.
"""
import json, os

DIR = os.path.expanduser("~/.config/laserwerk")
PRESETS = os.path.join(DIR, "presets.json")
CONFIG = os.path.join(DIR, "config.json")
MASCHINEN = os.path.join(DIR, "maschinen.json")

# Was zur Maschine gehoert und nicht zum Benutzer. Zwei Maschinen
# abwechselnd zu betreiben heisst: diese Werte wechseln mit, der Rest
# (Aussehen, Sprache, Brettchen, Einrasten) bleibt.
#
# Die Presets gehoeren dazu, auch wenn sie in ihrer eigenen Datei stehen:
# S/F ist an EINER Leistung gemessen. Bei 22 W statt 5,5 W braucht dieselbe
# Energie ein Viertel davon - dieselbe Liste an beiden Maschinen waere eine
# Falle, die beim ersten Brett zuschlaegt.
# "kamera" ist die Eichung der Kamera im Deckel. Sie gehoert zur
# Maschine wie der Verfahrweg: die Kamera ist festgeschraubt, und beim
# Umschalten auf die andere Maschine ist sie eine andere oder keine.
MASCHINENWERTE = ("port", "x_max", "y_max", "s_max", "accel", "eilgang",
                  "kreuzung", "watt", "z_invert", "jog_feed",
                  "dicke", "korrektur", "zeitmessungen", "kamera")

# Werte aus den Laeufen vom 14.-19.9.
DEFAULTS = {
    "Holz / Schichtplatte": dict(dicke=12.0, s=830, f=1000,
        line=0.10, mode="schwelle", schwelle=0.5,
        notiz="bewaehrt fuer Schilder und Logos auf Schichtplatte"),
    "Schiefer": dict(dicke=3.0, s=830, f=1000, line=0.12,
        mode="schwelle", schwelle=0.5,
        notiz="hell auf dunkel; vorher Planlage pruefen, Staub abwischen"),
    "Wildleder": dict(dicke=2.0, s=250, f=1000, line=0.15,
        mode="schwelle", schwelle=0.5,
        notiz="aus Fokustest S150/F600; Fasern loesen ab ca. 0,3 mm auf"),
    "Papier orange (Schnitt)": dict(dicke=0.1, s=500, f=600,
        line=0.10, mode="schwelle", schwelle=0.5,
        notiz="Schnitt, nicht Gravur. Brandgefahr - daneben bleiben"),
    "Erle 3 mm (Schnitt)": dict(dicke=12.0, s=450, f=1000,
        line=0.10, mode="raster", schwelle=0.5,
        schnitt_s=725, schnitt_f=300, durchgaenge=5,
        notiz="3 mm Erle auf 9 mm Unterlage, Fokus auf der Oberflaeche. "
              "5 x S725/F300 = 3,99 J/mm. 4 x S750/F300 = 3,30 J/mm war "
              "knapp zu wenig - die Schwelle liegt dazwischen. Fokus NICHT "
              "ins Material legen, das kostet mehr als es bringt"),
    "Alu eloxiert": dict(dicke=1.0, s=300, f=600, line=0.10,
        mode="schwelle", schwelle=0.5, notiz="ungetestet - erst Fokustest"),
}

CONFIG_DEFAULTS = {"z_invert": False, "jog_feed": 1000, "port": "",
                   "x_max": 200.0, "y_max": 200.0, "theme": "dunkel",
                   "brett_x": 100.0, "brett_y": 50.0, "brett_an": True,
                   "einrasten": True, "sprache": "de",
                   # Werte der angeschlossenen Maschine. Beim ersten '$$'
                   # nach dem Verbinden ueberschreibt Laserwerk sie mit dem,
                   # was die Maschine selbst sagt ($120/$121, $110/$111, $11).
                   "accel": 30.0, "eilgang": 3000.0, "kreuzung": 0.01,
                   # Optische Leistung bei S1000. Geht in die Energie je
                   # Millimeter ein, nicht in den G-Code. Muss von Hand
                   # stimmen - die Maschine sagt ihre Leistung nicht.
                   "watt": 5.5,
                   # Materialdicke und Fokuskorrektur ueberleben den Neustart.
                   # Die Korrektur misst der Fokustest, sie gehoert zur
                   # Maschine - sie nur in einem Preset abzulegen, das man
                   # von Hand speichern muss, heisst sie verlieren. Hier ist
                   # ihr einziger Platz; Presets fassen sie nicht mehr an.
                   "dicke": 12.0, "korrektur": 0.0,
                   # Angesagte gegen gebrauchte Laufzeit der letzten Jobs.
                   # Ihr Median korrigiert das Modell - gemessen statt
                   # geglaubt, und nicht aus einem einzigen Lauf.
                   "zeitmessungen": []}


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return json.loads(json.dumps(default))


def _save(path, data):
    os.makedirs(DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def load_presets():
    p = _load(PRESETS, DEFAULTS)
    if not p:
        p = json.loads(json.dumps(DEFAULTS))
    return p


def save_presets(p):
    _save(PRESETS, p)


# Bekannte Maschinen als Startpunkt. Die Werte sind nachgelesen, nicht
# gemessen - das erste '$$' nach dem Verbinden ueberschreibt sie mit dem,
# was die Maschine selbst sagt. Die Leistung sagt keine Maschine, die bleibt.
VORLAGEN = {
    "Creality Falcon2 Pro 22 W": dict(
        x_max=400.0, y_max=415.0, s_max=1000.0, accel=500.0, eilgang=8000.0,
        kreuzung=0.01, watt=22.0, z_invert=False, jog_feed=1000,
        dicke=12.0, korrektur=0.0, zeitmessungen=[]),
}


def kopie(d):
    """Tiefe Kopie ueber JSON - die Ablage und der laufende Stand duerfen
    sich nicht dieselben Listen teilen."""
    return json.loads(json.dumps(d))


# ---------------------------------------------------------- Maschinen
# config.json und presets.json bleiben, was sie sind: der Stand der
# Maschine, mit der gerade gearbeitet wird. maschinen.json legt daneben die
# anderen ab. So liest jede aeltere Fassung von Laserwerk die Dateien
# weiter, und es gibt genau einen Ort, an dem der laufende Stand steht.


def load_maschinen():
    d = _load(MASCHINEN, {"aktiv": "", "maschinen": {}})
    if not isinstance(d, dict) or not isinstance(d.get("maschinen"), dict):
        return {"aktiv": "", "maschinen": {}}
    d.setdefault("aktiv", "")
    return d


def save_maschinen(d):
    _save(MASCHINEN, d)


def maschine_sichern(d, name, cfg, presets):
    """Den laufenden Stand unter 'name' ablegen. Gibt d zurueck."""
    if not name:
        return d
    d.setdefault("maschinen", {})[name] = {
        "werte": {k: cfg[k] for k in MASCHINENWERTE if k in cfg},
        "presets": json.loads(json.dumps(presets)),
    }
    d["aktiv"] = name
    return d


def maschine_holen(d, name):
    """(werte, presets) einer abgelegten Maschine, oder (None, None).

    Zurueck kommen Kopien: wer sie veraendert, veraendert nicht die Ablage.
    """
    m = (d.get("maschinen") or {}).get(name)
    if not m:
        return None, None
    return (dict(m.get("werte") or {}),
            json.loads(json.dumps(m.get("presets") or DEFAULTS)))


def maschine_umrechnen(presets, von_watt, nach_watt):
    """Presets auf eine andere Leistung umrechnen.

    Uebertragbar ist die Energie je Millimeter, nicht S: bei vierfacher
    Leistung braucht dieselbe Energie ein Viertel von S. Das ist ein
    Startpunkt fuer einen eigenen Materialtest, kein Rezept - deshalb steht
    es auch in der Notiz.
    """
    f = float(von_watt) / max(0.1, float(nach_watt))
    raus = {}
    for name, d in json.loads(json.dumps(presets)).items():
        for schluessel in ("s", "smin", "schnitt_s"):
            if d.get(schluessel):
                d[schluessel] = max(1, min(1000, int(round(d[schluessel] * f))))
        d["notiz"] = (("umgerechnet von %.1f W auf %.1f W, UNGETESTET. "
                       % (von_watt, nach_watt)) + (d.get("notiz") or "")).strip()
        raus[name] = d
    return raus


def load_config():
    c = dict(CONFIG_DEFAULTS)
    c.update(_load(CONFIG, {}))
    return c


def save_config(c):
    _save(CONFIG, c)
