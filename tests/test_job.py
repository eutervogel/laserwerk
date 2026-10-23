"""Rastern, Tonwerte, Ausdehnung, Testmuster - alles ohne Oberflaeche."""
import re
import unittest

import numpy as np
from PIL import Image

from hilfe import *                                           # noqa: F401,F403
import lw_job as J


def s_werte(zeilen):
    """Alle gesendeten Leistungen aus G1-Zeilen."""
    raus = []
    for z in zeilen:
        if z.startswith("G1"):
            m = re.search(r"S(\d+)", z)
            if m:
                raus.append(int(m.group(1)))
    return raus


class Rastern(unittest.TestCase):
    def setUp(self):
        self.p = np.ones((50, 80))          # 8 x 5 mm volle Leistung

    def test_motiv_liegt_auf_dem_versatz(self):
        g, i = J.raster_gcode(self.p, 0.1, 500, 1000, x_off=30.0, y_off=20.0)
        x0, x1, y0, y1 = J.brenn_extent(g)
        self.assertAlmostEqual(x0, 30.0, places=2)
        self.assertAlmostEqual(x1, 38.0, places=2)
        self.assertAlmostEqual(y0, 20.0, places=2)
        self.assertAlmostEqual(y1, 24.9, places=2)

    def test_anlauf_liegt_ausserhalb_des_motivs(self):
        g, i = J.raster_gcode(self.p, 0.1, 500, 1000, x_off=30.0, overscan=1.5)
        self.assertAlmostEqual(i["xmin"], 28.5, places=2)   # 1,5 mm davor
        self.assertAlmostEqual(i["xmax"], 39.5, places=2)   # und dahinter
        self.assertAlmostEqual(J.brenn_extent(g)[0], 30.0, places=2)

    def test_datei_beginnt_absolut_und_endet_im_nullpunkt(self):
        g, _ = J.raster_gcode(self.p, 0.1, 500, 1000)
        self.assertIn("G90", g[:8])
        self.assertEqual(g[-1], "G0 X0 Y0")

    def test_leere_zeilen_werden_uebersprungen(self):
        p = np.zeros((50, 80))
        p[10:20, :] = 1.0
        g, i = J.raster_gcode(p, 0.1, 500, 1000, y_off=0.0)
        self.assertEqual(i["rows"], 10)
        y0, y1 = J.brenn_extent(g)[2:]
        # Bildzeile 0 ist oben, G-Code-Zeile 0 unten: Band 10..19 von oben
        # landet bei y = 3,0 .. 3,9 mm
        self.assertAlmostEqual(y0, 3.0, places=2)
        self.assertAlmostEqual(y1, 3.9, places=2)

    def test_weiss_bleibt_aus(self):
        p = np.zeros((20, 20))
        p[5:10, 5:10] = 1.0
        g, _ = J.raster_gcode(p, 0.1, 800, 1000, s_min=240)
        self.assertEqual(sorted(set(s_werte(g))), [0, 800])

    def test_grenzen_der_leistung(self):
        p = np.linspace(0, 1, 100).reshape(1, 100)
        g, _ = J.raster_gcode(p, 0.1, 400, 1000, s_min=120)
        werte = [s for s in s_werte(g) if s]
        self.assertGreaterEqual(min(werte), 120)
        self.assertLessEqual(max(werte), 400)


class Ausdehnung(unittest.TestCase):
    def test_brenn_extent_ignoriert_rueckfahrt_und_anlauf(self):
        g, _ = J.raster_gcode(np.ones((30, 60)), 0.1, 500, 1000,
                              x_off=40.0, y_off=25.0, overscan=1.5)
        voll = J.extent(g)
        brennt = J.brenn_extent(g)
        self.assertAlmostEqual(voll[0], 0.0, places=2)      # G0 X0 Y0 am Ende
        self.assertAlmostEqual(brennt[0], 40.0, places=2)
        self.assertLess(brennt[1], voll[1])                 # ohne Anlauf

    def test_brenn_extent_bei_schnitt(self):
        import lw_vector as V
        polys = [{"pts": [(10, 5), (50, 5), (50, 25), (10, 25)], "closed": True}]
        g, _ = V.cut_gcode(polys, 500, 600, 1)
        self.assertEqual(tuple(round(v, 2) for v in J.brenn_extent(g)),
                         (10.0, 50.0, 5.0, 25.0))

    def test_rahmen_faehrt_um_das_gebrannte(self):
        g, _ = J.raster_gcode(np.ones((30, 60)), 0.1, 500, 1000,
                              x_off=40.0, y_off=25.0)
        rahmen = J.frame_lines(g, 50, 600)
        self.assertIn("G0 X40.00 Y25.00", rahmen)
        self.assertNotIn("G0 X0.00 Y0.00", rahmen)
        # genau vier Ecken mit Laser an
        self.assertEqual(sum(1 for z in rahmen if z.startswith("G1")), 4)

    def test_leere_eingabe(self):
        self.assertEqual(J.extent([]), (0, 0, 0, 0))
        self.assertEqual(J.brenn_extent(["G21", "M5"]), (0, 0, 0, 0))

    def test_modale_bewegung(self):
        """G1 gilt weiter, auch wenn die naechste Zeile nur X nennt."""
        g = ["G90", "M4", "G1 X10 Y10 S500 F600", "X20", "M5", "G0 X0 Y0"]
        self.assertEqual(tuple(round(v, 2) for v in J.brenn_extent(g)),
                         (0.0, 20.0, 0.0, 10.0))


