"""
Projektdateien (.lwp): Motiv und alle Einstellungen in einer Datei.

Eine Projektdatei ist lesbares JSON. Die Vorlage steckt als base64 mit
drin, damit das Projekt auch dann noch aufgeht, wenn die Bilddatei
inzwischen verschoben oder geloescht wurde - ein Projekt, das nur einen
Pfad merkt, ist in einem halben Jahr wertlos.

Der urspruengliche Pfad wird trotzdem mitgeschrieben, als Hinweis fuer
Menschen. Ist die Vorlage groesser als GRENZE, wird nur der Pfad
gespeichert und beim Oeffnen von dort gelesen.
"""
import base64, json, os, time

ENDUNG = ".lwp"
FORMAT = 1
GRENZE = 12 * 1024 * 1024        # groesser wird nicht eingebettet


def _einbetten(d, quelle):
    """Vorlage als base64 hineinlegen, solange sie nicht zu gross ist."""
    if not (quelle and os.path.exists(quelle)):
        return d
    d["quelle"] = os.path.abspath(quelle)
    d["quelle_name"] = os.path.basename(quelle)
    if os.path.getsize(quelle) <= GRENZE:
        with open(quelle, "rb") as f:
            d["vorlage"] = base64.b64encode(f.read()).decode()
    return d


def speichern(pfad, werte, quelle=None, elemente=None):
    """werte: Einstellungen des Projekts.
    elemente: Liste aus {anzeige, quelle, werte} - jedes mit eigener Vorlage.
    quelle: einzelne Vorlage (alte Form, wenn es nur ein Motiv gab)."""
    d = {"format": FORMAT, "programm": "Laserwerk",
         "gespeichert": time.strftime("%Y-%m-%d %H:%M"),
         "werte": werte}
    if elemente is not None:
        d["elemente"] = [_einbetten(dict(e), e.get("quelle")) for e in elemente]
    elif quelle:
        _einbetten(d, quelle)
    with open(pfad, "w") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    return d


def laden(pfad):
    with open(pfad) as f:
        d = json.load(f)
    if d.get("programm") != "Laserwerk":
        raise ValueError("Keine Laserwerk-Projektdatei.")
    if d.get("format", 0) > FORMAT:
        raise ValueError("Die Datei stammt aus einer neueren Fassung.")
    return d


def vorlage_auspacken(d, ordner, nr=None):
    """Eingebettete Vorlage in einen Ordner schreiben und den Pfad liefern.
    Ohne Einbettung den gemerkten Pfad zurueckgeben, falls es ihn noch gibt.
    'nr' haelt gleichnamige Vorlagen mehrerer Elemente auseinander."""
    name = d.get("quelle_name") or "vorlage"
    if d.get("vorlage"):
        os.makedirs(ordner, exist_ok=True)
        ziel = os.path.join(ordner,
                            name if nr is None else "%d-%s" % (nr, name))
        with open(ziel, "wb") as f:
            f.write(base64.b64decode(d["vorlage"]))
        return ziel, name
    q = d.get("quelle")
    if q and os.path.exists(q):
        return q, os.path.basename(q)
    return None, name
