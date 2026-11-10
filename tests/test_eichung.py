"""
Die Kameraeichung - ohne Kamera und ohne Maschine geprueft.

Der Kern ist ein kuenstliches Modell: eine Eichung mit bekannten Zahlen
rechnet die Soll-Stellen der Kreuze ins Bild, die Anpassung rechnet
zurueck, und heraus kommen muessen dieselben Zahlen. Das prueft die
Rechnung vollstaendig, ohne dass ein Laser laeuft - und es ist die einzige
Art, sie zu pruefen: an der Maschine gibt es keine Wahrheit, gegen die man
messen koennte, nur ein zweites Messergebnis.

Fuer die Kreuzsuche wird dasselbe Modell zu einem Bild gemalt: helle
Unterlage mit Beleuchtungsverlauf, dunkle Spur, Unschaerfe, Rauschen.
"""
import unittest

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from hilfe import WURZEL                                      # noqa: F401
import lw_kamera as KAM
import lw_eichung as E


# Die Zahlen sind nicht erfunden: k1/k2 und die Homographie stammen aus der
# Eichung der Falcon2 Pro, auf das halbe Bildmass umgerechnet, damit die
# Tests nicht auf 2592 x 1944 grossen Bildern rechnen muessen.
ECHT = {
    "version": 1, "bild": [1296, 972],
    "k1": -0.23393448122459237, "k2": 0.052031199040878155,
    "mitte": [597.3, 459.2], "mass": 500.0,
    "homographie": [[1.8620282, -0.015225865, 591.28117],
                    [-0.0062692193, -1.8677883, 547.13897],
                    [6.40081e-07, -3.8707e-05, 1.0]],
    "massstab": 1.00221, "drehung": 0.036, "versatz": [190.58, 194.58],
    "hoehe": 260.0, "dicke": 0.0,
}

PUNKTE = np.array(E.raster_punkte(400.0, 400.0))
SOLL_PX = KAM.maschine_nach_bild(PUNKTE, ECHT)

_BILD = {}


def bild_malen(eichung=ECHT, punkte=PUNKTE, tiefe=38, grund=185,
               unschaerfe=1.6, rauschen=3.0, saat=1):
    """Ein Kamerabild, wie es nach dem Brennen aussieht - kuenstlich.

    Die Unterlage ist nicht gleichmaessig hell: die Gehaeuse-LED leuchtet
    von einer Seite, und genau daran sind drei Anlaeufe der echten
    Kreuzsuche gescheitert. Ein Bild mit gleichmaessigem Grund waere ein
    zu leichter Gegner.
    """
    W, H = eichung["bild"]
    rng = np.random.default_rng(saat)
    yy, xx = np.mgrid[0:H, 0:W]
    a = np.full((H, W), 40.0)
    rahmen = Image.new("L", (W, H), 0)
    ecken = KAM.maschine_nach_bild([(-20, -20), (420, -20), (420, 420),
                                    (-20, 420)], eichung)
    ImageDraw.Draw(rahmen).polygon([tuple(p) for p in ecken], fill=255)
    pappe = np.asarray(rahmen) > 0
    licht = grund * (0.75 + 0.45 * (1 - xx / W) * (0.6 + 0.4 * yy / H))
    a[pappe] = licht[pappe]
    for i, (x, y) in enumerate(punkte):
        arm = E.ARM_MARKE if i == 0 else E.ARM
        t = np.linspace(-arm, arm, 400)
        for bahn in (np.column_stack([x + t, np.full_like(t, y)]),
                     np.column_stack([np.full_like(t, x), y + t])):
            for u, v in KAM.maschine_nach_bild(bahn, eichung):
                iu, iv = int(round(u)), int(round(v))
                if 1 <= iu < W - 1 and 1 <= iv < H - 1:
                    a[iv - 1:iv + 2, iu - 1:iu + 2] -= tiefe
    bild = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    bild = bild.filter(ImageFilter.GaussianBlur(unschaerfe))
    b = np.asarray(bild).astype(float) + rng.normal(0, rauschen, (H, W))
    return Image.fromarray(np.clip(b, 0, 255).astype(np.uint8)).convert("RGB")


def kunstbild():
    """Das Bild einmal malen und liegen lassen - es kostet ein paar
    Sekunden, und sechs Tests brauchen dasselbe."""
    if "bild" not in _BILD:
        _BILD["bild"] = bild_malen()
    return _BILD["bild"]


def arm_px(eichung=ECHT, punkte=PUNKTE):
    return E._armlaenge_px(eichung, punkte, 0.0)


