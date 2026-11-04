"""
Trockenlauf: einen G-Code deuten, ohne dass sich etwas bewegt.

Geprueft wird vor allem, dass er findet, was im Betrieb wehtut - ein
stehender brennender Strahl, ein Befehl, den GRBL ueberspringt, eine
Koordinate hinter dem Verfahrweg. Ein Pruefwerkzeug, das nichts findet,
ist schlimmer als keines: man verlaesst sich darauf.
"""
import os
import tempfile
import unittest

from hilfe import WURZEL                                      # noqa: F401
import trockenlauf as TL


def lauf(text, **k):
    """G-Code aus einer Zeichenkette durchrechnen."""
    p = os.path.join(tempfile.mkdtemp(), "t.nc")
    with open(p, "w") as f:
        f.write(text)
    bei = k.pop("bei", None)
    l = TL.Lauf(**k)
    halt = TL.lies(p, l, bei)
    l.pfad, l.halt = p, halt
    return l


def arten(l):
    return {b.art for b in l.befunde}


SAUBER = """; Laserwerk Test
G21
G90
G94
M4 S0
G0 X10.000 Y10.000
G1 X50.000 S450 F1000
G1 X10.000 S450 F1000
G1 S0
M5
G0 X0 Y0
"""


class SauberDurch(unittest.TestCase):
    def setUp(self):
        self.l = lauf(SAUBER)

    def test_keine_befunde(self):
        self.assertEqual(self.l.befunde, [])

    def test_weg_wird_gezaehlt(self):
        # zweimal 40 mm brennend, die Anfahrt zaehlt nicht mit
        self.assertAlmostEqual(self.l.brennweg, 80.0, places=6)

    def test_endposition(self):
        self.assertAlmostEqual(self.l.x, 0.0, places=6)
        self.assertAlmostEqual(self.l.y, 0.0, places=6)
        self.assertEqual(self.l.spindel, "M5")

    def test_spanne(self):
        self.assertAlmostEqual(max(self.l.xs), 50.0, places=6)
        self.assertAlmostEqual(min(self.l.xs), 0.0, places=6)


class StrahlUndBewegung(unittest.TestCase):
    """Wann brennt es wirklich? Daran haengt jede andere Zahl."""

    def test_m4_im_stillstand_brennt_nicht(self):
        l = lauf("G90\nM4 S900 F300\nG1 X10\nG1 X10\n")
        self.assertNotIn("steht", arten(l))

    def test_m3_im_stillstand_brennt(self):
        l = lauf("G90\nM3 S900 F300\nG1 X10\nG1 X10\n")
        self.assertIn("steht", arten(l))

    def test_g0_brennt_im_lasermodus_nicht(self):
        l = lauf("G90\nM3 S900 F300\nG1 X10\nG0 X100\n")
        self.assertAlmostEqual(l.brennweg, 10.0, places=6)

    def test_ohne_lasermodus_brennt_g0_mit(self):
        """$32=0: der Strahl bleibt waehrend der Eilfahrt an. Genau dafuer
        warnt Laserwerk beim Verbinden."""
        l = lauf("G90\nM3 S900 F300\nG1 X10\nG0 X100\n", lasermodus=False)
        self.assertAlmostEqual(l.brennweg, 100.0, places=6)

    def test_nach_m5_brennt_nichts(self):
        l = lauf("G90\nM4 S900 F300\nG1 X10\nM5\nG1 X50\n")
        self.assertAlmostEqual(l.brennweg, 10.0, places=6)

    def test_s0_brennt_nicht(self):
        l = lauf("G90\nM4 S0 F300\nG1 X10\n")
        self.assertAlmostEqual(l.brennweg, 0.0, places=6)
        self.assertAlmostEqual(l.leerweg, 10.0, places=6)

    def test_wartezeit_unter_m3(self):
        l = lauf("G90\nM3 S900 F300\nG1 X10\nG4 P4\n")
        self.assertIn("wartet_mit_strahl", arten(l))
        self.assertGreaterEqual(l.sekunden, 4.0)

    def test_wartezeit_unter_m4_ist_harmlos(self):
        l = lauf("G90\nM4 S900 F300\nG1 X10\nG4 P4\n")
        self.assertNotIn("wartet_mit_strahl", arten(l))


