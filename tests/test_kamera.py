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


class AusMehrerenAufnahmenDieBeste(unittest.TestCase):
    """Die Falcon2-Kamera liefert abwechselnd helle und dunkle Bilder.

    Sechs helle, zwei dunkle, wieder helle - und welches davon das erste
    ist, ist Gluecksache. Mit einer einzigen Aufnahme war das Bildholen
    deshalb eine Lotterie: am 11.11.2026 einmal eine Eichung auf einem
    stockdunklen Bild, einmal kein Werkstueck gefunden, und nichts sagte
    warum. Der Regler fuer die Belichtungszeit hilft dagegen nicht -
    diese Kamera ignoriert ihn.
    """

    def feld(self, a, b, verlust=0.0):
        """Ein Schachbrett aus zwei Helligkeiten, optional mit einem Teil
        ausgebrannter Flaeche."""
        f = np.indices((40, 40)).sum(axis=0) % 2
        aus = np.where(f == 0, a, b).astype(np.uint8)
        if verlust:
            aus[:int(40 * verlust)] = 255
        return Image.fromarray(aus).convert("RGB")

    def test_die_dunkle_verliert(self):
        dunkel = self.feld(3, 8)
        gut = self.feld(60, 200)
        self.assertGreater(K.guete(gut), K.guete(dunkel))
        self.assertIs(K.beste([dunkel, gut]), gut)

    def test_die_ausgebrannte_verliert_auch(self):
        """Das hellste Bild hat am meisten Licht und am wenigsten
        Auskunft - wo alles 255 ist, steht nichts mehr drin."""
        gut = self.feld(60, 200)
        hell = self.feld(200, 255, verlust=0.6)
        self.assertGreater(K.guete(gut), K.guete(hell))
        self.assertIs(K.beste([hell, gut, hell]), gut)

    def test_ohne_aufnahme_kommt_nichts(self):
        self.assertIsNone(K.beste([]))
        self.assertIsNone(K.beste([None]))

    def test_die_reihenfolge_entscheidet_nicht(self):
        dunkel, gut = self.feld(3, 8), self.feld(60, 200)
        self.assertIs(K.beste([gut, dunkel]), gut)
        self.assertIs(K.beste([dunkel, gut]), gut)


class EichungSagtWasSieTaugt(unittest.TestCase):
    """Ein Fehler ohne seine Flaeche ist eine Falle.

    0,43 mm sah nach einer sehr guten Eichung aus - gemessen war das auf
    140 x 100 mm in der Bettmitte, und aussen lag sie um 6,5 mm daneben.
    """

    def test_flaeche_und_punkte_stehen_dabei(self):
        t = K.eichung_lesbar(dict(geraet="/dev/video2", fehler_mm=1.58,
                                    spanne_mm=[340, 340], kreuze=9, dicke=0.0))
        self.assertIn("1.58", t.replace(",", "."))
        self.assertIn("340", t)
        self.assertIn("9 Kreuze", t)

    def test_eine_zahl_ist_eine_spanne(self):
        t = K.eichung_lesbar(dict(geraet="x", fehler_mm=1.0, spanne_mm=340,
                                    kreuze=9))
        self.assertIn("340", t)

    def test_ohne_flaeche_sagt_er_das_auch(self):
        """Aeltere Eichungen haben den Eintrag nicht - dann kein stilles Nichts."""
        t = K.eichung_lesbar(dict(geraet="x", fehler_mm=0.43, aufnahmen=11))
        self.assertIn("nicht vermerkt", t)
        self.assertIn("11 Aufnahmen", t)

    def test_ohne_eichung_keine_zeile(self):
        self.assertEqual(K.eichung_lesbar({}), "")


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


