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


class Strom(G.Grbl):
    """Grbl ohne Port: jede gesendete Zeile wird sofort quittiert.

    'pause_bei' meldet mitten im Strom eine Pause an; auf die Meldung
    'pausiert' wird gleich wieder fortgesetzt, sonst stuende der Test.
    """

    def __init__(self, fehler_bei=(), pause_bei=None):
        self.ereignisse = []
        self.gesendet = []
        self.bei_pause = None
        self.fehler_bei = set(fehler_bei)
        self.pause_bei = pause_bei
        self.nr = 0
        super().__init__(self._ereignis)
        self.alive = True

    def _ereignis(self, art, daten):
        self.ereignisse.append((art, daten))
        if art == "pausiert":
            self.bei_pause = list(self.gesendet)
            self.resume()

    def write(self, data):
        for zeile in data.decode().splitlines():
            self.gesendet.append(zeile)
            self.oks.put("error:1" if self.nr in self.fehler_bei else "ok")
            self.nr += 1
            if self.nr == self.pause_bei:
                self.pause_am_zeilenende()

    def wait_idle(self, timeout=120.0):
        return True


class Referenzfahrt(unittest.TestCase):
    def test_h_wird_gesendet_und_quittiert(self):
        g = Strom()
        self.assertEqual(g.home(), "ok")
        self.assertEqual(g.gesendet, ["$H"])

    def test_die_fahrt_bekommt_mehr_zeit_als_ein_befehl(self):
        """Zehn Sekunden reichen nicht: GRBL quittiert erst, wenn der Kopf
        steht, und bis dahin faehrt er zweimal ueber das ganze Bett."""
        g = Strom()
        gemerkt = {}
        g.cmd = lambda zeile, timeout=10.0: (
            gemerkt.update(zeile=zeile, timeout=timeout) or "ok")
        g.home()
        self.assertEqual(gemerkt["zeile"], "$H")
        self.assertGreaterEqual(gemerkt["timeout"], 60)

    def test_ein_alarm_ist_danach_vom_tisch(self):
        g = Strom()
        g.alarm = "ALARM:9"
        g.home()
        self.assertIsNone(g.alarm)


ZEILEN = ["G1 X%07.3f Y%07.3f S500" % (i, i) for i in range(40)]
MARKEN = [0, 8, 16, 24, 32]


class Streamen(unittest.TestCase):
    def test_alles_kommt_an(self):
        g = Strom()
        self.assertEqual(g.run_job(ZEILEN, lambda *a: None), "fertig")
        self.assertEqual(g.gesendet, ZEILEN)
        self.assertEqual(g.job_done, len(ZEILEN))

    def test_fehler_werden_gezaehlt(self):
        """Nach dem Job ist die Fehlerzahl die einzige Spur, die eine
        ausgelassene Zeile im Werkstueck noch erklaeren koennte."""
        g = Strom(fehler_bei=(3, 17))
        g.run_job(ZEILEN, lambda *a: None)
        self.assertEqual(g.job_errors, 2)

    def test_ohne_fehler_steht_null(self):
        g = Strom()
        g.run_job(ZEILEN, lambda *a: None)
        self.assertEqual(g.job_errors, 0)


class PauseAmZeilenende(unittest.TestCase):
    """Ein Feed Hold bremst mitten in der Zeile ab - die Spur liegt im
    Motiv. Am Zeilenende steht der Kopf im Anlauf daneben."""

    def setUp(self):
        self.g = Strom(pause_bei=10)
        self.g.run_job(ZEILEN, lambda *a: None, marken=MARKEN)
        self.job = [z for z in self.g.gesendet if z.startswith("G1")]

    def test_haelt_an_einer_marke(self):
        vorher = [z for z in self.g.bei_pause if z.startswith("G1")]
        self.assertIn(len(vorher), MARKEN)

    def test_laser_aus_waehrend_der_pause(self):
        self.assertEqual(self.g.bei_pause[-1], "M5")

    def test_danach_wieder_im_selben_modus(self):
        """Nach dem M5 muss genau der Modus wieder gelten, in dem der Job
        laeuft - sonst brennt der Rest mit konstanter Leistung."""
        i = self.g.gesendet.index("M5")
        self.assertEqual(self.g.gesendet[i + 1], "M4")

    def test_keine_zeile_geht_verloren(self):
        self.assertEqual(self.job, ZEILEN)

    def test_der_job_laeuft_zu_ende(self):
        self.assertEqual(self.g.job_done, len(ZEILEN))

    def test_kein_feed_hold(self):
        """'!' wuerde genau die Delle bremsen, die vermieden werden soll."""
        self.assertNotIn("realtime", [a for a, _ in self.g.ereignisse])
        self.assertNotIn("!", self.g.gesendet)

    def test_meldet_anhalten_und_weiterfahren(self):
        self.assertEqual([a for a, _ in self.g.ereignisse],
                         ["pausiert", "weiter"])