class Tonwerte(unittest.TestCase):
    def setUp(self):
        v = np.linspace(255, 0, 400).astype(np.uint8)
        self.verlauf = Image.fromarray(np.tile(v, (80, 1)))

    def test_schwelle_kennt_nur_an_und_aus(self):
        p = J.prepare(self.verlauf, 40.0, 8.0, 0.1, mode="schwelle")
        self.assertEqual(sorted(set(np.unique(p))), [0.0, 1.0])

    def test_graustufen_lassen_weiss_aus(self):
        p = J.prepare(self.verlauf, 40.0, 8.0, 0.1, mode="grau")
        self.assertEqual(p[:, 0].max(), 0.0)        # ganz hell = aus
        self.assertAlmostEqual(p[:, -1].max(), 1.0, places=2)

    def test_mitten_heben_und_senken(self):
        hell = J.prepare(self.verlauf, 40.0, 8.0, 0.1, mode="grau", gamma=2.0)
        mitte = J.prepare(self.verlauf, 40.0, 8.0, 0.1, mode="grau", gamma=1.0)
        dunkel = J.prepare(self.verlauf, 40.0, 8.0, 0.1, mode="grau", gamma=0.6)
        self.assertLess(hell.mean(), mitte.mean())
        self.assertLess(mitte.mean(), dunkel.mean())
        # Schwarz bleibt Schwarz, egal wie die Kurve liegt
        for p in (hell, mitte, dunkel):
            self.assertAlmostEqual(p[:, -1].max(), 1.0, places=2)

    def test_rasterung_kennt_nur_punkt_oder_nicht(self):
        p = J.prepare(self.verlauf, 40.0, 8.0, 0.1, mode="raster")
        self.assertEqual(sorted(set(np.unique(p))), [0.0, 1.0])

    def test_rasterung_bildet_den_verlauf_als_dichte_ab(self):
        p = J.prepare(self.verlauf, 40.0, 8.0, 0.1, mode="raster")
        achtel = [t.mean() for t in np.array_split(p, 8, axis=1)]
        for i, dichte in enumerate(achtel):
            self.assertAlmostEqual(dichte, (i + 0.5) / 8, delta=0.04)
        self.assertEqual(achtel, sorted(achtel))        # steigt durchgehend

    def test_invertieren(self):
        a = J.prepare(self.verlauf, 40.0, 8.0, 0.1, mode="schwelle")
        b = J.prepare(self.verlauf, 40.0, 8.0, 0.1, mode="schwelle", invert=True)
        self.assertAlmostEqual(a.mean() + b.mean(), 1.0, places=2)

    def test_drehen_tauscht_die_seiten(self):
        p = J.prepare(self.verlauf, 40.0, 20.0, 0.1, mode="schwelle", rotate=90)
        self.assertEqual(p.shape, (200, 400))


class Laufzeit(unittest.TestCase):
    def test_laenger_bei_mehr_strecke(self):
        kurz = J.estimate([5.0] * 100, 1000, 100)
        lang = J.estimate([10.0] * 100, 1000, 100)
        self.assertGreater(lang, kurz)

    def test_schneller_bei_mehr_vorschub(self):
        langsam = J.estimate([5.0] * 100, 500, 100)
        schnell = J.estimate([5.0] * 100, 1000, 100)
        self.assertLess(schnell, langsam)

    def test_kurze_segmente_bremsen(self):
        """100 mm am Stueck sind schneller als 1000 Haeppchen davon."""
        am_stueck = J.estimate([100.0], 1000, 1)
        gestueckelt = J.estimate([0.1] * 1000, 1000, 1000)
        self.assertGreater(gestueckelt, am_stueck)


