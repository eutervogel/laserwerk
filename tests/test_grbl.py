"""Statusberichte und Einstellungen des Controllers auswerten.

Hier sitzt der Fehler, der im Betrieb am teuersten war: Ein Bericht mit
einem nicht numerischen Feld (A:C bei laufendem Laser) hat den Lesethread
umgebracht, und der Job blieb bei 0,5 Prozent stehen.
"""
import queue
import unittest

from hilfe import *                                           # noqa: F401,F403
import lw_grbl as G


class Leser(G.Grbl):
    """Grbl ohne seriellen Port: nur die Auswertung."""

    def __init__(self):
        self.ereignisse = []
        super().__init__(lambda art, daten: self.ereignisse.append((art, daten)))


class Status(unittest.TestCase):
    def setUp(self):
        self.g = Leser()

    def test_einfacher_bericht(self):
        self.g._handle("<Idle|MPos:10.000,20.000,5.000|FS:0,0>")
        self.assertEqual(self.g.status["state"], "Idle")
        self.assertEqual(self.g.status["mpos"], (10.0, 20.0, 5.0))

    def test_wpos_ist_mpos_minus_wco(self):
        self.g._handle("<Idle|MPos:50.000,40.000,0.000|WCO:10.000,5.000,0.000>")
        self.assertEqual(self.g.status["wpos"], (40.0, 35.0, 0.0))

    def test_wco_gilt_weiter_wenn_es_nicht_mitkommt(self):
        self.g._handle("<Idle|MPos:50.000,40.000,0.000|WCO:10.000,5.000,0.000>")
        self.g._handle("<Run|MPos:60.000,40.000,0.000|FS:1000,830>")
        self.assertEqual(self.g.status["wpos"], (50.0, 35.0, 0.0))

    def test_zubehoerfeld_bringt_nichts_um(self):
        """A:C ist nicht numerisch - frueher starb daran der Lesethread."""
        self.g._handle("<Run|MPos:1.000,2.000,3.000|FS:1000,830|A:C>")
        self.assertEqual(self.g.status["state"], "Run")
        self.assertEqual(self.g.status["mpos"], (1.0, 2.0, 3.0))

    def test_pinfeld_bringt_nichts_um(self):
        self.g._handle("<Idle|MPos:0.000,0.000,0.000|Pn:XYZ>")
        self.assertEqual(self.g.status["state"], "Idle")

    def test_unbekannte_zeile_wird_gemeldet_statt_zu_werfen(self):
        self.g._handle("irgendwas Unerwartetes")
        self.assertIn("msg", [a for a, _ in self.g.ereignisse])

    def test_vorschub_und_leistung(self):
        self.g._handle("<Run|MPos:0.000,0.000,0.000|FS:980,830>")
        self.assertEqual(self.g.status["fs"], (980.0, 830.0))


class Quittungen(unittest.TestCase):
    def setUp(self):
        self.g = Leser()

    def test_ok_landet_in_der_schlange(self):
        self.g._handle("ok")
        self.assertEqual(self.g.oks.get_nowait(), "ok")

    def test_fehler_landet_ebenfalls_in_der_schlange(self):
        self.g._handle("error:24")
        self.assertEqual(self.g.oks.get_nowait(), "error:24")

    def test_alarm_wird_gemeldet(self):
        self.g._handle("ALARM:2")
        self.assertEqual(self.g.alarm, "ALARM:2")
        self.assertIn(("alarm", "ALARM:2"), self.g.ereignisse)

    def test_neustart_verwirft_den_versatz(self):
        self.g.status["wco"] = (10.0, 10.0, 0.0)
        self.g._handle("Grbl 1.1f ['$' for help]")
        self.assertEqual(self.g.status["wco"], (0, 0, 0))
        self.assertEqual(self.g.reset_seen, 1)
        self.assertIn("reset", [a for a, _ in self.g.ereignisse])


class Einstellungen(unittest.TestCase):
    def setUp(self):
        self.g = Leser()

    def test_dollarzeilen_werden_gesammelt(self):
        for z in ("$30=1000.000", "$32=1", "$130=200.000"):
            self.g._handle(z)
        self.assertEqual(self.g.settings["30"], 1000.0)
        self.assertEqual(self.g.settings["32"], 1.0)
        self.assertEqual(self.g.settings["130"], 200.0)

    def test_krumme_dollarzeile_stoert_nicht(self):
        self.g._handle("$30=viel")
        self.assertNotIn("30", self.g.settings)


if __name__ == "__main__":
    unittest.main()