class DasRasterLiegtRichtig(unittest.TestCase):
    def test_fuenf_mal_fuenf_mit_rand(self):
        p = E.raster_punkte(400.0, 400.0, rand=30.0, n=5)
        self.assertEqual(len(p), 25)
        xs = sorted({round(x, 6) for x, _ in p})
        self.assertEqual(xs, [30.0, 115.0, 200.0, 285.0, 370.0])

    def test_zeilenweise_von_vorn_links(self):
        """Erst X durchlaufen, dann Y - die Suche verlaesst sich darauf."""
        p = E.raster_punkte(400.0, 400.0, n=3)
        self.assertEqual(p[0], (30.0, 30.0))
        self.assertEqual(p[1][1], 30.0)
        self.assertGreater(p[3][1], p[0][1])

    def test_rechteckiges_bett(self):
        p = E.raster_punkte(400.0, 300.0, rand=20.0, n=4)
        self.assertAlmostEqual(max(x for x, _ in p), 380.0)
        self.assertAlmostEqual(max(y for _, y in p), 280.0)

    def test_zu_breiter_rand_wird_abgelehnt(self):
        with self.assertRaises(ValueError):
            E.raster_punkte(400.0, 400.0, rand=250.0)


class DerBrennauftrag(unittest.TestCase):
    def test_jedes_kreuz_zwei_striche(self):
        z = E.raster_gcode(E.raster_punkte(400.0, 400.0))
        self.assertEqual(sum(1 for s in z if s.startswith("G1 ")), 50)
        self.assertEqual(z[0], "G21")

    def test_laser_ist_am_ende_aus(self):
        z = E.raster_gcode(E.raster_punkte(400.0, 400.0))
        self.assertIn("M5", z[-3:])
        self.assertTrue(z[-1].startswith("G0 "))

    def test_erste_marke_hat_laengere_arme(self):
        """Ohne sie sieht ein verdrehtes Raster aus wie ein richtiges."""
        z = E.raster_gcode([(100.0, 100.0), (200.0, 100.0)],
                           arm=8.0, arm_marke=13.0)
        self.assertIn("G0 X87.000 Y100.000", z)
        self.assertIn("G0 X192.000 Y100.000", z)

    def test_kreuz_ausserhalb_des_verfahrwegs_wird_abgelehnt(self):
        with self.assertRaises(ValueError):
            E.raster_gcode([(2.0, 200.0)], x_max=400.0, y_max=400.0)


class HomographieDurchViele(unittest.TestCase):
    def test_vier_punkte_gehen_exakt_durch(self):
        von = [(0.0, 0.0), (10.0, 0.0), (10.0, 7.0), (0.0, 7.0)]
        nach = [(100.0, 50.0), (300.0, 60.0), (290.0, 200.0), (110.0, 190.0)]
        H = E.homographie_viele(von, nach)
        np.testing.assert_allclose(KAM._anwenden(H, von), nach, atol=1e-6)

    def test_viele_punkte_werden_ausgeglichen(self):
        """Mit Rauschen auf allen Punkten darf keiner exakt getroffen sein,
        aber alle zusammen gut."""
        rng = np.random.default_rng(5)
        von = np.array([(x, y) for x in range(5) for y in range(5)], float)
        H0 = np.array([[2.0, 0.1, 5.0], [-0.2, 1.9, 3.0], [0.001, 0.002, 1.0]])
        nach = KAM._anwenden(H0, von) + rng.normal(0, 0.05, (25, 2))
        H = E.homographie_viele(von, nach)
        d = np.hypot(*(KAM._anwenden(H, von) - nach).T)
        self.assertLess(d.mean(), 0.1)

    def test_zu_wenige_punkte(self):
        with self.assertRaises(ValueError):
            E.homographie_viele([(0, 0), (1, 0), (1, 1)],
                                [(0, 0), (1, 0), (1, 1)])