class Grenzen(unittest.TestCase):
    def test_ueber_den_verfahrweg(self):
        l = lauf("G90\nM4 S450 F1000\nG1 X310\n", x_max=295.0)
        self.assertIn("ausserhalb", arten(l))

    def test_hinter_den_nullpunkt(self):
        l = lauf("G90\nM4 S450 F1000\nG1 X-5\n")
        self.assertIn("negativ", arten(l))

    def test_knapp_drinnen_ist_kein_befund(self):
        l = lauf("G90\nM4 S450 F1000\nG1 X294.9\n", x_max=295.0)
        self.assertEqual(l.befunde, [])

    def test_s_ueber_der_obergrenze(self):
        l = lauf("G90\nM4 S1400 F1000\nG1 X10\n", s_max=1000.0)
        self.assertIn("s_zu_gross", arten(l))


class WasGrblNichtKann(unittest.TestCase):
    def test_fraesbefehle_werden_gemeldet(self):
        l = lauf("G90\nM6 T2\nG81 X20 Y20 Z-3 R5\nG43 H1\n")
        self.assertEqual(l.zahl.get("unbekannt"), 3)

    def test_bekannte_befehle_schweigen(self):
        l = lauf("G21\nG90\nG94\nG17\nG54\nM4 S0\nM5\n")
        self.assertNotIn("unbekannt", arten(l))

    def test_g1_ohne_vorschub(self):
        l = lauf("G90\nM4 S450\nG1 X10\n")
        self.assertIn("kein_f", arten(l))

    def test_haltebefehl(self):
        l = lauf("G90\nM4 S450 F1000\nG1 X10\nM0\n")
        self.assertIn("halt", arten(l))


class ModalerZustand(unittest.TestCase):
    def test_relativ_rechnet_weiter(self):
        l = lauf("G90\nM4 S450 F1000\nG1 X10\nG91\nG1 X5\nG1 X5\n")
        self.assertAlmostEqual(l.x, 20.0, places=6)

    def test_zoll_wird_umgerechnet_und_gemeldet(self):
        l = lauf("G90\nM4 S450 F1000\nG20\nG1 X2\n")
        self.assertIn("zoll", arten(l))
        self.assertAlmostEqual(l.x, 50.8, places=6)

    def test_g92_wird_gemeldet(self):
        l = lauf("G90\nG92 X0 Y0\nM4 S450 F1000\nG1 X10\n")
        self.assertIn("g92", arten(l))

    def test_vorschub_bleibt_stehen(self):
        l = lauf("G90\nM4 S450 F600\nG1 X10\nG1 X20\n")
        self.assertEqual(sorted(l.nach_f), [600.0])


class Laufzeit(unittest.TestCase):
    """Die Zeit kommt aus demselben Modell wie die Vorschau. Haette der
    Trockenlauf ein eigenes, wuerden sich beide Zahlen widersprechen."""

    def test_helle_stellen_laufen_mit_vorschub(self):
        """G1 mit S0 faehrt weiter mit F, nicht im Eilgang. Als Leerfahrt
        gerechnet war der Job um Stunden zu kurz."""
        l = lauf("G90\nM4 S0 F1000\nG1 X100\n")
        self.assertEqual(l.eilweg, 0.0)
        self.assertIn(1000.0, l.nach_f)

    def test_g0_zaehlt_als_eilgang(self):
        l = lauf("G90\nM4 S0 F1000\nG0 X100\n")
        self.assertAlmostEqual(l.eilweg, 100.0, places=6)
        self.assertEqual(l.nach_f, {})

    def test_wie_die_vorschau(self):
        """500 Befehle ohne G0 dazwischen sind eine Bahn - die Achse haelt
        fuer einen Leistungswechsel nicht an."""
        import lw_job as J
        strecken = [1.0] * 500
        g = ["G90", "M4 S450 F1000"]
        at = 0.0
        for d in strecken:
            at += d
            g.append("G1 X%.3f S450" % at)
        l = lauf("\n".join(g) + "\n", x_max=600.0)
        self.assertAlmostEqual(l.laufzeit(), J.estimate([sum(strecken)], 1000),
                               places=6)

    def test_g0_trennt_die_bahnen(self):
        """Zwei Haelften mit einem Halt dazwischen dauern laenger als
        dieselbe Strecke am Stueck."""
        import lw_job as J
        a = lauf("G90\nM4 S450 F1000\nG1 X100\n", x_max=600.0)
        b = lauf("G90\nM4 S450 F1000\nG1 X50\nG0 X50\nG1 X100\n", x_max=600.0)
        self.assertGreater(b.laufzeit(), a.laufzeit())
        self.assertAlmostEqual(a.laufzeit(), J.estimate([100.0], 1000),
                               places=6)


