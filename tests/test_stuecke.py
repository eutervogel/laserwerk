"""
Werkstuecke im Kamerabild finden - ohne Kamera geprueft.

Gearbeitet wird auf kuenstlichen Draufsichten: ein gleichmaessiger
Untergrund, darauf Scheiben und Brettchen an bekannten Stellen. Was
hereingemalt wurde, muss in Millimetern wieder herauskommen - und zwar
in Maschinenkoordinaten, mit Y nach oben. Genau dort sitzt der Fehler,
den man am Bildschirm nicht sieht und erst am verbrannten Werkstueck.

Die zweite Haelfte der Tests prueft das Gegenteil: dass nichts
herauskommt, wo nichts ist, und dass ein angeschnittenes oder zweifel-
haftes Stueck sich selbst als unsicher meldet. Eine Zahl, die nur so
aussieht wie eine Antwort, ist hier schlimmer als keine.
"""
import math
import unittest

import numpy as np
from PIL import Image, ImageDraw

from hilfe import WURZEL                                      # noqa: F401
import lw_stuecke as ST


PX = 2.0                      # Bildpunkte je Millimeter, wie in Laserwerk
MM = 1.0 / PX
BETT = 200.0                  # kuenstliches Bett, Kante in Millimetern


def bett(stuecke=(), grund=90, hell=225, groesse=BETT):
    """Eine Draufsicht malen: Millimeter hinein, Bild heraus.

    Y zeigt in der Maschine nach oben und im Bild nach unten - diese
    Funktion dreht es um, damit die Tests in Maschinenkoordinaten
    beschrieben werden koennen.
    """
    n = int(groesse * PX)
    b = Image.new("L", (n, n), grund)
    d = ImageDraw.Draw(b)
    for art, *w in stuecke:
        farbe = hell
        if art == "kreis":
            mx, my, r = w[:3]
            if len(w) > 3:
                farbe = w[3]
            d.ellipse([(mx - r) * PX, (groesse - my - r) * PX,
                       (mx + r) * PX, (groesse - my + r) * PX], fill=farbe)
        elif art == "rechteck":
            x0, y0, x1, y1 = w[:4]
            if len(w) > 4:
                farbe = w[4]
            d.rectangle([x0 * PX, (groesse - y1) * PX,
                         x1 * PX, (groesse - y0) * PX], fill=farbe)
        elif art == "gedreht":
            mx, my, br, ho, grad = w
            c, s = math.cos(math.radians(grad)), math.sin(math.radians(grad))
            ecken = []
            for ex, ey in ((-br / 2, -ho / 2), (br / 2, -ho / 2),
                           (br / 2, ho / 2), (-br / 2, ho / 2)):
                ecken.append(((mx + ex * c - ey * s) * PX,
                              (groesse - (my + ex * s + ey * c)) * PX))
            d.polygon(ecken, fill=farbe)
        elif art == "ring":
            mx, my, r, loch = w
            d.ellipse([(mx - r) * PX, (groesse - my - r) * PX,
                       (mx + r) * PX, (groesse - my + r) * PX], fill=farbe)
            d.ellipse([(mx - loch) * PX, (groesse - my - loch) * PX,
                       (mx + loch) * PX, (groesse - my + loch) * PX],
                      fill=grund)
    return b.convert("RGB")


def finden(bild, **kw):
    return ST.finden(bild, MM, 0.0, 0.0, **kw)