class EichungRechnetBeideRichtungen(unittest.TestCase):
    """Bild -> Maschine und zurueck, mit der echten Eichung der Falcon.

    Die Zahlen hier sind nicht erfunden: k1/k2 und die Homographie kommen
    aus elf Aufnahmen einer Punktekarte, Massstab und Versatz aus neun
    Kreuzen, die der Kopf selbst gebrannt hat.
    """

    EICHUNG = {
        "version": 1, "geraet": "/dev/video2", "bild": [2592, 1944],
        "k1": -0.23393448122459237, "k2": 0.052031199040878155,
        "mitte": [1194.6429467766807, 918.4638899070328], "mass": 1000.0,
        "homographie": [[3.7240564485784344, -0.030451730107427005,
                         1182.5623427582486],
                        [-0.012538438665385381, -3.735576659393299,
                         1094.2779460976224],
                        [3.2004029750511467e-07, -1.9353504670839243e-05,
                         1.0]],
        "massstab": 1.0075305, "drehung": -0.1488,
        "versatz": [191.2, 192.2], "hoehe": 0.0, "dicke": 0.0,
    }

    # Die neun gebrannten Kreuze: Bildpunkt und die Stelle, die der Kopf
    # dafuer angefahren hat.
    KREUZE = [((787.1, 1061.3), (80.0, 200.0)),
              ((1030.8, 1065.5), (150.0, 200.0)),
              ((1288.9, 1064.6), (220.0, 200.0)),
              ((800.4, 1229.9), (80.0, 150.0)),
              ((1035.9, 1241.1), (150.0, 150.0)),
              ((1287.6, 1241.1), (220.0, 150.0)),
              ((814.2, 1387.2), (80.0, 100.0)),
              ((1043.7, 1400.6), (150.0, 100.0)),
              ((1283.8, 1402.5), (220.0, 100.0))]

    def test_bild_wird_zu_millimetern(self):
        px = [p for p, _ in self.KREUZE]
        soll = np.array([m for _, m in self.KREUZE])
        ist = K.bild_nach_maschine(px, self.EICHUNG)
        fehler = np.hypot(*(ist - soll).T)
        self.assertLess(fehler.max(), 1.5, "Eichung sitzt nicht mehr")
        self.assertLess(fehler.mean(), 0.7)

    def test_der_rueckweg_trifft_wieder(self):
        """Hin und zurueck muss am selben Punkt ankommen."""
        px = np.array([p for p, _ in self.KREUZE])
        mm = K.bild_nach_maschine(px, self.EICHUNG)
        zurueck = K.maschine_nach_bild(mm, self.EICHUNG)
        self.assertLess(np.hypot(*(zurueck - px).T).max(), 0.5)

    def test_ohne_hoehe_aendert_die_dicke_nichts(self):
        """hoehe 0 heisst 'nicht herausrechnen' - und darf nicht heimlich
        doch etwas verschieben."""
        mm = [(150.0, 150.0), (80.0, 200.0)]
        a = K.maschine_nach_bild(mm, self.EICHUNG, dicke=0.0)
        b = K.maschine_nach_bild(mm, self.EICHUNG, dicke=18.0)
        self.assertLess(np.abs(a - b).max(), 1e-9)

    def test_dickes_material_rueckt_nach_aussen(self):
        """Mit bekannter Kamerahoehe schiebt die Dicke vom Lotpunkt weg."""
        e = dict(self.EICHUNG, hoehe=300.0)
        lot = K._nadir(e)
        fern = K.bild_nach_maschine([[300.0, 1700.0]], e)[0]
        a = K.maschine_nach_bild([fern], e, dicke=0.0)[0]
        b = K.maschine_nach_bild([fern], e, dicke=20.0)[0]
        mitte = K.maschine_nach_bild([K.bild_nach_maschine([e["mitte"]], e)[0]],
                                     e, dicke=20.0)[0]
        self.assertGreater(np.hypot(*(b - a)), 5.0)
        # der Lotpunkt selbst bleibt stehen
        self.assertLess(np.hypot(*(mitte - np.array(e["mitte"]))), 1.0)
        self.assertEqual(len(lot), 2)

    def test_bettbild_hat_die_verlangte_groesse(self):
        bild = Image.new("RGB", (2592, 1944), (30, 30, 30))
        aus = K.bett_bild(bild, self.EICHUNG, 0, 0, 300, 200, px_je_mm=2.0)
        self.assertEqual(aus.size, (600, 400))