class AnpassungFindetDasModellWieder(unittest.TestCase):
    """Der Kern: bekannte Zahlen hinein, dieselben Zahlen heraus."""

    def test_ohne_rauschen_exakt(self):
        # k1 und k2 gelten immer zu einer Bezugslaenge: r wird in 'mass'
        # gemessen. Das Modell hier rechnet in 500 Bildpunkten, die
        # Anpassung legt 1000 ab - also steht dasselbe k1 viermal so gross
        # da. Wer das uebersieht, haelt eine richtige Zahl fuer falsch.
        e = E.anpassen(SOLL_PX, PUNKTE, ECHT["bild"], hoehe=260.0)
        f = (E.MASS / ECHT["mass"]) ** 2
        self.assertAlmostEqual(e["k1"], ECHT["k1"] * f, places=4)
        self.assertAlmostEqual(e["k2"], ECHT["k2"] * f ** 2, places=4)
        self.assertAlmostEqual(e["mitte"][0], ECHT["mitte"][0], places=1)
        self.assertAlmostEqual(e["mitte"][1], ECHT["mitte"][1], places=1)
        self.assertLess(e["fehler_mm"], 0.001)

    def test_die_lage_steckt_in_der_homographie(self):
        """Massstab, Drehung und Versatz haben keine eigene Bedeutung mehr -
        sonst waere dieselbe Abbildung auf zwei Arten beschreibbar."""
        e = E.anpassen(SOLL_PX, PUNKTE, ECHT["bild"])
        self.assertEqual(e["massstab"], 1.0)
        self.assertEqual(e["drehung"], 0.0)
        self.assertEqual(e["versatz"], [0.0, 0.0])

    def test_lw_kamera_rechnet_das_ergebnis_nach(self):
        """Die Eichung muss in der Form abgelegt sein, die das Programm
        spaeter liest - nicht nur in der, in der sie entstand."""
        e = E.anpassen(SOLL_PX, PUNKTE, ECHT["bild"], hoehe=260.0)
        mittel, groesster, _ = E.fehler(e, SOLL_PX, PUNKTE)
        self.assertLess(groesster, 0.001)
        self.assertAlmostEqual(groesster, e["fehler_mm"], places=5)

    def test_mit_messrauschen_unter_einem_halben_millimeter(self):
        rng = np.random.default_rng(4)
        px = SOLL_PX + rng.normal(0, 0.5, SOLL_PX.shape)
        e = E.anpassen(px, PUNKTE, ECHT["bild"], hoehe=260.0)
        mittel, groesster, _ = E.fehler(e, SOLL_PX, PUNKTE)
        self.assertLess(mittel, 0.2)
        self.assertLess(groesster, 0.5)

    def test_die_flaeche_steht_dabei(self):
        """Eine Fehlerzahl ohne ihre Flaeche ist eine Falle - 0,43 mm auf
        140 x 100 mm waren draussen 6,5 mm."""
        e = E.anpassen(SOLL_PX, PUNKTE, ECHT["bild"])
        self.assertEqual([round(v) for v in e["spanne_mm"]], [340, 340])
        self.assertEqual(e["kreuze"], 25)
        self.assertIn("340 x 340 mm", KAM.eichung_lesbar(e))

    def test_zu_wenige_kreuze(self):
        with self.assertRaises(ValueError):
            E.anpassen(SOLL_PX[:4], PUNKTE[:4], ECHT["bild"])

    def test_ungleich_viele_punkte(self):
        with self.assertRaises(ValueError):
            E.anpassen(SOLL_PX, PUNKTE[:-1], ECHT["bild"])


class DieMitteIstDerHebel(unittest.TestCase):
    """Nicht die Zahl der Kreuze entscheidet, sondern ob die
    Verzeichnungsmitte mitgesucht wird.

    Mit der Mitte fest in der Bildmitte bleiben ueber einen Millimeter
    stehen, auch mit fuenfundzwanzig Kreuzen - die Linse sitzt eben nicht
    mittig im Bild. Genau das war der Grund, warum die erste Eichung der
    Falcon aussen danebenlag.
    """

    def test_feste_mitte_bleibt_schlecht(self):
        e = E.anpassen(SOLL_PX, PUNKTE, ECHT["bild"], mitte_frei=False)
        self.assertGreater(e["fehler_mm"], 1.0)

    def test_freie_mitte_trifft(self):
        e = E.anpassen(SOLL_PX, PUNKTE, ECHT["bild"], mitte_frei=True)
        self.assertLess(e["fehler_mm"], 0.01)

    def test_neun_kreuze_reichen_schon(self):
        mm = np.array(E.raster_punkte(400.0, 400.0, n=3))
        px = KAM.maschine_nach_bild(mm, ECHT)
        e = E.anpassen(px, mm, ECHT["bild"])
        self.assertTrue(e["mitte"][0] != ECHT["bild"][0] / 2.0)
        self.assertLess(E.fehler(e, SOLL_PX, PUNKTE)[1], 0.01)