class DieGeometrieStimmt(unittest.TestCase):

    def test_huelle_laesst_den_innenpunkt_weg(self):
        h = ST.huelle([(0, 0), (10, 0), (10, 10), (0, 10), (5, 5)])
        self.assertEqual(len(h), 4)
        self.assertNotIn((5.0, 5.0), h)

    def test_minrechteck_findet_die_drehung(self):
        grad = 30.0
        c, s = math.cos(math.radians(grad)), math.sin(math.radians(grad))
        ecken = [(100 + x * c - y * s, 50 + x * s + y * c)
                 for x, y in ((-30, -10), (30, -10), (30, 10), (-30, 10))]
        mitte, br, ho, winkel = ST.minrechteck(ecken)
        self.assertAlmostEqual(mitte[0], 100.0, places=6)
        self.assertAlmostEqual(mitte[1], 50.0, places=6)
        self.assertAlmostEqual(br, 60.0, places=6)
        self.assertAlmostEqual(ho, 20.0, places=6)
        self.assertAlmostEqual(abs(winkel), 30.0, places=6)

    def test_kreis_findet_mitte_und_halbmesser(self):
        punkte = [(60 + 25 * math.cos(a), 80 + 25 * math.sin(a))
                  for a in np.linspace(0, 2 * math.pi, 40, endpoint=False)]
        cx, cy, r, rest = ST.kreis(punkte)
        self.assertAlmostEqual(cx, 60.0, places=6)
        self.assertAlmostEqual(cy, 80.0, places=6)
        self.assertAlmostEqual(r, 25.0, places=6)
        self.assertLess(rest, 1e-6)

    def test_kreis_auf_einer_geraden_gibt_auf(self):
        # Drei Punkte auf einer Linie haben keinen Kreis. Lieber unendlich
        # Rest als eine Mitte, die irgendwo im Nichts liegt.
        cx, cy, r, rest = ST.kreis([(0, 0), (1, 0), (2, 0), (3, 0)])
        self.assertEqual(rest, float("inf"))

    def test_ebnen_macht_aus_tausend_punkten_vier(self):
        rand = [(x, 0.0) for x in range(0, 101)] + \
               [(100.0, y) for y in range(1, 51)] + \
               [(x, 50.0) for x in range(99, -1, -1)] + \
               [(0.0, y) for y in range(49, 0, -1)]
        self.assertLessEqual(len(ST._ebnen(rand, 0.3)), 6)

    def test_ebnen_laesst_den_kreis_rund(self):
        kreis = [(50 * math.cos(a), 50 * math.sin(a))
                 for a in np.linspace(0, 2 * math.pi, 600, endpoint=False)]
        aus = ST._ebnen(kreis, 0.3)
        self.assertGreater(len(aus), 20)
        for x, y in aus:
            self.assertAlmostEqual(math.hypot(x, y), 50.0, places=6)

    def test_im_umriss_oder_daneben(self):
        viereck = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertTrue(ST._in_umriss((5, 5), viereck))
        self.assertFalse(ST._in_umriss((15, 5), viereck))
        self.assertFalse(ST._in_umriss((-1, 5), viereck))


class FlaechenZusammenfassen(unittest.TestCase):

    def felder(self, zeilen):
        return np.array([[c != "." for c in z] for z in zeilen], dtype=bool)

    def test_zwei_getrennte_flecken_sind_zwei(self):
        m = self.felder(["##..##", "##..##", "......"])
        marken, n = ST._marken(m)
        self.assertEqual(n, 2)
        self.assertNotEqual(marken[0][0], marken[0][4])

    def test_schraeg_beruehrt_ist_zusammen(self):
        m = self.felder(["#..", ".#.", "..#"])
        _, n = ST._marken(m)
        self.assertEqual(n, 1)

    def test_das_u_wird_unten_eines(self):
        m = self.felder(["#..#", "#..#", "####"])
        _, n = ST._marken(m)
        self.assertEqual(n, 1)

    def test_eine_luecke_von_zwei_trennt(self):
        m = self.felder(["#...#", ".....", "....."])
        _, n = ST._marken(m)
        self.assertEqual(n, 2)

    def test_zu_unruhig_gibt_auf(self):
        # Ein Schachbrett ist der schlimmste Fall: jede Zeile lauter
        # einzelne Laeufe. Darauf zu antworten waere geraten.
        m = np.indices((200, 200)).sum(axis=0) % 2 == 0
        marken, n = ST._marken(m, grenze=1000)
        self.assertIsNone(marken)
        self.assertEqual(n, 0)

    def test_das_kleine_loch_zaehlt_zur_flaeche(self):
        """Eine Maserung ist kein zweites Werkstueck.

        Ohne Zuschlagen waere die Flaeche um das Loch kleiner und das
        Stueck nicht mehr rund.
        """
        s = finden(bett([("ring", 100, 100, 40, 5)]))
        self.assertEqual(len(s), 1)
        self.assertAlmostEqual(s[0]["breite"], 80.0, delta=1.0)
        self.assertEqual(s[0]["form"], "rund")

    def test_das_grosse_loch_ist_ein_eigener_fund(self):
        """Daran ist der erste Versuch an der echten Maschine gescheitert.

        Ein dunkler Untersetzer auf einem weissen Blatt ist genau das -
        ein Loch im Blatt. Wer es nur zuschlaegt, fuellt das Werkstueck
        weg und meldet das Blatt.
        """
        s = finden(bett([("ring", 100, 100, 70, 30)]))
        self.assertEqual(len(s), 2)
        self.assertEqual(sorted(x["form"] for x in s), ["rund", "rund"])
        masse = sorted(x["breite"] for x in s)
        # Eine halbe Bildpunktbreite Zugabe ist richtig und nicht Fehler:
        # bei einer hart gezeichneten Kante liegt die wahre Kante zwischen
        # dem letzten gefuellten und dem ersten leeren Punkt, und genau
        # dorthin setzt die Feinkante sie. Am Kamerabild, wo die Kante
        # weich ist, trifft sie sie wirklich.
        self.assertAlmostEqual(masse[0], 60.0, delta=0.8)
        self.assertAlmostEqual(masse[1], 140.0, delta=0.8)
        # Das Blatt misst sich mitsamt dem Loch - sein Umriss ist der
        # aeussere, und seine Flaeche soll dazu passen.
        gross = max(s, key=lambda x: x["breite"])
        self.assertAlmostEqual(gross["flaeche"], math.pi * 70.0 ** 2,
                               delta=0.05 * math.pi * 70.0 ** 2)


