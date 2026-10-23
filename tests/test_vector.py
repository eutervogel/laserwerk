"""SVG und DXF einlesen, einpassen, drehen, spiegeln, schneiden."""
import math
import os
import tempfile
import unittest

from hilfe import *                                           # noqa: F401,F403
import lw_vector as V


def schreib(inhalt, endung=".svg"):
    f = tempfile.NamedTemporaryFile("w", suffix=endung, delete=False)
    f.write(inhalt)
    f.close()
    return f.name


QUADRAT = """<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="20mm"
 viewBox="0 0 40 20"><rect x="0" y="0" width="40" height="20"
 fill="none" stroke="black"/></svg>"""

ZWEI = """<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60"
 viewBox="0 0 60 60">
 <path d="M 0 0 L 60 0 L 60 60 L 0 60 Z"/>
 <circle cx="30" cy="30" r="10"/></svg>"""


class Einlesen(unittest.TestCase):
    def test_svg_rechteck(self):
        polys = V.flatten(V.load_svg(schreib(QUADRAT)), 1.0)
        x0, y0, x1, y1 = V.bbox(polys)
        self.assertAlmostEqual(x1 - x0, 40.0, delta=0.2)
        self.assertAlmostEqual(y1 - y0, 20.0, delta=0.2)

    def test_svg_mit_zwei_konturen(self):
        polys = V.flatten(V.load_svg(schreib(ZWEI)), 1.0)
        self.assertGreaterEqual(len(polys), 2)

    def test_kaputtes_svg_wirft(self):
        with self.assertRaises(Exception):
            V.load_svg(schreib("das ist kein svg"))

    def test_load_vector_nach_endung(self):
        p = V.load_vector(schreib(QUADRAT))
        self.assertTrue(p)

    def test_vorschaubild(self):
        polys = V.flatten(V.load_svg(schreib(ZWEI)), 1.0)
        im = V.render_preview(polys)
        self.assertGreater(im.width, 10)


class Umformen(unittest.TestCase):
    def setUp(self):
        self.polys = [{"pts": [(0, 0), (40, 0), (40, 20), (0, 20)],
                       "closed": True}]

    def test_einpassen_haelt_das_verhaeltnis(self):
        p, _ = V.fit(self.polys, 80.0, 80.0, 0.0, 0.0)
        x0, y0, x1, y1 = V.bbox(p)
        self.assertAlmostEqual(x1 - x0, 80.0, places=3)
        self.assertAlmostEqual(y1 - y0, 40.0, places=3)   # nicht 80

    def test_einpassen_setzt_auf_den_versatz(self):
        p, _ = V.fit(self.polys, 40.0, 20.0, 12.0, 7.0)
        x0, y0, _, _ = V.bbox(p)
        self.assertAlmostEqual(x0, 12.0, places=3)
        self.assertAlmostEqual(y0, 7.0, places=3)

    def test_drehen_um_90_grad(self):
        p = V.rotate(self.polys, 90)
        x0, y0, x1, y1 = V.bbox(p)
        self.assertAlmostEqual(x1 - x0, 20.0, places=3)
        self.assertAlmostEqual(y1 - y0, 40.0, places=3)

    def test_drehen_um_einen_beliebigen_winkel(self):
        p = V.rotate(self.polys, 30)
        x0, y0, x1, y1 = V.bbox(p)
        a = math.radians(30)
        self.assertAlmostEqual(x1 - x0, 40 * abs(math.cos(a)) + 20 * abs(math.sin(a)),
                               places=2)
        self.assertAlmostEqual(y1 - y0, 40 * abs(math.sin(a)) + 20 * abs(math.cos(a)),
                               places=2)

    def test_spiegeln_an_der_wendeachse(self):
        p = V.mirror(self.polys, "x", 50.0)
        x0, _, x1, _ = V.bbox(p)
        self.assertAlmostEqual(x0, 2 * 50.0 - 40.0, places=3)
        self.assertAlmostEqual(x1, 2 * 50.0 - 0.0, places=3)

    def test_zweimal_spiegeln_ist_das_original(self):
        p = V.mirror(V.mirror(self.polys, "x", 50.0), "x", 50.0)
        self.assertEqual([tuple(map(lambda v: round(v, 6), q)) for q in p[0]["pts"]],
                         [tuple(map(float, q)) for q in self.polys[0]["pts"]])


class Reihenfolge(unittest.TestCase):
    def test_innen_vor_aussen(self):
        aussen = {"pts": [(0, 0), (100, 0), (100, 100), (0, 100)], "closed": True}
        innen = {"pts": [(40, 40), (60, 40), (60, 60), (40, 60)], "closed": True}
        sortiert = V.order([aussen, innen])
        # order() liefert neue Konturen ohne die Hilfsangabe 'tiefe',
        # verglichen wird deshalb der Inhalt
        self.assertEqual(sortiert[0]["pts"], innen["pts"])
        self.assertEqual(sortiert[-1]["pts"], aussen["pts"])
        self.assertEqual(innen["tiefe"], 1)          # liegt in aussen
        self.assertEqual(aussen["tiefe"], 0)


class Schneiden(unittest.TestCase):
    def setUp(self):
        self.polys = [{"pts": [(10, 5), (50, 5), (50, 25), (10, 25)],
                       "closed": True}]

    def test_gcode_faehrt_die_kontur(self):
        g, i = V.cut_gcode(self.polys, 500, 600, 1)
        self.assertIn("G90", g[:8])
        self.assertEqual(i["konturen"], 1)
        self.assertAlmostEqual(i["breite"], 40.0, places=2)
        self.assertAlmostEqual(i["hoehe"], 20.0, places=2)

    def test_mehrere_durchgaenge_verlaengern_den_weg(self):
        _, ein = V.cut_gcode(self.polys, 500, 600, 1)
        _, drei = V.cut_gcode(self.polys, 500, 600, 3)
        self.assertAlmostEqual(drei["cut_m"], 3 * ein["cut_m"], places=3)

    def test_geschlossene_kontur_kehrt_zum_anfang_zurueck(self):
        g, _ = V.cut_gcode(self.polys, 500, 600, 1)
        import lw_job as J
        x0, x1, y0, y1 = J.brenn_extent(g)
        self.assertEqual((round(x0), round(x1), round(y0), round(y1)),
                         (10, 50, 5, 25))


class OffeneLinien(unittest.TestCase):
    def test_join_open_setzt_strecken_zusammen(self):
        teile = [{"pts": [(0, 0), (10, 0)], "closed": False},
                 {"pts": [(10, 0), (10, 10)], "closed": False},
                 {"pts": [(10, 10), (0, 10)], "closed": False},
                 {"pts": [(0, 10), (0, 0)], "closed": False}]
        zusammen = V.join_open(teile, 0.01)
        self.assertEqual(len(zusammen), 1)
        self.assertTrue(zusammen[0]["closed"])


if __name__ == "__main__":
    unittest.main()
