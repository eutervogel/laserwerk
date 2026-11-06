"""
Kein Testlauf fasst die Konfiguration des Benutzers an.

Das ist keine Formfrage. In ~/.config/laserwerk stehen die Maschine und die
Presets, mit denen gearbeitet wird - Werte, die an echtem Material gemessen
wurden und sich nicht aus dem Quelltext wiederherstellen lassen.

hilfe.py biegt die Pfade auf ein Wegwerfverzeichnis um. Einmal waren sie
dort namentlich aufgezaehlt, und maschinen.json kam spaeter dazu, ohne in
die Aufzaehlung zu geraten. Gemerkt hat es niemand, weil kein Test
fehlschlug: Der Schaden stand in der Konfiguration. Dieser Test sieht
nach, statt sich darauf zu verlassen, dass jemand daran denkt.
"""
import os
import unittest

import hilfe                                                   # noqa: F401
import lw_presets as P
import lw_telegram as TG

ECHT = os.path.expanduser("~/.config/laserwerk")


class KeinTestSchreibtInsEchteVerzeichnis(unittest.TestCase):

    def pfade(self, modul):
        """Alle Zeichenketten des Moduls, die nach einem Pfad aussehen."""
        return [(n, getattr(modul, n)) for n in dir(modul)
                if not n.startswith("_")
                and isinstance(getattr(modul, n), str)
                and getattr(modul, n).startswith("/")]

    def test_presets_zeigen_ins_wegwerfverzeichnis(self):
        draussen = [(n, w) for n, w in self.pfade(P)
                    if os.path.commonpath([w, ECHT]) == ECHT]
        self.assertEqual(draussen, [], "lw_presets zeigt noch auf %s" % ECHT)

    def test_auch_die_spaeter_dazugekommenen(self):
        """Namentlich, damit das Umbiegen nicht leise ins Leere laeuft."""
        for name in ("DIR", "CONFIG", "PRESETS", "MASCHINEN"):
            self.assertTrue(
                getattr(P, name).startswith(hilfe.WEGWERF),
                "%s zeigt auf %s" % (name, getattr(P, name)))

    def test_telegram_auch(self):
        self.assertTrue(TG.DATEI.startswith(hilfe.WEGWERF))


if __name__ == "__main__":
    unittest.main()
