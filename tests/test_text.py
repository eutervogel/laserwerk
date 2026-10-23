"""
Zweisprachigkeit: fehlt eine Uebersetzung, oder passen die Platzhalter nicht?

Der zweite Fall ist der gefaehrliche. "{x:.1f} mm" auf Englisch versehentlich
als "{y:.1f} mm" uebersetzt faellt niemandem auf - bis die Zeile im Betrieb
mit einem KeyError abbricht, meist mitten in einer Warnung.
"""
import ast
import collections
import os
import re
import unittest

from hilfe import WURZEL                                      # noqa: F401
import lw_text


def quelldateien():
    for name in sorted(os.listdir(WURZEL)):
        if name.endswith(".py") and name != "lw_text.py":
            yield os.path.join(WURZEL, name)


def schluessel_im_code():
    """Alle Texte, die irgendwo als T("...") stehen."""
    raus = set()
    for pfad in quelldateien():
        with open(pfad) as f:
            baum = ast.parse(f.read())
        for k in ast.walk(baum):
            if (isinstance(k, ast.Call) and isinstance(k.func, ast.Name)
                    and k.func.id == "T" and k.args
                    and isinstance(k.args[0], ast.Constant)
                    and isinstance(k.args[0].value, str)):
                raus.add(k.args[0].value)
    return raus


# Texte, die Hilfsfunktionen durchreichen und deshalb nicht als T("...")
# im Quelltext stehen.
DURCHGEREICHT = {
    "Rahmen fahren", "Start", "Pause", "Weiter", "STOPP",
    "Motiv", "Material", "Maschine", "Tests",
    "Breite", "Höhe", "Materialdicke", "Fokuskorrektur", "Leistung S",
    "Leistung ab", "Vorschub F", "Zeilenabstand", "Notiz",
    "Spanne", "Schritt", "Leistungen", "Vorschübe", "Stufen", "Feldgröße",
    "Z hoch", "Z runter", "X+", "X-", "Y+", "Y-",
    "Vorderseite", "Rückseite, Wenden links/rechts",
    "Rückseite, Wenden oben/unten",
    "mm", "mm/min", "von 1000", "0 = automatisch",
}

PLATZHALTER = re.compile(r"\{([a-zA-Z_][a-zA-Z_0-9]*|\d*)[^{}]*\}")


def platzhalter(text):
    return collections.Counter(PLATZHALTER.findall(text.replace("{{", "").replace("}}", "")))


class Vollstaendig(unittest.TestCase):
    def test_jeder_text_hat_eine_uebersetzung(self):
        fehlt = sorted((schluessel_im_code() | DURCHGEREICHT) - set(lw_text.EN))
        self.assertEqual(fehlt, [], "ohne englische Fassung: %r" % (fehlt,))

    def test_keine_doppelten_schluessel(self):
        with open(os.path.join(WURZEL, "lw_text.py")) as f:
            baum = ast.parse(f.read())
        for k in baum.body:
            if isinstance(k, ast.Assign) and getattr(k.targets[0], "id", "") == "EN":
                schl = [ast.literal_eval(s) for s in k.value.keys]
                doppelt = [x for x, n in collections.Counter(schl).items() if n > 1]
                self.assertEqual(doppelt, [], "mehrfach eingetragen: %r" % (doppelt,))
                return
        self.fail("EN nicht gefunden")

    def test_durchgereichte_texte_gibt_es_wirklich(self):
        """Schutz gegen Karteileichen in der Liste oben."""
        quelle = ""
        for pfad in quelldateien():
            with open(pfad) as f:
                quelle += f.read()
        tot = [t for t in sorted(DURCHGEREICHT) if '"%s"' % t not in quelle]
        # nicht assertIn: das wuerde den ganzen Quelltext in die Meldung kippen
        self.assertEqual(tot, [], "steht nirgends mehr im Code: %r" % (tot,))


class Platzhalter(unittest.TestCase):
    def test_gleiche_platzhalter_in_beiden_sprachen(self):
        schief = []
        for de, en in lw_text.EN.items():
            if platzhalter(de) != platzhalter(en):
                schief.append((de, sorted(platzhalter(de)), sorted(platzhalter(en))))
        self.assertEqual(schief, [], "Platzhalter passen nicht: %r" % (schief,))

    def test_formatieren_klappt_in_beiden_sprachen(self):
        """Jeder Text mit Platzhaltern muss sich auch fuellen lassen."""
        for de, en in lw_text.EN.items():
            felder = platzhalter(de)
            if not felder or any(f.isdigit() or f == "" for f in felder):
                continue
            werte = {f: 1 for f in felder}
            for sprache, text in (("de", de), ("en", en)):
                try:
                    text.format(**werte)
                except Exception as e:
                    self.fail("%s: %r laesst sich nicht fuellen (%s)" % (sprache, text, e))


class Umschalten(unittest.TestCase):
    def tearDown(self):
        lw_text.setze("de")

    def test_deutsch_gibt_den_schluessel_zurueck(self):
        lw_text.setze("de")
        self.assertEqual(lw_text.T("Motiv"), "Motiv")

    def test_englisch_uebersetzt(self):
        lw_text.setze("en")
        self.assertEqual(lw_text.T("Motiv"), "Artwork")

    def test_unbekannter_text_faellt_auf_deutsch_zurueck(self):
        lw_text.setze("en")
        self.assertEqual(lw_text.T("Gibt es nicht"), "Gibt es nicht")

    def test_unbekannte_sprache_wird_deutsch(self):
        self.assertEqual(lw_text.setze("klingonisch"), "de")


if __name__ == "__main__":
    unittest.main()
