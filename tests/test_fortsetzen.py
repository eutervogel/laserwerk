"""
Den Stopp-Punkt einer haengengebliebenen Datei wiederfinden.

Hier wird nichts gesendet und kein Port geoeffnet - geprueft wird nur die
Rechnung, die entscheidet, ab welcher Zeile es weitergeht. Genau die muss
stimmen: trifft sie daneben, faehrt die Maschine mitten ins Werkstueck.
"""
import unittest

from hilfe import *                                           # noqa: F401,F403
import fortsetzen as F


GRAVUR = ["G21", "G90", "G94", "M4 S0",
          "G0 X0.000 Y0.000",
          "G1 X40.000 Y0.000 S500 F1000",
          "G1 X40.000 Y0.150",
          "G1 X0.000 Y0.150",
          "G1 X0.000 Y0.300",
          "G1 X40.000 Y0.300"]

# Zwei Zustellungen uebereinander - dieselben X/Y, nur tiefer.
TASCHE = ["G21", "G90", "G94",
          "G0 Z5.000",
          "G0 X10.000 Y10.000",
          "G1 Z-1.000 F200",
          "G1 X50.000 F600",
          "G1 Y40.000",
          "G1 X10.000",
          "G1 Y10.000",
          "G0 Z5.000",
          "G0 X10.000 Y10.000",
          "G1 Z-2.000 F200",
          "G1 X50.000 F600",
          "G1 Y40.000",
          "G1 X10.000",
          "G1 Y10.000",
          "G0 Z5.000"]


def treffer(lines, wpos):
    """Dasselbe Suchkriterium wie main(), ohne Port und Ausgabe."""
    ep = F.endpunkte(lines)
    mit_z = F.hat_z(lines)
    return [i for i, (x, y, z, f, bew) in enumerate(ep)
            if bew and abs(x - wpos[0]) <= F.TOL and abs(y - wpos[1]) <= F.TOL
            and (not mit_z or abs(z - wpos[2]) <= F.TOL)]


class Endpunkte(unittest.TestCase):
    def test_koordinaten_bleiben_stehen(self):
        """G90: eine Zeile ohne Y behaelt das alte Y."""
        ep = F.endpunkte(["G0 X10.000 Y20.000", "G1 X30.000 F600"])
        self.assertEqual(ep[-1][:3], (30.0, 20.0, 0.0))

    def test_zeilen_ohne_bewegung_sind_keine_kandidaten(self):
        ep = F.endpunkte(["G21", "G90", "M4 S0", "G0 X5.000 Y5.000"])
        self.assertEqual([e[4] for e in ep], [False, False, False, True])

    def test_vorschub_wird_mitgefuehrt(self):
        ep = F.endpunkte(["G1 X1.000 F600", "G1 X2.000", "G1 X3.000 F200"])
        self.assertEqual([e[3] for e in ep], [600.0, 600.0, 200.0])

    def test_z_wird_mitgefuehrt(self):
        ep = F.endpunkte(TASCHE)
        self.assertEqual(ep[6][2], -1.0)        # erste Zustellung
        self.assertEqual(ep[13][2], -2.0)       # zweite Zustellung

    def test_eine_reine_z_fahrt_zaehlt_als_bewegung(self):
        ep = F.endpunkte(["G0 Z5.000"])
        self.assertTrue(ep[0][4])


class StelleFinden(unittest.TestCase):
    def test_gravur_eindeutig(self):
        self.assertEqual(treffer(GRAVUR, (40.0, 0.150, 0.0)), [6])

    def test_fokushoehe_stoert_die_gravur_nicht(self):
        """Eine Lasergravur fasst Z nie an - der Kopf steht auf der
        Fokushoehe, und die darf den Abgleich nicht kaputtmachen."""
        self.assertEqual(treffer(GRAVUR, (40.0, 0.150, 12.4)), [6])

    def test_daneben_findet_nichts(self):
        self.assertEqual(treffer(GRAVUR, (40.0, 0.2, 0.0)), [])

    def test_toleranz_deckt_rundung_ab(self):
        self.assertEqual(treffer(GRAVUR, (40.0, 0.1549, 0.0)), [6])

    def test_zweite_zustellung_ist_mit_z_eindeutig(self):
        self.assertEqual(treffer(TASCHE, (50.0, 10.0, -2.0)), [13])

    def test_erste_zustellung_ist_mit_z_eindeutig(self):
        self.assertEqual(treffer(TASCHE, (50.0, 10.0, -1.0)), [6])

    def test_ohne_z_waere_die_tasche_mehrdeutig(self):
        """Der Grund fuer den Z-Abgleich: ohne Tiefe passen zwei Stellen,
        und das Skript haette abgebrochen statt fortzusetzen."""
        ep = F.endpunkte(TASCHE)
        ohne = [i for i, (x, y, z, f, bew) in enumerate(ep)
                if bew and abs(x - 50.0) <= F.TOL and abs(y - 10.0) <= F.TOL]
        self.assertEqual(len(ohne), 2)
        self.assertEqual(len(treffer(TASCHE, (50.0, 10.0, -2.0))), 1)

    def test_falsche_tiefe_findet_nichts(self):
        """Lieber nichts finden als in der falschen Lage weiterfraesen."""
        self.assertEqual(treffer(TASCHE, (50.0, 10.0, -1.5)), [])


class Resttext(unittest.TestCase):
    def test_hat_z_erkennt_die_zustellung(self):
        self.assertTrue(F.hat_z(TASCHE))
        self.assertFalse(F.hat_z(GRAVUR))

    def test_vorschub_der_stelle_wird_rueckwaerts_gesucht(self):
        ep = F.endpunkte(TASCHE)
        idx = treffer(TASCHE, (10.0, 40.0, -2.0))[0]
        feed = next((ep[i][3] for i in range(idx, -1, -1) if ep[i][3]), 1000.0)
        self.assertEqual(feed, 600.0)           # nicht die 200 der Zustellung


if __name__ == "__main__":
    unittest.main()
