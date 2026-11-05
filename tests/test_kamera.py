"""
Kamerabild auf Maschinenkoordinaten - ohne Kamera geprueft.

Die Maschine mit Kamera ist noch nicht da. Pruefbar ist trotzdem das
Stueck, das nicht an ihr haengt: die Abbildung von vier Punkten auf vier
Punkte. Dafuer wird ein Bild mit bekannten Marken absichtlich verzerrt und
danach zurueckgerechnet - kommen die Marken dort heraus, wo sie in
Millimetern hingehoeren, stimmt die Rechnung.
"""
import unittest

import numpy as np
from PIL import Image

from hilfe import WURZEL                                      # noqa: F401
import lw_kamera as K


def marke(bild, x, y, r=6, farbe=(255, 0, 0)):
    """Ein ausgefuelltes Quadrat als Marke - gross genug, um es nach dem
    Entzerren wiederzufinden."""
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            if 0 <= x + dx < bild.width and 0 <= y + dy < bild.height:
                bild.putpixel((x + dx, y + dy), farbe)


def schwerpunkt(bild, kanal=0):
    """Wo liegt das Rote im Bild? Mittelwert aller kraeftig roten Punkte."""
    a = np.asarray(bild).astype(int)
    treffer = (a[:, :, kanal] > 150) & (a[:, :, 1] < 110) & (a[:, :, 2] < 110)
    ys, xs = np.nonzero(treffer)
    if not len(xs):
        return None
    return float(xs.mean()), float(ys.mean())


class VierPunkteAufVierPunkte(unittest.TestCase):
    def test_koeffizienten_treffen_die_ecken(self):
        """Die Homographie geht exakt durch ihre vier Stuetzpunkte."""
        ziel = [(0, 0), (100, 0), (100, 50), (0, 50)]
        quelle = [(10, 20), (210, 5), (200, 120), (30, 100)]
        a, b, c, d, e, f, g, h = K.homographie(ziel, quelle)
        for (x, y), (u, v) in zip(ziel, quelle):
            n = g * x + h * y + 1
            self.assertAlmostEqual((a * x + b * y + c) / n, u, places=6)
            self.assertAlmostEqual((d * x + e * y + f) / n, v, places=6)

    def test_drei_punkte_sind_zu_wenig(self):
        with self.assertRaises(ValueError):
            K.homographie([(0, 0), (1, 0), (1, 1)], [(0, 0), (1, 0), (1, 1)])

    def test_punkte_auf_einer_linie_gehen_nicht(self):
        gerade = [(0, 0), (1, 1), (2, 2), (3, 3)]
        with self.assertRaises(ValueError):
            K.homographie(gerade, gerade)


