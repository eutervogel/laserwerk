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
        kurz = J.estimate([5.0] * 100, 1000)
        lang = J.estimate([10.0] * 100, 1000)
        self.assertGreater(lang, kurz)

    def test_schneller_bei_mehr_vorschub(self):
        langsam = J.estimate([5.0] * 100, 500)
        schnell = J.estimate([5.0] * 100, 1000)
        self.assertLess(schnell, langsam)

    def test_haltestellen_kosten_zeit(self):
        """Nicht die Zerlegung bremst, sondern der Halt: 100 mm am Stueck
        gegen hundert Stuecke, zwischen denen die Achse steht."""
        am_stueck = J.estimate([100.0], 1000)
        mit_halt = J.estimate([1.0] * 100, 1000)
        self.assertGreater(mit_halt, am_stueck)

    def test_feine_zerlegung_bremst_nicht(self):
        """Fuer einen Leistungswechsel haelt die Achse nicht an. Das alte
        Modell rechnete das anders und lag bei Strichgrafik ein Viertel zu
        niedrig, weil ein an Graustufen geeichter Faktor es ausglich."""
        zeile = 100.0
        self.assertAlmostEqual(J.estimate([zeile], 1000),
                               J.estimate([zeile], 1000), places=9)
        # Dieselbe Zeile, egal wie der G-Code sie beschreibt
        g_fein, i_fein = J.raster_gcode(
            np.tile(np.linspace(0.1, 1.0, 200), (40, 1)), 0.1, 830, 1000)
        g_grob, i_grob = J.raster_gcode(
            np.ones((40, 200)), 0.1, 830, 1000)
        self.assertGreater(len(g_fein), len(g_grob) * 3)
        self.assertAlmostEqual(i_fein["sekunden"], i_grob["sekunden"],
                               places=6)

    def test_trapez_erreicht_die_reisegeschwindigkeit_nicht(self):
        """Kurze Bahn: die Achse beschleunigt und bremst sofort wieder."""
        lang = J.fahrzeit(100.0, 1000 / 60.0, 30.0)
        kurz = J.fahrzeit(0.5, 1000 / 60.0, 30.0)
        self.assertAlmostEqual(kurz, 2 * (0.5 / 30.0) ** 0.5, places=9)
        self.assertGreater(lang, kurz)

    def test_eilgang_ist_schneller_als_vorschub(self):
        mit = J.estimate([], 1000, [100.0])
        ohne = J.estimate([100.0], 1000, [])
        self.assertLess(mit, ohne)


class EckenKostenZeit(unittest.TestCase):
    """Eine nachgezeichnete Kontur hat Hunderte Richtungswechsel, und an
    jedem laesst $11 nur noch wenig Tempo durch. Als eine gerade Strecke
    gerechnet war der Schnitt fast um die Haelfte zu kurz angesagt."""

    def test_gerade_punktfolge_ist_die_gerade_strecke(self):
        """Geradeaus bremst niemand - sonst waere die Gravurzeile falsch."""
        pts = [(x, 0.0) for x in range(0, 101)]
        self.assertAlmostEqual(J.bahnzeit(pts, 1000 / 60.0),
                               J.fahrzeit(100.0, 1000 / 60.0), places=9)

    def test_zickzack_dauert_laenger_als_die_gerade(self):
        zick = [(i * 1.0, 0.5 if i % 2 else 0.0) for i in range(101)]
        weg = sum(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
                  for a, b in zip(zick, zick[1:]))
        self.assertGreater(J.bahnzeit(zick, 1000 / 60.0),
                           2 * J.fahrzeit(weg, 1000 / 60.0))

    def test_spitzer_knick_bremst_mehr_als_ein_flacher(self):
        import math
        def knick(grad):
            r = math.radians(grad)
            return [(0.0, 0.0), (20.0, 0.0),
                    (20.0 + 20 * math.cos(r), 20 * math.sin(r))]
        self.assertGreater(J.bahnzeit(knick(90), 1000 / 60.0),
                           J.bahnzeit(knick(10), 1000 / 60.0))

    def test_eine_bahn_darf_zahl_oder_punktfolge_sein(self):
        zahl = J.estimate([100.0], 1000)
        punkte = J.estimate([[(0.0, 0.0), (100.0, 0.0)]], 1000)
        self.assertAlmostEqual(zahl, punkte, places=9)

    def test_schnitt_sieht_die_ecken(self):
        """Dieselbe Schnittlaenge, einmal gerade, einmal nachgezeichnet."""
        import lw_vector as V
        gerade = [{"pts": [(0.0, 0.0), (100.0, 0.0)], "closed": False}]
        zackig = [{"pts": [(i * 1.0, 0.5 if i % 2 else 0.0)
                           for i in range(101)], "closed": False}]
        _, a = V.cut_gcode(gerade, 500, 600)
        _, b = V.cut_gcode(zackig, 500, 600)
        self.assertAlmostEqual(a["cut_m"], 0.1, places=3)
        self.assertGreater(b["sekunden"], 2 * a["sekunden"])


