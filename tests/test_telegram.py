"""
Fernsteuerung: Menue, Steuerkreuz und Befehlsauswertung.

Geprueft wird vor allem, dass die drei zusammenpassen. Ein Knopf, dessen
callback_data niemand auswertet, antwortet am Handy mit "Kenne ich nicht" -
und das merkt man am Werkstueck, mit dem Handy in der Hand.

Hier geht nichts ins Netz: Fern wird gebaut, aber nie gestartet.
"""
import queue
import unittest

from hilfe import WURZEL, Attrappe                             # noqa: F401
import lw_telegram as TG

# Was _knopf selbst erledigt, ohne bei der Oberflaeche nachzufragen.
EIGEN = {"schritt"}


class Stummel:
    """Gerade so viel Laserwerk, wie die Fernsteuerung anfasst. Spart den
    ganzen Fensteraufbau - diese Tests brauchen keinen Bildschirm."""

    def __init__(self):
        self.grbl = Attrappe()
        self.cfg = {"z_invert": False, "jog_feed": 1000}
        self.q = queue.Queue()


class Grundlage(unittest.TestCase):
    def setUp(self):
        self.app = Stummel()
        self.fern = TG.Fern(self.app)
        self.getan = []
        self.fern._tun = lambda a: (self.getan.append(a), "ok")[1]
        self.fern._pad_neu = lambda: None
        self.fern._fahren = lambda a, mm: "gefahren"

    def sagen(self, text):
        """Einen Befehl auswerten und zurueckgeben, was ans Handy ginge."""
        self.fern.raus = queue.Queue()
        self.fern._befehl(text)
        raus = []
        while not self.fern.raus.empty():
            raus.append(self.fern.raus.get())
        return "\n".join(raus)


class Menue(Grundlage):
    def test_jeder_menuepunkt_wird_verstanden(self):
        for befehl, _ in TG.MENUE:
            antwort = self.sagen("/" + befehl)
            self.assertNotIn("Kenne ich nicht", antwort,
                             "/%s steht im Menue, wird aber nicht erkannt"
                             % befehl)

    def test_jeder_menuepunkt_hat_eine_beschreibung(self):
        for befehl, text in TG.MENUE:
            self.assertTrue(text.strip(), befehl)
            # Telegram verlangt 1..256 Zeichen und kleine Befehlsnamen
            self.assertLessEqual(len(text), 256, befehl)
            self.assertEqual(befehl, befehl.lower())
            self.assertTrue(befehl.isalpha(), befehl)

    def test_pause_und_weiter_stehen_drin(self):
        drin = {b for b, _ in TG.MENUE}
        self.assertIn("pause", drin)
        self.assertIn("weiter", drin)

    def test_hilfe_nennt_jeden_menuepunkt(self):
        h = TG.hilfe()
        for befehl, _ in TG.MENUE:
            if befehl == "hilfe":
                continue
            self.assertIn("/" + befehl, h, befehl)


class Befehle(Grundlage):
    def test_pause_geht_an_die_oberflaeche(self):
        self.sagen("/pause")
        self.assertEqual(self.getan, ["pause"])

    def test_weiter_geht_an_die_oberflaeche(self):
        self.sagen("/weiter")
        self.assertEqual(self.getan, ["weiter"])

    def test_nullzurueck_geht_an_die_oberflaeche(self):
        self.sagen("/nullzurueck")
        self.assertEqual(self.getan, ["nullzurueck"])

    def test_frei_geht_an_die_oberflaeche(self):
        self.sagen("/frei")
        self.assertEqual(self.getan, ["frei"])

    def test_unbekanntes_bleibt_unbekannt(self):
        self.assertIn("Kenne ich nicht", self.sagen("/fraesen"))
        self.assertEqual(self.getan, [])

    def test_mit_botnamen_dahinter(self):
        """In Gruppen haengt Telegram '@botname' an den Befehl."""
        self.sagen("/pause@gerndorf_laser_bot")
        self.assertEqual(self.getan, ["pause"])


class Steuerkreuz(Grundlage):
    def knoepfe(self):
        return [k["callback_data"] for reihe in self.fern._tastatur()["inline_keyboard"]
                for k in reihe]

    def test_ohne_job_steht_das_steuerkreuz_da(self):
        self.app.grbl.job_running = False
        k = self.knoepfe()
        self.assertIn("x+", k)
        self.assertIn("schritt", k)
        self.assertNotIn("pause", k)

    def test_waehrend_eines_jobs_stehen_die_jobknoepfe_da(self):
        """Fahrbefehle sind waehrend eines Jobs ohnehin gesperrt - ein
        Steuerkreuz, das auf jeden Druck 'Es laeuft ein Job' antwortet,
        ist schlimmer als keines."""
        self.app.grbl.job_running = True
        k = self.knoepfe()
        self.assertIn("pause", k)
        self.assertIn("weiter", k)
        self.assertIn("stopp", k)
        self.assertNotIn("x+", k)
        self.assertNotIn("y-", k)

    def test_stopp_ist_immer_erreichbar(self):
        for laeuft in (False, True):
            self.app.grbl.job_running = laeuft
            self.assertIn("stopp", self.knoepfe())
            self.assertIn("aus", self.knoepfe())

    def test_jeder_knopf_hat_eine_beschriftung(self):
        for laeuft in (False, True):
            self.app.grbl.job_running = laeuft
            for d in self.knoepfe():
                self.assertNotEqual(self.fern._etikett(d), d,
                                    "Knopf %r ohne Etikett" % d)

    def test_jeder_knopf_wird_ausgewertet(self):
        for laeuft in (False, True):
            self.app.grbl.job_running = laeuft
            for d in self.knoepfe():
                self.getan = []
                self.fern._knopf(d)
                if d in EIGEN or (len(d) == 2 and d[0] in "xyz"):
                    continue
                self.assertEqual(self.getan, [d], "Knopf %r landet nirgends" % d)


class NichtsGehtInsNetz(unittest.TestCase):
    def test_bauen_startet_nichts(self):
        fern = TG.Fern(Stummel())
        self.assertFalse(fern.aktiv)
        self.assertEqual(fern.leitungen, {})


if __name__ == "__main__":
    unittest.main()