class EntzerrenRechnetInMillimeter(unittest.TestCase):
    """Ein schraeg stehendes Kamerabild wird zur Draufsicht, in der ein
    Bildpunkt eine feste Anzahl Millimeter ist."""

    def kamerabild(self):
        """Vier Marken, wie sie eine schraeg haengende Kamera sieht, und wo
        sie in Maschinenkoordinaten liegen."""
        im = Image.new("RGB", (640, 480), (40, 40, 40))
        # Absichtlich unsymmetrisch: eine Kamera sitzt nie gerade darueber.
        px = [(80, 400), (560, 430), (520, 90), (120, 60)]
        mm = [(20.0, 20.0), (220.0, 20.0), (220.0, 160.0), (20.0, 160.0)]
        for x, y in px:
            marke(im, x, y)
        return im, px, mm

    def test_marken_landen_auf_ihren_millimetern(self):
        im, px, mm = self.kamerabild()
        for i, (mx, my) in enumerate(mm):
            einzeln = Image.new("RGB", im.size, (40, 40, 40))
            marke(einzeln, *px[i])
            # Mit Rand, sonst liegt jede Marke genau auf einer Ecke des
            # Ergebnisses und wird zur Haelfte abgeschnitten - ihr
            # Schwerpunkt waere dann nach innen verschoben.
            aus, x0, y0, skala = K.entzerren(einzeln, px, mm, mm_je_px=0.25,
                                             rand=6.0)
            s = schwerpunkt(aus)
            self.assertIsNotNone(s, "Marke %d verschwunden" % i)
            self.assertAlmostEqual(x0 + s[0] * skala, mx, delta=0.6)
            # Y zeigt in der Maschine nach oben, im Bild nach unten
            self.assertAlmostEqual(y0 + (aus.height - s[1]) * skala, my,
                                   delta=0.6)

    def test_groesse_folgt_der_flaeche_und_der_skala(self):
        im, px, mm = self.kamerabild()
        aus, x0, y0, skala = K.entzerren(im, px, mm, mm_je_px=0.5)
        self.assertEqual((x0, y0), (20.0, 20.0))
        self.assertEqual(aus.width, 400)        # 200 mm / 0,5
        self.assertEqual(aus.height, 280)       # 140 mm / 0,5
        feiner, _, _, _ = K.entzerren(im, px, mm, mm_je_px=0.25)
        self.assertEqual(feiner.width, 800)

    def test_rand_gibt_luft_um_die_punkte(self):
        im, px, mm = self.kamerabild()
        ohne, x0, _, _ = K.entzerren(im, px, mm, mm_je_px=0.5)
        mit, x0r, _, _ = K.entzerren(im, px, mm, mm_je_px=0.5, rand=10.0)
        self.assertEqual(x0r, x0 - 10.0)
        self.assertEqual(mit.width, ohne.width + 40)

    def test_unsinnige_skala_wird_abgelehnt(self):
        im, px, mm = self.kamerabild()
        with self.assertRaises(ValueError):
            K.entzerren(im, px, mm, mm_je_px=0.0)


class EichungMisstSichSelbst(unittest.TestCase):
    """Vier Punkte sagen nichts ueber die Guete - durch vier Punkte geht
    immer eine Homographie. Erst ein fuenfter prueft sie."""

    def test_vier_punkte_messen_nichts(self):
        px = [(80, 400), (560, 430), (520, 90), (120, 60)]
        mm = [(20.0, 20.0), (220.0, 20.0), (220.0, 160.0), (20.0, 160.0)]
        self.assertEqual(K.eichung_pruefen(px, mm), 0.0)

    def test_fuenfter_punkt_deckt_den_fehler_auf(self):
        ziel = [(20.0, 20.0), (220.0, 20.0), (220.0, 160.0), (20.0, 160.0)]
        skala = 0.25
        px = [(80, 400), (560, 430), (520, 90), (120, 60)]
        a, b, c, d, e, f, g, h = K.homographie(
            [(x / skala, y / skala) for x, y in ziel], px)
        # Ein fuenfter Punkt, genau auf der Abbildung: Fehler null.
        mx, my = 120.0, 90.0
        x, y = mx / skala, my / skala
        n = g * x + h * y + 1
        passt = ((a * x + b * y + c) / n, (d * x + e * y + f) / n)
        self.assertLess(K.eichung_pruefen(px + [passt], ziel + [(mx, my)],
                                          skala), 0.01)
        # Derselbe Punkt 12 Bildpunkte daneben: der Fehler wird gemeldet.
        schief = (passt[0] + 12.0, passt[1])
        self.assertAlmostEqual(
            K.eichung_pruefen(px + [schief], ziel + [(mx, my)], skala),
            12.0 * skala, delta=0.01)