class EnergieJeMillimeter(unittest.TestCase):
    def test_gravurwerte_ritzen_nur_an(self):
        """Genau der Fall aus dem Projekt mit fuenf Baggern: vier Elemente
        standen auf den Gravurwerten, eines auf echten Schnittwerten."""
        self.assertAlmostEqual(J.energie(830, 1000, 1), 0.27, delta=0.01)
        self.assertAlmostEqual(J.energie(1000, 330, 6), 6.0, delta=0.05)

    def test_durchgaenge_zaehlen_mit(self):
        self.assertAlmostEqual(J.energie(500, 600, 4),
                               4 * J.energie(500, 600, 1), places=9)

    def test_haelt_unsinn_aus(self):
        self.assertEqual(J.energie(500, 0), 0.0)
        self.assertEqual(J.energie(None, 600), 0.0)


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

    def test_vorschau_zeigt_auch_schwache_fahrten(self):
        """Eine Rahmenfahrt mit S40 ist kein leeres Blatt.

        Die Graustufe hing an der absoluten Leistung: S40 von S1000 ergab
        246 von 255, also weiss auf weiss. In Laserwerk sah man dann den
        Kasten und darin nichts - ausgerechnet bei den Dateien, die man
        vor dem Start noch einmal ansehen will.
        """
        import io as _io
        from PIL import Image as _Image
        g = ["G21", "G90", "M4 S40",
             "G1 X10 Y0 F1000", "G1 X10 Y10", "G1 X0 Y10", "G1 X0 Y0", "M5"]
        png, _bb, info = J.gcode_preview(g, 10)
        bild = np.asarray(_Image.open(_io.BytesIO(png)).convert("L"))
        self.assertLess(bild.min(), 120, "schwache Bahnen bleiben unsichtbar")

    def test_vorschau_haelt_die_abstufung(self):
        """Dunkler heisst immer noch staerker - nur eben im Verhaeltnis."""
        import io as _io
        from PIL import Image as _Image
        g = ["G21", "G90",
             "M4 S100", "G1 X20 Y0 F1000",
             "M4 S900", "G1 X20 Y20", "M5"]
        png, _bb, _i = J.gcode_preview(g, 10)
        bild = np.asarray(_Image.open(_io.BytesIO(png)).convert("L"))
        unten = bild[-3:, :].min()          # die schwache Bahn
        rechts = bild[:, -3:].min()         # die starke
        self.assertLess(rechts, unten)

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


