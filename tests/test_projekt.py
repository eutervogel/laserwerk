"""Projektdateien: hin und zurueck, auch wenn die Vorlage verschwindet."""
import json
import os
import shutil
import tempfile
import unittest

from hilfe import *                                           # noqa: F401,F403
import lw_projekt as PR


class Rundlauf(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp(prefix="laserwerk-projekt-")
        self.vorlage = os.path.join(self.ordner, "motiv.svg")
        with open(self.vorlage, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="40" '
                    'height="20" viewBox="0 0 40 20"><rect width="40" '
                    'height="20" fill="none" stroke="black"/></svg>')
        self.datei = os.path.join(self.ordner, "probe.lwp")
        self.werte = {"breite": 137.5, "modus": "raster", "leistung": 173,
                      "mitten": 1.7, "spiegel": "x"}

    def tearDown(self):
        shutil.rmtree(self.ordner, ignore_errors=True)

    def test_werte_kommen_unveraendert_zurueck(self):
        PR.speichern(self.datei, self.werte, self.vorlage)
        d = PR.laden(self.datei)
        self.assertEqual(d["werte"], self.werte)

    def test_vorlage_steckt_mit_drin(self):
        PR.speichern(self.datei, self.werte, self.vorlage)
        d = PR.laden(self.datei)
        self.assertIn("vorlage", d)
        self.assertEqual(d["quelle_name"], "motiv.svg")

    def test_vorlage_ueberlebt_das_loeschen_des_originals(self):
        PR.speichern(self.datei, self.werte, self.vorlage)
        original = open(self.vorlage, "rb").read()
        os.remove(self.vorlage)
        ziel, name = PR.vorlage_auspacken(PR.laden(self.datei),
                                          os.path.join(self.ordner, "aus"))
        self.assertEqual(name, "motiv.svg")
        with open(ziel, "rb") as f:
            self.assertEqual(f.read(), original)

    def test_grosse_vorlage_wird_nur_verwiesen(self):
        alt = PR.GRENZE
        try:
            PR.GRENZE = 10
            d = PR.speichern(self.datei, self.werte, self.vorlage)
            self.assertNotIn("vorlage", d)
            self.assertTrue(d["quelle"].endswith("motiv.svg"))
            ziel, _ = PR.vorlage_auspacken(PR.laden(self.datei), self.ordner)
            self.assertEqual(ziel, self.vorlage)     # vom gemerkten Ort
        finally:
            PR.GRENZE = alt

    def test_fehlende_vorlage_meldet_sich(self):
        alt = PR.GRENZE
        try:
            PR.GRENZE = 10
            PR.speichern(self.datei, self.werte, self.vorlage)
            os.remove(self.vorlage)
            ziel, name = PR.vorlage_auspacken(PR.laden(self.datei), self.ordner)
            self.assertIsNone(ziel)
            self.assertEqual(name, "motiv.svg")
        finally:
            PR.GRENZE = alt

    def test_datei_ist_lesbares_json(self):
        PR.speichern(self.datei, self.werte, self.vorlage)
        with open(self.datei) as f:
            d = json.load(f)
        self.assertEqual(d["programm"], "Laserwerk")
        self.assertEqual(d["werte"]["leistung"], 173)

    def test_ohne_vorlage_speichern(self):
        d = PR.speichern(self.datei, self.werte, None)
        self.assertNotIn("quelle", d)
        self.assertEqual(PR.laden(self.datei)["werte"], self.werte)


class Abweisen(unittest.TestCase):
    def setUp(self):
        self.ordner = tempfile.mkdtemp(prefix="laserwerk-projekt-")

    def tearDown(self):
        shutil.rmtree(self.ordner, ignore_errors=True)

    def schreib(self, inhalt):
        p = os.path.join(self.ordner, "x.lwp")
        with open(p, "w") as f:
            json.dump(inhalt, f)
        return p

    def test_fremde_datei(self):
        with self.assertRaises(ValueError):
            PR.laden(self.schreib({"programm": "Lightburn"}))

    def test_neuere_fassung(self):
        with self.assertRaises(ValueError):
            PR.laden(self.schreib({"programm": "Laserwerk", "format": 99,
                                   "werte": {}}))

    def test_kein_json(self):
        p = os.path.join(self.ordner, "y.lwp")
        with open(p, "w") as f:
            f.write("nicht json")
        with self.assertRaises(Exception):
            PR.laden(p)


if __name__ == "__main__":
    unittest.main()