class WerkstueckImBild(unittest.TestCase):
    """Damit ein Kamerabild mehr ist als eine Kontrolle, muss Laserwerk
    sagen koennen, wo das Brettchen liegt und wie schief - sonst schiebt
    man das Motiv weiter von Hand und schaut dabei auf ein Foto."""

    def brett(self, b=120, h=60, winkel=0.0, mitte=(200, 120), unter=60,
              drauf=210, groesse=(400, 300)):
        """Ein helles Brettchen auf dunklem Bett, beliebig gedreht."""
        im = Image.new("L", groesse, unter)
        stueck = Image.new("L", (b, h), drauf)
        if winkel:
            stueck = stueck.rotate(winkel, expand=True, fillcolor=unter)
        im.paste(stueck, (mitte[0] - stueck.width // 2,
                          mitte[1] - stueck.height // 2))
        return im.convert("RGB")

    def test_findet_den_kasten_in_millimetern(self):
        # 0,5 mm je Bildpunkt, linke untere Ecke bei (10, 20) mm
        w = K.werkstueck(self.brett(), 10.0, 20.0, 0.5)
        self.assertIsNotNone(w)
        self.assertAlmostEqual(w["breite"], 120 * 0.5, delta=2.0)
        self.assertAlmostEqual(w["hoehe"], 60 * 0.5, delta=2.0)
        # Bildmitte (200, 120) von 400 x 300 -> x = 10 + 100, y = 20 + 90
        self.assertAlmostEqual((w["x0"] + w["x1"]) / 2, 110.0, delta=1.0)
        self.assertAlmostEqual((w["y0"] + w["y1"]) / 2, 110.0, delta=1.0)

    def test_y_zaehlt_wie_in_der_maschine(self):
        """Oben im Bild ist das groesste Y, nicht das kleinste."""
        oben = K.werkstueck(self.brett(mitte=(200, 60)), 0.0, 0.0, 0.5)
        unten = K.werkstueck(self.brett(mitte=(200, 240)), 0.0, 0.0, 0.5)
        self.assertGreater(oben["y0"], unten["y0"])

    def test_winkel_eines_schiefen_bretts(self):
        for soll in (-30.0, -12.0, 0.0, 17.0, 35.0):
            w = K.werkstueck(self.brett(winkel=soll), 0.0, 0.0, 0.5)
            self.assertIsNotNone(w["winkel"], "kein Winkel bei %g" % soll)
            self.assertAlmostEqual(w["winkel"], soll, delta=2.5,
                                   msg="Winkel %g" % soll)

    def test_quadrat_hat_keinen_winkel(self):
        """Ein Quadrat hat keine lange Seite - dann ist None ehrlicher als
        eine Zahl, die nur aussieht wie eine Antwort."""
        w = K.werkstueck(self.brett(b=100, h=100), 0.0, 0.0, 0.5)
        self.assertIsNotNone(w)
        self.assertIsNone(w["winkel"])

    def test_leeres_bett_meldet_nichts(self):
        leer = Image.new("RGB", (400, 300), (60, 60, 60))
        self.assertIsNone(K.werkstueck(leer, 0.0, 0.0, 0.5))

    def test_kruemel_sind_kein_werkstueck(self):
        im = self.brett(b=3, h=3)
        self.assertIsNone(K.werkstueck(im, 0.0, 0.0, 0.5))

    def test_dunkles_stueck_auf_hellem_bett_geht_auch(self):
        im = self.brett(unter=230, drauf=40)
        w = K.werkstueck(im, 0.0, 0.0, 0.5)
        self.assertIsNotNone(w)
        self.assertAlmostEqual(w["breite"], 60.0, delta=2.0)


class Geraete(unittest.TestCase):
    def test_kameras_liefert_eine_liste(self):
        """Ohne Kamera eine leere Liste, mit Kamera Paare aus Geraet und
        Name - abstuerzen darf es in keinem Fall."""
        for g, name in K.kameras():
            self.assertTrue(g.startswith("/dev/video"))
            self.assertIsInstance(name, str)

    def test_bild_von_einem_falschen_geraet_wirft(self):
        with self.assertRaises(RuntimeError):
            K.bild_holen("/dev/video-gibt-es-nicht", timeout=8)


if __name__ == "__main__":
    unittest.main()