class Bildkorrektur(unittest.TestCase):
    def setUp(self):
        # Foto mit hellgrauem Hintergrund und mittlerem Motiv
        a = np.full((200, 300), 235, dtype=np.uint8)
        a[60:140, 80:220] = 120
        self.foto = Image.fromarray(a)

    def test_ohne_werte_bleibt_das_bild(self):
        gleich = J.bildkorrektur(self.foto, 0, 0, 0)
        self.assertEqual(list(gleich.getdata())[:5],
                         list(self.foto.getdata())[:5])

    def test_kontrast_spreizt(self):
        vorher = np.asarray(self.foto, dtype=float).std()
        nachher = np.asarray(J.bildkorrektur(self.foto, 0, 50, 0), dtype=float).std()
        self.assertGreater(nachher, vorher)

    def test_helligkeit_hebt(self):
        vorher = np.asarray(self.foto, dtype=float).mean()
        nachher = np.asarray(J.bildkorrektur(self.foto, 40, 0, 0), dtype=float).mean()
        self.assertGreater(nachher, vorher)

    def test_auto_zieht_den_hintergrund_auf_weiss(self):
        h, k = J.auto_tonwerte(self.foto)
        roh = J.prepare(self.foto, 60.0, 40.0, 0.15, mode="raster")
        auto = J.prepare(self.foto, 60.0, 40.0, 0.15, mode="raster",
                         helligkeit=h, kontrast=k)
        # Hintergrund oben links: vorher ein duenner Teppich, danach nichts
        self.assertGreater(roh[:20, :20].sum(), 0.0)
        self.assertEqual(auto[:20, :20].sum(), 0.0)
        # das Motiv wird dafuer kraeftiger, der Abstand waechst
        mitte = (slice(80, 120), slice(120, 180))
        self.assertGreater(auto[mitte].mean(), roh[mitte].mean())

    def test_auto_laesst_strichgrafik_in_ruhe(self):
        a = np.full((200, 300), 255, dtype=np.uint8)
        a[50:150, 50:250] = 0
        h, k = J.auto_tonwerte(Image.fromarray(a))
        self.assertAlmostEqual(h, 0.0, delta=2.0)
        self.assertAlmostEqual(k, 0.0, delta=2.0)

    def test_schaerfen_hebt_die_kanten(self):
        weich = self.foto.filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(2))
        a = np.asarray(weich, dtype=float)
        b = np.asarray(J.bildkorrektur(weich, 0, 0, 80), dtype=float)
        self.assertGreater(np.abs(np.diff(b, axis=1)).mean(),
                           np.abs(np.diff(a, axis=1)).mean())

    def test_auto_bei_einfarbigem_bild(self):
        flach = Image.fromarray(np.full((50, 50), 128, dtype=np.uint8))
        self.assertEqual(J.auto_tonwerte(flach), (0.0, 0.0))


class ZAusdehnung(unittest.TestCase):
    """Fuer die Fraese: wie tief geht die Datei?"""

    TASCHE = ["G21", "G90", "G0 Z5.000", "G0 X10 Y10",
              "G1 Z-1.000 F200", "G1 X50 F600", "G1 Y40",
              "G0 Z5.000", "G1 Z-2.500 F200", "G1 X10", "G0 Z5.000"]

    def test_tiefster_und_hoechster_wert(self):
        self.assertEqual(J.z_extent(self.TASCHE), (-2.5, 5.0))

    def test_ohne_z_kommt_nichts(self):
        self.assertIsNone(J.z_extent(["G1 X10 Y10 F600", "G1 X20"]))

    def test_kommentare_zaehlen_nicht(self):
        self.assertIsNone(J.z_extent(["G1 X10 ; Z-9 waere falsch"]))

    def test_kleinschreibung(self):
        self.assertEqual(J.z_extent(["g1 z-3.0 f200"]), (-3.0, -3.0))

    def test_fokustest_bleibt_ueber_null(self):
        """Beim Lasern kommt Z nur im Fokustest vor - und dort oberhalb
        des Materials. Die Tiefenabfrage darf da nicht anspringen."""
        g, _ = J.fokustest_z(12.0, 4.0, 1.0, 120, 1000)
        self.assertGreater(J.z_extent(g)[0], 0.0)


class EingebetteteBilder(unittest.TestCase):
    """SVGs aus neueren Zeichenprogrammen betten Bilder mit dem schlichten
    href ein (SVG 2). Inkscape 1.2 zeichnet nur xlink:href - beim Rendern
    fiel dann genau das Motiv heraus und uebrig blieb der Rahmen."""

    def setUp(self):
        import base64, io, tempfile
        self.d = tempfile.mkdtemp(prefix="laserwerk-svg-")
        bild = Image.new("L", (40, 20), 0)          # schwarzes Rechteck
        roh = io.BytesIO()
        bild.save(roh, format="PNG")
        self.b64 = base64.b64encode(roh.getvalue()).decode()

    def svg(self, attr, mit_xlink_ns=False):
        import os
        ns = ' xmlns:xlink="http://www.w3.org/1999/xlink"' if mit_xlink_ns else ""
        p = os.path.join(self.d, attr.replace(":", "_") + ".svg")
        with open(p, "w") as f:
            f.write(f'<svg xmlns="http://www.w3.org/2000/svg"{ns} width="40mm" '
                    'height="20mm" viewBox="0 0 40 20">'
                    f'<image {attr}="data:image/png;base64,{self.b64}" '
                    'x="0" y="0" width="40" height="20"/></svg>')
        return p

    def test_haengt_xlink_davor(self):
        neu = J.xlink_notdurft(self.svg("href"))
        self.assertIsNotNone(neu)
        with open(neu) as f:
            t = f.read()
        self.assertIn("xlink:href=", t)
        self.assertIn("xmlns:xlink", t)

    def test_laesst_xlink_in_ruhe(self):
        self.assertIsNone(J.xlink_notdurft(self.svg("xlink:href", True)))

    def test_ohne_bild_keine_kopie(self):
        import os
        p = os.path.join(self.d, "nur_pfad.svg")
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="10mm" '
                    'height="10mm" viewBox="0 0 10 10">'
                    '<path d="M1 1 L9 9" stroke="black"/></svg>')
        self.assertIsNone(J.xlink_notdurft(p))

    def test_das_bild_kommt_im_render_an(self):
        im = J.load_source(self.svg("href"), 200)
        self.assertEqual(im.getextrema()[0], 0, "das eingebettete Bild fehlt")

    def test_xlink_rendert_weiterhin(self):
        im = J.load_source(self.svg("xlink:href", True), 200)
        self.assertEqual(im.getextrema()[0], 0)