class DieKanteWirdNachgefasst(unittest.TestCase):
    """Der verfolgte Rand liegt auf dem Bildpunktraster.

    In halben Millimetern, und wo genau er liegt, haengt an der Schwelle,
    die jemand eingestellt hat. Fuer eine Anzeige reicht das, fuer ein
    Mass nicht und fuer eine Mitte schon gar nicht. Deshalb wird quer zur
    Kontur durch das graue Bild geschnitten und die Kante dort gesucht,
    wo die Helligkeit auf halber Hoehe steht.
    """

    def weiche_scheibe(self, mx, my, r, unschaerfe=2.5):
        """Eine Scheibe mit weicher Kante - so wie eine Kamera sie sieht."""
        from PIL import ImageFilter
        b = Image.new("L", (int(BETT * PX), int(BETT * PX)), 90)
        ImageDraw.Draw(b).ellipse(
            [(mx - r) * PX, (BETT - my - r) * PX,
             (mx + r) * PX, (BETT - my + r) * PX], fill=225)
        return b.filter(ImageFilter.GaussianBlur(unschaerfe)).convert("RGB")

    def test_sie_trifft_die_weiche_kante(self):
        soll_r = 30.0
        # PIL malt die Ellipse einschliesslich beider Grenzen - die
        # gemalte Scheibe ist deshalb einen Bildpunkt breiter als 2*r.
        soll = 2 * soll_r + 1.0 / PX
        # ...und sie sitzt deshalb auch eine halbe Bildpunktbreite weiter.
        soll_x, soll_y = 100.0 + 0.5 / PX, 100.0 - 0.5 / PX
        bild = self.weiche_scheibe(100.0, 100.0, soll_r)
        s = finden(bild)
        self.assertEqual(len(s), 1)
        self.assertAlmostEqual(s[0]["breite"], soll, delta=0.2)
        self.assertAlmostEqual(s[0]["mitte"][0], soll_x, delta=0.15)
        self.assertAlmostEqual(s[0]["mitte"][1], soll_y, delta=0.15)

    def test_sie_haengt_kaum_noch_an_der_schwelle(self):
        """Das ist der eigentliche Gewinn: das Mass soll nicht davon
        abhaengen, wie jemand einen Regler gestellt hat."""
        bild = self.weiche_scheibe(100.0, 100.0, 30.0)
        masse = [finden(bild, schwelle=s)[0]["breite"]
                 for s in (0.14, 0.20, 0.26)]
        self.assertLess(max(masse) - min(masse), 0.5,
                        "Durchmesser streut ueber die Schwellen: %r" % (masse,))

    def test_ohne_graues_bild_bleibt_der_rand_wie_er_war(self):
        punkte = [(10.0, 0.0), (0.0, 10.0), (-10.0, 0.0), (0.0, -10.0)]
        self.assertEqual(ST.feinkante(punkte, lambda x, y: 0.0), punkte)

    def test_wo_nichts_zu_sehen_ist_wird_nichts_erfunden(self):
        """Ein flaues Stueck Kante hat keine Mitte zwischen zwei Hoehen -
        dort bleibt der alte Punkt stehen."""
        import math as _m
        kreis = [(100 + 20 * _m.cos(a), 100 + 20 * _m.sin(a))
                 for a in np.linspace(0, 2 * _m.pi, 60, endpoint=False)]
        aus = ST.feinkante(kreis, lambda x, y: np.full(np.shape(x), 128.0))
        for a, b in zip(aus, kreis):
            self.assertAlmostEqual(a[0], b[0], places=6)
            self.assertAlmostEqual(a[1], b[1], places=6)

    def test_die_flaeche_kommt_aus_dem_umriss(self):
        p = [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (0.0, 4.0)]
        self.assertAlmostEqual(ST.polygonflaeche(p), 40.0, places=6)
        self.assertAlmostEqual(ST.polygonflaeche(p[::-1]), 40.0, places=6)
        self.assertEqual(ST.polygonflaeche([(0.0, 0.0), (1.0, 1.0)]), 0.0)