class AbbruchInDerPause(unittest.TestCase):
    """STOPP waehrend der Pause darf nicht im Wartelauf haengen bleiben."""

    class Abbrecher(Strom):
        def _ereignis(self, art, daten):
            self.ereignisse.append((art, daten))
            if art == "pausiert":
                self._stop = True

    def test_bricht_ab(self):
        g = self.Abbrecher(pause_bei=10)
        self.assertEqual(g.run_job(ZEILEN, lambda *a: None, marken=MARKEN),
                         "abgebrochen")
        self.assertLess(len([z for z in g.gesendet if z.startswith("G1")]),
                        len(ZEILEN))


class Marken(unittest.TestCase):
    def test_naechste_marke(self):
        self.assertEqual(G.Grbl._naechste_marke([0, 8, 16], 5), 8)

    def test_marke_genau_davor(self):
        self.assertEqual(G.Grbl._naechste_marke([0, 8, 16], 8), 16)

    def test_ohne_marke_dahinter_sofort(self):
        """Keine Marke mehr vor uns: anhalten, sobald der Puffer leer ist -
        auch das haelt kontrolliert an, nur eben nicht am Zeilenende."""
        self.assertEqual(G.Grbl._naechste_marke([0, 8], 12), 12)

    def test_ganz_ohne_marken(self):
        self.assertEqual(G.Grbl._naechste_marke(None, 7), 7)

    def test_modus_m4(self):
        self.assertEqual(G.Grbl._laser_modus(["M4 S0", "G1 X1"], 2), "M4")

    def test_modus_m3(self):
        self.assertEqual(G.Grbl._laser_modus(["M3 S300", "G1 X1"], 2), "M3")

    def test_modus_kommentar_zaehlt_nicht(self):
        self.assertEqual(G.Grbl._laser_modus(["M4 S0", "; M3 waere falsch"], 2),
                         "M4")


if __name__ == "__main__":
    unittest.main()


class EineVerloreneQuittungHaeltDenJobNichtAn(unittest.TestCase):
    """Ein Byte auf der Leitung darf keinen Job toeten.

    Der Sendefaden hat bis zu 127 Bytes unterwegs und darf erst
    nachschicken, wenn eine Quittung zurueckkommt. Bleibt eine aus,
    wartete er frueher endlos: der Job stand, die Maschine lief ihren
    Puffer leer und meldete Idle, und Laserwerk hielt den Job weiter fuer
    laufend. Gesehen am 6.11.2026 mitten in einer Gravur mit 2,3
    Millionen Zeilen.
    """

    class Leitung:
        """Eine Verbindung, die genau eine Quittung verschluckt."""

        def __init__(self, verliere_bei=5):
            self.verliere_bei = verliere_bei
            self.gesendet = []
            self.quittiert = 0

        def schreibe(self, g, zeile):
            self.gesendet.append(zeile)
            self.quittiert += 1
            if self.quittiert == self.verliere_bei:
                return            # diese eine kommt nie an
            g.oks.put("ok")

    def bauen(self, verliere_bei=5):
        import lw_grbl as G
        g = G.Grbl(lambda *a: None)
        g.alive = True
        g.s = object()
        g.STILL_SEKUNDEN = 0.05          # im Test nicht drei Sekunden warten
        g.status = {"state": "Idle", "bf": (15, 127), "mpos": (0, 0, 0),
                    "wco": (0, 0, 0), "wpos": (0, 0, 0), "fs": (0, 0)}
        leitung = self.Leitung(verliere_bei)
        g.write = lambda daten: leitung.schreibe(g, daten.decode().strip())
        return g, leitung

    def test_der_job_laeuft_trotzdem_zu_ende(self):
        g, leitung = self.bauen(verliere_bei=5)
        zeilen = ["G1 X%d" % i for i in range(40)]
        erg = g.run_job(zeilen, lambda *a: None)
        self.assertEqual(erg, "fertig")
        self.assertEqual(leitung.gesendet, zeilen)
        self.assertGreaterEqual(g.job_resyncs, 1)

    def test_ohne_verlust_wird_nicht_aufgesetzt(self):
        g, leitung = self.bauen(verliere_bei=10**9)
        erg = g.run_job(["G1 X%d" % i for i in range(40)], lambda *a: None)
        self.assertEqual(erg, "fertig")
        self.assertEqual(g.job_resyncs, 0)

    def test_waehrend_sie_faehrt_wird_gewartet(self):
        """Run heisst arbeiten, nicht haengen - da darf nichts aufgesetzt
        werden."""
        g, _ = self.bauen()
        g.status["state"] = "Run"
        self.assertFalse(g._strom_steht(sent=10, done=5))

    def test_voller_planer_zaehlt_als_arbeitend(self):
        g, _ = self.bauen()
        g.status["bf"] = (0, 127)        # kein freier Planerblock
        self.assertFalse(g._strom_steht(sent=10, done=5))

    def test_ohne_ausstand_nichts_zu_tun(self):
        g, _ = self.bauen()
        self.assertFalse(g._strom_steht(sent=5, done=5))