class StelleFinden(unittest.TestCase):
    def test_befehl_wird_verortet(self):
        g = "G90\nM4 S450 F1000\nG1 X10\nG1 X20\nG1 X30\n"
        l = lauf(g, bei=4)
        self.assertIsNotNone(l.halt)
        zeile, x, y = l.halt[0], l.halt[1], l.halt[2]
        self.assertEqual(zeile, 4)
        self.assertAlmostEqual(x, 20.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)

    def test_kommentare_zaehlen_nicht_als_befehl(self):
        l = lauf("; Kopf\n; noch einer\nG90\nM4 S450 F1000\nG1 X10\n")
        self.assertEqual(l.befehle, 3)


class LangeStriche(unittest.TestCase):
    def test_lange_brennende_strecke_wird_aufgelistet(self):
        l = lauf("G90\nM4 S450 F1000\nG1 X200\n")
        self.assertEqual(len(l.lange), 1)

    def test_aber_nicht_als_befund(self):
        """Ein Rechteck besteht aus vier langen Strichen - das ist kein
        Fehler, sonst meldet das Werkzeug bei jedem Schnitt Alarm."""
        l = lauf("G90\nM4 S450 F1000\nG1 X200\n")
        self.assertEqual(l.befunde, [])

    def test_leerfahrt_zaehlt_nicht(self):
        l = lauf("G90\nM4 S450 F1000\nG0 X200\n")
        self.assertEqual(l.lange, [])


class EchterJob(unittest.TestCase):
    """Gegen das, was Laserwerk selbst erzeugt - und gegen seine eigenen
    Zahlen. Weichen sie ab, stimmt eines von beiden nicht."""

    def gcode(self):
        import lw_vector as V
        p = os.path.join(tempfile.mkdtemp(), "q.svg")
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="40" '
                    'height="20" viewBox="0 0 40 20">'
                    '<path d="M 0 0 L 40 0 L 40 20 L 0 20 Z" fill="none" '
                    'stroke="#000"/></svg>')
        polys = V.order(V.fit(V.flatten(V.load_vector(p), 1.0),
                              40.0, 20.0, 10.0, 10.0)[0])
        return V.cut_gcode(polys, 700, 220, 2)

    def test_schnitt_laeuft_ohne_befund_durch(self):
        g, _ = self.gcode()
        l = lauf("\n".join(g) + "\n")
        self.assertEqual(l.befunde, [])

    def test_brennweg_stimmt_mit_der_vorschau(self):
        g, info = self.gcode()
        l = lauf("\n".join(g) + "\n")
        self.assertAlmostEqual(l.brennweg / 1000, info["cut_m"], places=3)

    def test_laufzeit_liegt_bei_der_vorschau(self):
        g, info = self.gcode()
        l = lauf("\n".join(g) + "\n")
        # Die Vorschau rechnet die Leerfahrten pauschal, der Trockenlauf
        # aus den tatsaechlichen Wegen - ein paar Prozent Abstand bleiben.
        self.assertLess(abs(l.laufzeit() - info["sekunden"]),
                        0.1 * info["sekunden"])


class NichtsWirdAngefasst(unittest.TestCase):
    def test_kein_serieller_port_im_modul(self):
        """Der Trockenlauf ist das Werkzeug fuer den Fall, dass man der
        Maschine gerade nicht traut. Es darf sie nicht anfassen."""
        with open(os.path.join(WURZEL, "trockenlauf.py")) as f:
            quelle = f.read()
        for wort in ("serial", "/dev/tty", "write("):
            self.assertNotIn(wort, quelle)


if __name__ == "__main__":
    unittest.main()