class WasDaliegtWirdGemessen(unittest.TestCase):

    def test_die_scheibe_kommt_in_millimetern_zurueck(self):
        s = finden(bett([("kreis", 70.0, 120.0, 30.0)]))
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["form"], "rund")
        self.assertAlmostEqual(s[0]["mitte"][0], 70.0, delta=0.5)
        self.assertAlmostEqual(s[0]["mitte"][1], 120.0, delta=0.5)
        self.assertAlmostEqual(s[0]["breite"], 60.0, delta=0.6)
        self.assertIsNone(s[0]["winkel"])
        self.assertTrue(s[0]["sicher"])

    def test_y_zeigt_nach_oben(self):
        # Der Fehler, den man am Schirm nicht sieht: eine Scheibe weit
        # hinten darf nicht vorne gemeldet werden.
        hinten = finden(bett([("kreis", 100.0, 160.0, 20.0)]))[0]
        vorne = finden(bett([("kreis", 100.0, 40.0, 20.0)]))[0]
        self.assertGreater(hinten["mitte"][1], vorne["mitte"][1])
        self.assertAlmostEqual(hinten["mitte"][1], 160.0, delta=0.5)

    def test_das_brettchen_behaelt_seine_masse(self):
        s = finden(bett([("rechteck", 40.0, 30.0, 140.0, 90.0)]))
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["form"], "rechteck")
        self.assertAlmostEqual(s[0]["breite"], 100.0, delta=0.6)
        self.assertAlmostEqual(s[0]["hoehe"], 60.0, delta=0.6)
        self.assertAlmostEqual(s[0]["mitte"][0], 90.0, delta=0.5)
        self.assertAlmostEqual(s[0]["mitte"][1], 60.0, delta=0.5)

    def test_schief_eingelegt_steht_der_winkel_dabei(self):
        s = finden(bett([("gedreht", 100.0, 100.0, 90.0, 40.0, 20.0)]))
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["form"], "rechteck")
        self.assertAlmostEqual(s[0]["winkel"], 20.0, delta=1.0)
        self.assertAlmostEqual(s[0]["breite"], 90.0, delta=1.5)
        self.assertAlmostEqual(s[0]["hoehe"], 40.0, delta=1.5)

    def test_acht_untersetzer_werden_acht(self):
        lagen = [(40 + 45 * (i % 4), 60 + 60 * (i // 4)) for i in range(8)]
        s = finden(bett([("kreis", x, y, 18.0) for x, y in lagen]))
        self.assertEqual(len(s), 8)
        self.assertTrue(all(x["form"] == "rund" for x in s))
        self.assertTrue(all(x["sicher"] for x in s))

    def test_abgelesen_wird_von_hinten_nach_vorne(self):
        s = finden(bett([("kreis", 150.0, 50.0, 18.0),
                         ("kreis", 50.0, 150.0, 18.0),
                         ("kreis", 150.0, 150.0, 18.0)]))
        self.assertEqual([x["nr"] for x in s], [1, 2, 3])
        self.assertAlmostEqual(s[0]["mitte"][0], 50.0, delta=1.0)
        self.assertAlmostEqual(s[0]["mitte"][1], 150.0, delta=1.0)
        self.assertAlmostEqual(s[2]["mitte"][1], 50.0, delta=1.0)

    def test_dunkles_auf_hellem_geht_genauso(self):
        s = finden(bett([("kreis", 100.0, 100.0, 30.0, 40)], grund=230))
        self.assertEqual(len(s), 1)
        self.assertAlmostEqual(s[0]["breite"], 60.0, delta=0.6)

    def test_zwei_verschieden_grosse_nebeneinander(self):
        s = finden(bett([("kreis", 50.0, 100.0, 15.0),
                         ("kreis", 140.0, 100.0, 35.0)]))
        self.assertEqual(len(s), 2)
        masse = sorted(round(x["breite"]) for x in s)
        self.assertEqual(masse, [30, 70])


class NichtsIstAuchEineAntwort(unittest.TestCase):

    def test_auf_leerem_bett_nichts(self):
        self.assertEqual(finden(bett([])), [])

    def test_ein_kruemel_ist_kein_werkstueck(self):
        self.assertEqual(finden(bett([("kreis", 100.0, 100.0, 3.0)])), [])

    def test_alles_bedeckt_heisst_untergrund_verfehlt(self):
        # Liegt das Material bis in die Ecken, ist der Bildrand kein
        # Untergrund mehr. Dann lieber nichts sagen.
        self.assertEqual(finden(bett([("rechteck", 0.0, 0.0, 200.0, 200.0)],
                                     grund=40)), [])

    def test_angeschnitten_heisst_unsicher(self):
        s = finden(bett([("rechteck", -20.0, 60.0, 80.0, 140.0)]))
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0]["randlage"])
        self.assertFalse(s[0]["sicher"])

    def test_was_die_kamera_nicht_sah_ist_kein_stueck(self):
        # bett_bild legt Schwarz hin, wo das Objektiv nicht hinreicht.
        # Schwarz hebt sich praechtig ab und ist doch nichts.
        n = int(BETT * PX)
        bild = bett([("kreis", 100.0, 150.0, 25.0)])
        a = np.asarray(bild).copy()
        a[int(n * 0.7):] = 0
        ab = np.ones((n, n), dtype=bool)
        ab[int(n * 0.7):] = False
        s = ST.finden(Image.fromarray(a), MM, 0.0, 0.0, abdeckung=ab)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["form"], "rund")
        self.assertAlmostEqual(s[0]["breite"], 50.0, delta=0.8)

    def test_am_rand_der_abdeckung_gilt_als_angeschnitten(self):
        n = int(BETT * PX)
        bild = bett([("kreis", 100.0, 70.0, 25.0)])
        a = np.asarray(bild).copy()
        ab = np.ones((n, n), dtype=bool)
        ab[int(n * 0.7):] = False          # unten fehlt das Bild
        a[int(n * 0.7):] = 0
        s = ST.finden(Image.fromarray(a), MM, 0.0, 0.0, abdeckung=ab)
        self.assertEqual(len(s), 1)
        self.assertTrue(s[0]["randlage"])
        self.assertFalse(s[0]["sicher"])

    def test_der_kopf_wird_uebersprungen(self):
        b = bett([("kreis", 60.0, 60.0, 25.0),
                  ("rechteck", 150.0, 150.0, 190.0, 190.0)])
        ohne = finden(b)
        self.assertEqual(len(ohne), 2)
        mit = finden(b, sperren=[(140.0, 140.0, 200.0, 200.0)])
        self.assertEqual(len(mit), 1)
        self.assertAlmostEqual(mit[0]["mitte"][0], 60.0, delta=1.0)