class Testmuster(unittest.TestCase):
    def test_graustufentest_bildet_die_echte_abbildung_ab(self):
        g, i = J.graustufentest([200], 1000, stufen=6, feld=7.0)
        toene = [int(z.split("S")[-1]) for z in g if z.startswith("; Ton")]
        self.assertEqual(len(toene), 6)
        self.assertEqual(toene, sorted(toene))
        self.assertEqual(toene[-1], 200)                 # dunkelstes = S
        self.assertAlmostEqual(toene[0], 200 * 0.3 + (200 - 60) / 6, delta=2)

    def test_graustufentest_mit_eigener_untergrenze(self):
        g, _ = J.graustufentest([230], 1000, stufen=6, s_min=150)
        toene = [int(z.split("S")[-1]) for z in g if z.startswith("; Ton")]
        self.assertGreaterEqual(min(toene), 150)
        self.assertEqual(max(toene), 230)

    def test_graustufentest_markiert_die_zeilen(self):
        """Eine Zeile bekommt so viele Striche wie ihre Nummer."""
        g, _ = J.graustufentest([100, 200, 300], 1000, stufen=3, feld=6.0)
        striche = [z for z in g if z.startswith("G1 X2.4")]
        self.assertEqual(len(striche), (1 + 2 + 3) * 3)   # je Strich 3 Zeilen

    def test_graustufentest_untergrenze_unter_der_leistung(self):
        g, _ = J.graustufentest([120], 1000, stufen=3, s_min=500)
        toene = [int(z.split("S")[-1]) for z in g if z.startswith("; Ton")]
        self.assertLessEqual(max(toene), 120)

    def test_materialtest_raster(self):
        g = J.materialtest([200, 400], [600, 1000])
        self.assertEqual(sum(1 for z in g if z.startswith("; S")), 4)

    def test_fokustest_liefert_die_hoehen(self):
        g, zs = J.fokustest_z(12.0, 4.0, 0.5, 300, 600)
        self.assertEqual(len(zs), 9)
        self.assertAlmostEqual(zs[0], 10.0, places=3)
        self.assertAlmostEqual(zs[-1], 14.0, places=3)

    def test_sichtkreuz_kehrt_zurueck(self):
        g = J.kreuz_lines(50, 600, 3.0)
        self.assertIn("G91", g)
        self.assertEqual(g[-1], "G90")
        for achse in ("X", "Y"):
            weg = sum(float(re.search(achse + r"(-?[\d.]+)", z).group(1))
                      for z in g if z.startswith("G1") and achse in z)
            self.assertAlmostEqual(weg, 0.0, places=3)


class FremderGcode(unittest.TestCase):
    def test_vorschau_findet_die_fahrten(self):
        g, _ = J.raster_gcode(np.ones((20, 40)), 0.1, 500, 1000, x_off=5.0)
        png, (x0, y0, x1, y1), info = J.gcode_preview(g, 10)
        self.assertTrue(png.startswith(b"\x89PNG"))
        # die Vorschau zeichnet auch die Rueckfahrt zum Nullpunkt mit
        self.assertAlmostEqual(x0, 0.0, delta=0.2)
        self.assertAlmostEqual(x1, 5.0 + 4.0 + 1.5, delta=0.3)
        self.assertGreater(info["befehle"], 0)

    def test_vorschau_ohne_bewegung(self):
        png, bb, info = J.gcode_preview(["G21", "M5"], 10)
        self.assertIsNone(info)


if __name__ == "__main__":
    unittest.main()


class Anlauf(unittest.TestCase):
    """Der Anlauf muss lang genug sein, damit die Achse auf Tempo ist -
    sonst gibt M4 am Zeilenanfang zu wenig Leistung."""

    def test_formel(self):
        self.assertAlmostEqual(J.anlauf_noetig(1000, 30.0), 4.63, places=2)
        self.assertAlmostEqual(J.anlauf_noetig(600, 30.0), 1.67, places=2)
        self.assertAlmostEqual(J.anlauf_noetig(1000, 500.0), 0.28, places=2)

    def test_schnellere_maschine_braucht_weniger(self):
        self.assertLess(J.anlauf_noetig(1000, 500.0), J.anlauf_noetig(1000, 30.0))

    def test_mehr_vorschub_braucht_mehr(self):
        self.assertGreater(J.anlauf_noetig(1500, 30.0), J.anlauf_noetig(1000, 30.0))

    def test_null_stuerzt_nicht_ab(self):
        self.assertGreaterEqual(J.anlauf_noetig(0, 0), 0.0)