class Schnittvorlage(unittest.TestCase):
    """Eine Schnittvorlage traegt beides: das Motiv als eingebettetes Bild
    und die Schnittlinien als Pfade drumherum.

    Wer so eine Datei rastert, graviert sich die Schnittlinien mitten ins
    Motiv. Das Werkstueck ist dann zwar fertig, aber die Vorlage fuer den
    naechsten Durchgang ist hin - genau so ist ein Puzzlemuster in ein
    zehnstuendiges Hundebild gebrannt worden.
    """

    def setUp(self):
        import base64, io, os, tempfile
        self.d = tempfile.mkdtemp(prefix="laserwerk-schnitt-")
        roh = io.BytesIO()
        Image.new("L", (40, 20), 255).save(roh, format="PNG")   # weisses Bild
        self.b64 = base64.b64encode(roh.getvalue()).decode()
        self.os = os

    def vorlage(self, name="beides.svg", bild=True, linien=True):
        p = self.os.path.join(self.d, name)
        teile = ['<svg xmlns="http://www.w3.org/2000/svg" '
                 'xmlns:xlink="http://www.w3.org/1999/xlink" width="40mm" '
                 'height="20mm" viewBox="0 0 40 20">',
                 '<defs><clipPath id="rahmen">'
                 '<rect width="40" height="20"/></clipPath></defs>']
        if bild:
            teile.append('<image xlink:href="data:image/png;base64,%s" '
                         'x="0" y="0" width="40" height="20" '
                         'clip-path="url(#rahmen)"/>' % self.b64)
        if linien:
            teile.append('<g id="schnittlinien" fill="none" stroke="#000000" '
                         'stroke-width="0.6"><path d="M0 10 H40"/>'
                         '<path d="M20 0 V20"/></g>')
        teile.append("</svg>")
        with open(p, "w") as f:
            f.write("".join(teile))
        return p

    def test_anteile(self):
        self.assertEqual(J.svg_anteile(self.vorlage()), (1, 2))

    def test_vorlagen_zaehlen_nicht_mit(self):
        """Das rect im clipPath wird nie gezeichnet - es ist keine Linie,
        die mitgraviert wuerde."""
        self.assertEqual(J.svg_anteile(self.vorlage(linien=False)), (1, 0))

    def test_nur_bilder_laesst_die_linien_weg(self):
        neu = J.nur_bilder(self.vorlage())
        self.assertEqual(J.svg_anteile(neu), (1, 0))

    def test_der_rahmen_bleibt_stehen(self):
        """Ohne clipPath und viewBox landet das Bild woanders als vorher."""
        with open(J.nur_bilder(self.vorlage())) as f:
            t = f.read()
        self.assertIn("clipPath", t)
        self.assertIn('viewBox="0 0 40 20"', t)

    def test_ohne_linien_keine_kopie(self):
        self.assertIsNone(J.nur_bilder(self.vorlage(linien=False)))

    def test_ohne_bild_keine_kopie(self):
        self.assertIsNone(J.nur_bilder(self.vorlage(bild=False)))

    def test_gerendert_bleiben_die_linien_draussen(self):
        p = self.vorlage()
        voll = J.load_source(p, 200)
        nur = J.load_source(p, 200, nur_bild=True)
        self.assertEqual(voll.size, nur.size, "das Bild muss gleich liegen")
        self.assertEqual(voll.getextrema()[0], 0, "die Linien fehlen schon so")
        self.assertEqual(nur.getextrema(), (255, 255),
                         "die Schnittlinien sind mitgerendert worden")

    def test_schalter_wirkt_nur_bei_svg(self):
        """Ein Pixelbild hat nichts auszublenden - und darf daran auch
        nicht scheitern."""
        p = self.os.path.join(self.d, "flach.png")
        Image.new("L", (10, 10), 128).save(p)
        self.assertEqual(J.load_source(p, nur_bild=True).size, (10, 10))