class VonHandGesetzt(unittest.TestCase):

    def test_rechteck_von_hand(self):
        s = ST.rechteck_stueck(10.0, 20.0, 60.0, 50.0)
        self.assertEqual(s["form"], "rechteck")
        self.assertEqual(s["mitte"], (35.0, 35.0))
        self.assertEqual((s["breite"], s["hoehe"]), (50.0, 30.0))
        self.assertTrue(s["sicher"])
        self.assertEqual(s["herkunft"], "hand")

    def test_rechteck_auch_rueckwaerts_gezogen(self):
        a = ST.rechteck_stueck(60.0, 50.0, 10.0, 20.0)
        b = ST.rechteck_stueck(10.0, 20.0, 60.0, 50.0)
        self.assertEqual(a["kasten"], b["kasten"])

    def test_kreis_von_hand(self):
        s = ST.kreis_stueck(100.0, 80.0, 25.0)
        self.assertEqual(s["form"], "rund")
        self.assertEqual(s["mitte"], (100.0, 80.0))
        self.assertAlmostEqual(s["breite"], 50.0)
        for x, y in s["umriss"]:
            self.assertAlmostEqual(math.hypot(x - 100.0, y - 80.0), 25.0,
                                   places=6)

    def test_unter_dem_zeiger_gewinnt_das_kleinere(self):
        gross = ST.rechteck_stueck(0.0, 0.0, 100.0, 100.0)
        klein = ST.kreis_stueck(50.0, 50.0, 10.0)
        self.assertIs(ST.unter([gross, klein], 50.0, 50.0), klein)
        self.assertIs(ST.unter([gross, klein], 90.0, 90.0), gross)
        self.assertIsNone(ST.unter([gross, klein], 200.0, 200.0))

    def test_die_mitte_nimmt_den_umriss_mit(self):
        s = ST.kreis_stueck(50.0, 50.0, 10.0)
        n = ST.verschieben(s, 80.0, 20.0)
        self.assertEqual(n["mitte"], (80.0, 20.0))
        self.assertAlmostEqual(n["kasten"][0], 70.0, places=6)
        self.assertAlmostEqual(n["kasten"][1], 10.0, places=6)
        for x, y in n["umriss"]:
            self.assertAlmostEqual(math.hypot(x - 80.0, y - 20.0), 10.0,
                                   places=6)
        self.assertEqual(s["mitte"], (50.0, 50.0))   # das alte bleibt heil


