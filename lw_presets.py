"""
Material-Presets und Einstellungen, gespeichert unter ~/.config/laserwerk/.

ACHTUNG: Die Werte stammen von EINER Maschine (450 nm, 5,5 W, GRBL 1.1f).
Anderer Laser, andere Linse, anderer Fokus - andere Werte. Sie sind ein
Startpunkt fuer einen eigenen Materialtest, kein Rezept. Uebertragbar ist
das Verhaeltnis S/F, also die Energie je Millimeter; die Leistungen selbst
beziehen sich auf die Skala 0..1000 und werden beim Senden auf $30 der
angeschlossenen Maschine umgerechnet.

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
                   "accel": 30.0,
                   # Materialdicke und Fokuskorrektur ueberleben den Neustart.
                   # Die Korrektur misst der Fokustest, sie gehoert zur
                   # Maschine - sie nur in einem Preset abzulegen, das man
                   # von Hand speichern muss, heisst sie verlieren. Hier ist
                   # ihr einziger Platz; Presets fassen sie nicht mehr an.
                   "dicke": 12.0, "korrektur": 0.0}


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


def load_config():
    c = dict(CONFIG_DEFAULTS)
    c.update(_load(CONFIG, {}))
    return c


def save_config(c):
    _save(CONFIG, c)