class VorlageInVorlage(unittest.TestCase):
    """Wer eine Schnittvorlage noch einmal einrahmt, bekommt die ganze alte
    Vorlage als data:image/svg+xml in die neue gelegt. Inkscape zeichnet
    diese innere SVG - und laesst darin wieder genau das Bild weg, weil es
    am schlichten href haengt. Herausgekommen sind zwei Rahmen und kein
    Motiv."""

    def setUp(self):
        import base64, io, os, tempfile
        self.b64, self.os = base64, os
        self.d = tempfile.mkdtemp(prefix="laserwerk-innen-")
        roh = io.BytesIO()
        Image.new("L", (40, 20), 0).save(roh, format="PNG")   # schwarz
        self.png = base64.b64encode(roh.getvalue()).decode()

    def blatt(self, inhalt):
        """Motiv in der Mitte, Rahmen am Blattrand - sonst liegt der Rahmen
        auf dem Motiv und sein Wegfallen waere nicht zu sehen."""
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="40mm" '
                'height="20mm" viewBox="0 0 40 20">%s'
                '<g id="rahmen" fill="none" stroke="#ff0000" '
                'stroke-width="0.6"><path d="M0.5 0.5 H39.5 V19.5 H0.5 Z"/>'
                '</g></svg>') % inhalt

    def vorlage(self, tiefe=1):
        """Eine Schnittvorlage, tiefe-mal in sich selbst eingerahmt."""
        t = self.blatt('<image href="data:image/png;base64,%s" x="10" y="6" '
                       'width="20" height="8"/>' % self.png)
        for _ in range(tiefe):
            b = self.b64.b64encode(t.encode()).decode()
            t = self.blatt('<image href="data:image/svg+xml;base64,%s" '
                           'x="4" y="2" width="32" height="16"/>' % b)
        p = self.os.path.join(self.d, "tief%d.svg" % tiefe)
        with open(p, "w") as f:
            f.write(t)
        return p

    def test_das_motiv_kommt_an(self):
        im = J.load_source(self.vorlage(), 200)
        self.assertEqual(im.getextrema()[0], 0, "das innere Motiv fehlt")

    def test_auch_zweimal_eingerahmt(self):
        im = J.load_source(self.vorlage(2), 200)
        self.assertEqual(im.getextrema()[0], 0, "das innere Motiv fehlt")

    def test_xlink_wandert_mit_nach_innen(self):
        neu = J.xlink_notdurft(self.vorlage())
        with open(neu) as f:
            t = f.read()
        innen = J._eingebettete_svg(
            re.search(r'xlink:href="(data:image/svg[^"]*)"', t).group(1))
        self.assertIn("xlink:href=", innen)

    def test_der_innere_rahmen_wird_nicht_mitgraviert(self):
        """Er liegt nicht im Dokument, sondern in dem Bild, als das die alte
        Vorlage darin steckt - von aussen gar nicht zu sehen."""
        p = self.vorlage()
        voll = J.load_source(p, 200)
        nur = J.load_source(p, 200, nur_bild=True)
        self.assertEqual(voll.size, nur.size)
        rot = np.asarray(voll.convert("L"))
        ohne = np.asarray(nur.convert("L"))
        self.assertLess((ohne < 200).sum(), (rot < 200).sum(),
                        "es ist nichts weggefallen")
        # Am Blattrand liegt nur noch Weiss: beide Rahmen sind draussen.
        self.assertEqual(int(ohne[:2, :].max()), 255)
        self.assertEqual(int(ohne[-2:, :].max()), 255)
        self.assertLess(int(rot[:2, :].min()), 200)
        self.assertEqual(ohne.min(), 0, "das Motiv fehlt jetzt auch")

    def test_ohne_eingebettete_vorlage_keine_kopie(self):
        p = self.os.path.join(self.d, "schlicht.svg")
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="10mm" '
                    'height="10mm" viewBox="0 0 10 10">'
                    '<path d="M1 1 L9 9" stroke="black"/></svg>')
        self.assertIsNone(J.nur_bilder(p))
        self.assertIsNone(J.xlink_notdurft(p))