class KreuzeImBildFinden(unittest.TestCase):
    def test_alle_kreuze_auf_den_bildpunkt_genau(self):
        funde, guete = E.kreuze_suchen(kunstbild(), SOLL_PX, arm_px=arm_px())
        self.assertTrue((guete > 0).all())
        d = np.hypot(*(funde - SOLL_PX).T)
        self.assertLess(d.max(), 1.0)

    def test_der_kopf_verdeckt_zwei(self):
        """Verdeckt ist nicht gefunden - und darf auch nicht als Fund
        durchgehen, sonst zieht er die ganze Eichung schief."""
        bild = kunstbild().copy()
        mal = ImageDraw.Draw(bild)
        for x, y in SOLL_PX[:2]:
            mal.rectangle([x - 60, y - 60, x + 60, y + 60], fill=(30, 30, 30))
        funde, guete = E.kreuze_suchen(bild, SOLL_PX, arm_px=arm_px())
        schlecht = E._brauchbar(guete, 0.25)
        self.assertFalse(schlecht[0])
        self.assertFalse(schlecht[1])
        self.assertTrue(schlecht[2:].all())

    def test_fenster_bleiben_getrennt(self):
        """Zwei Fenster duerfen sich nie um dasselbe Kreuz streiten."""
        f = E._fensterbreite(SOLL_PX, 20)
        abstand = np.hypot(*(SOLL_PX[1] - SOLL_PX[0]).T)
        self.assertLess(2 * f, abstand)

    def test_an_einer_leeren_unterlage_findet_sie_nichts(self):
        leer = Image.new("RGB", tuple(ECHT["bild"]), (180, 180, 180))
        funde, guete = E.kreuze_suchen(leer, SOLL_PX, arm_px=arm_px())
        self.assertFalse((guete > 0).any())


class DerGanzeAblauf(unittest.TestCase):
    def test_mit_einer_schiefen_alten_eichung(self):
        """So sieht der Normalfall aus: es gibt eine Eichung, sie ist nur
        ungenau. Sie taugt als Wegweiser, nicht als Ergebnis."""
        schief = dict(ECHT, versatz=[194.58, 191.58], drehung=0.3)
        e, funde, guete = E.eichen(kunstbild(), PUNKTE, start=schief)
        self.assertEqual(e["kreuze"], 25)
        self.assertLess(e["fehler_mm"], 0.5)
        self.assertLess(E.fehler(e, SOLL_PX, PUNKTE)[1], 0.5)

    def test_beim_ersten_mal_aus_vier_angeklickten_ecken(self):
        """Der heikelste Punkt des Vorhabens: ohne alte Eichung weiss
        niemand, wo die Kreuze liegen. Vier Klicks reichen - auch wenn sie
        um ein paar Bildpunkte danebengehen."""
        rng = np.random.default_rng(11)
        ecken = np.array([SOLL_PX[0], SOLL_PX[4], SOLL_PX[20], SOLL_PX[24]])
        ecken = ecken + rng.normal(0, 4, (4, 2))
        e, funde, guete = E.eichen(kunstbild(), PUNKTE, ecken_px=ecken,
                                   hoehe=260.0)
        self.assertEqual(e["kreuze"], 25)
        self.assertLess(e["fehler_mm"], 0.5)
        self.assertEqual(e["hoehe"], 260.0)

    def test_ohne_wegweiser_geht_es_nicht(self):
        with self.assertRaises(ValueError):
            E.eichen(kunstbild(), PUNKTE)

    def test_zu_wenig_gefunden_sagt_es(self):
        leer = Image.new("RGB", tuple(ECHT["bild"]), (180, 180, 180))
        with self.assertRaisesRegex(ValueError, "Kreuzen gefunden"):
            E.eichen(leer, PUNKTE, start=ECHT)

    def test_die_dicke_wird_vermerkt(self):
        """Geeicht wird in einer Ebene. Steht nicht dabei, welche, zaehlt
        die Unterlage beim naechsten Mal doppelt."""
        e, _, _ = E.eichen(kunstbild(), PUNKTE, start=ECHT, dicke=0.0)
        self.assertEqual(e["dicke"], 0.0)


class PruefenSagtWasDieEichungTaugt(unittest.TestCase):
    """Der zweite Knopf, und fast der wichtigere: eine Eichung verrutscht
    nicht laut, sie verrutscht still."""

    def test_eine_gute_eichung_meldet_wenig(self):
        mittel, groesster, funde, guete = E.pruefen(kunstbild(), ECHT, PUNKTE)
        self.assertLess(groesster, 0.6)
        self.assertEqual(int((guete > 0).sum()), 25)

    def test_eine_verrutschte_eichung_faellt_auf(self):
        schief = dict(ECHT, versatz=[193.08, 193.08])
        mittel, groesster, _, _ = E.pruefen(kunstbild(), schief, PUNKTE)
        self.assertGreater(mittel, 2.0)

    def test_ohne_kreuze_im_bild(self):
        leer = Image.new("RGB", tuple(ECHT["bild"]), (180, 180, 180))
        with self.assertRaises(ValueError):
            E.pruefen(leer, ECHT, PUNKTE)


if __name__ == "__main__":
    unittest.main()