class DieZeileSagtWasDaliegt(unittest.TestCase):

    def test_rund_wird_mit_durchmesser_geschrieben(self):
        z = ST.lesbar(ST.kreis_stueck(100.0, 80.0, 25.0, nr=3))
        self.assertIn("3.", z)
        self.assertIn("rund", z)
        self.assertIn("Ø 50.0 mm", z)
        self.assertIn("100.0", z)

    def test_unsicher_steht_dabei(self):
        s = dict(ST.kreis_stueck(100.0, 80.0, 25.0, nr=1), sicher=False)
        self.assertIn("(unsicher)", ST.lesbar(s))

    def test_sprache_und_zahlen_kommen_von_aussen(self):
        # Die Datei rechnet und soll von der Sprache nichts wissen muessen.
        uebersetzt = {"rund": "round",
                      "{nr}. {form}, {mass}, Mitte X {x} / Y {y}":
                          "{nr}. {form}, {mass}, centre X {x} / Y {y}"}
        z = ST.lesbar(ST.kreis_stueck(100.0, 80.0, 25.0, nr=1),
                      t=lambda s: uebersetzt.get(s, s),
                      zahl=lambda v, n: ("%.1f" % v).replace(".", ","))
        self.assertIn("round", z)
        self.assertIn("centre X 100,0", z)

    def test_die_marke_am_umriss_ist_kurz(self):
        m = ST.marke(ST.rechteck_stueck(0.0, 0.0, 50.0, 30.0, nr=2))
        self.assertTrue(m.startswith("2"))
        self.assertIn("50.0", m)
        self.assertNotIn("Mitte", m)


if __name__ == "__main__":
    unittest.main()
