"""
Der Materialtest: ein Raster aus Feldern mit ihren Zahlen daneben.

Geprueft wird, was man dem fertigen Brettchen nicht mehr ansieht: dass
die Felder dort liegen, wo die Ausgabe es sagt, dass die Beschriftung
ueberhaupt sichtbar wird, und dass die Energierechnung stimmt - denn
genau die ist der Zweck der ganzen Uebung.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

from hilfe import WURZEL

SKRIPT = os.path.join(WURZEL, "materialtest.py")
sys.path.insert(0, WURZEL)
import materialtest as M                                      # noqa: E402


def erzeugen(*args):
    ziel = os.path.join(tempfile.mkdtemp(prefix="mtest-"), "t.nc")
    aus = subprocess.run([sys.executable, SKRIPT, "--ziel", ziel] + list(args),
                         capture_output=True, text=True, timeout=120)
    assert aus.returncode == 0, aus.stderr
    with open(ziel) as h:
        return h.read().splitlines(), aus.stdout


class DasRasterStimmt(unittest.TestCase):

    def punkte(self, zeilen):
        x = y = 0.0
        raus = []
        for z in zeilen:
            mx = re.search(r"X(-?[\d.]+)", z)
            my = re.search(r"Y(-?[\d.]+)", z)
            if not (mx or my):
                continue
            x = float(mx.group(1)) if mx else x
            y = float(my.group(1)) if my else y
            if z.startswith(("G0", "G1")):
                raus.append((x, y))
        return raus

    def test_alles_liegt_in_der_angesagten_flaeche(self):
        """Die Ausgabe sagt eine Flaeche an - danach legt man das Brettchen."""
        zeilen, text = erzeugen("--x", "30", "--y", "25")
        m = re.search(r"X\s*([\d.]+)\.\.([\d.]+)\s+Y\s*([\d.]+)\.\.([\d.]+)", text)
        self.assertTrue(m, text)
        x0, x1, y0, y1 = (float(g) for g in m.groups())
        for px, py in self.punkte(zeilen):
            if (px, py) == (0.0, 0.0):
                continue                      # die Heimfahrt am Ende
            self.assertTrue(x0 - 0.01 <= px <= x1 + 0.01, "X %.2f" % px)
            self.assertTrue(y0 - 0.01 <= py <= y1 + 0.01, "Y %.2f" % py)

    def test_der_ursprung_wird_beachtet(self):
        a, _ = erzeugen("--x", "20", "--y", "20")
        b, _ = erzeugen("--x", "70", "--y", "20")
        ax = min(p[0] for p in self.punkte(a) if p != (0.0, 0.0))
        bx = min(p[0] for p in self.punkte(b) if p != (0.0, 0.0))
        self.assertAlmostEqual(bx - ax, 50.0, delta=0.01)

    def test_jedes_feld_kommt_mit_seinen_werten_vor(self):
        zeilen, _ = erzeugen("--s", "200,400", "--f", "1000,3000")
        text = "\n".join(zeilen)
        for s in (200, 400):
            for f in (1000, 3000):
                self.assertIn("S%d F%d" % (s, f), text,
                              "S%d/F%d fehlt" % (s, f))

    def test_die_tabelle_rechnet_wie_lw_job(self):
        import lw_job as J
        for s, f, watt in ((300, 1000, 22.0), (830, 1000, 5.5), (50, 600, 22.0)):
            self.assertAlmostEqual(M.energie(s, f, watt, 1000.0),
                                   J.energie(s, f, 1, watt), places=9)

    def test_die_beschriftung_ist_sichtbar(self):
        """Ein fester Anteil von Smax waere an 22 W 0,011 J/mm - auf Holz
        nicht zu sehen. Gerechnet wird deshalb aus einer Zielenergie."""
        _z, text = erzeugen("--watt", "22")
        m = re.search(r"Beschriftung laeuft mit S(\d+)/F(\d+) = ([\d.]+)", text)
        self.assertTrue(m, text)
        self.assertGreater(float(m.group(3)), 0.066)

    def test_an_einer_schwaecheren_maschine_steht_mehr_S_da(self):
        _z, stark = erzeugen("--watt", "22")
        _z, schwach = erzeugen("--watt", "5.5")
        a = int(re.search(r"Beschriftung laeuft mit S(\d+)", stark).group(1))
        b = int(re.search(r"Beschriftung laeuft mit S(\d+)", schwach).group(1))
        self.assertGreater(b, a * 2)

    def test_der_strichfont_kennt_alle_ziffern(self):
        for c in "0123456789":
            self.assertTrue(M.zeichen(c, 0, 0, 3.0), "Ziffer %s fehlt" % c)

    def test_ohne_laser_faehrt_er_nicht_quer_durchs_bild(self):
        """Zwischen zwei Feldern muss M5 stehen - sonst zieht er einen
        Strich von einem zum naechsten."""
        zeilen, _ = erzeugen("--s", "300", "--f", "1000,3000")
        i = [k for k, z in enumerate(zeilen) if z.startswith("G0 X")]
        for k in i:
            self.assertTrue(any(zeilen[j].startswith("M5")
                                for j in range(max(0, k - 3), k)),
                            "vor %r steht kein M5" % zeilen[k])


class InDenVorhandenenPlatzEinpassen(unittest.TestCase):
    """--platz 80x40: der Benutzer sagt, was er hat, nicht was er rechnen
    soll."""

    def flaeche(self, text):
        m = re.search(r"\((\d+\.\d) x (\d+\.\d) mm\)", text)
        self.assertTrue(m, text)
        return float(m.group(1)), float(m.group(2))

    def test_es_passt_und_nutzt_den_platz(self):
        _z, text = erzeugen("--platz", "80x40", "--x", "10", "--y", "10")
        b, h = self.flaeche(text)
        self.assertLessEqual(b, 80.01)
        self.assertLessEqual(h, 40.01)
        self.assertGreater(b, 78.0, "die Breite bleibt liegen")
        self.assertGreater(h, 38.0, "die Hoehe bleibt liegen")

    def test_felder_duerfen_laenglich_sein(self):
        """Sonst begrenzt die knappere Richtung beide und die halbe
        Flaeche bleibt liegen."""
        ss, ff, fb, fh, _l, _s = M.einpassen([1, 2, 3, 4, 5],
                                             [1, 2, 3, 4, 5], 80.0, 40.0)
        self.assertEqual((len(ss), len(ff)), (5, 5))
        self.assertGreater(fb, fh * 1.5)

    def test_auf_wenig_platz_fallen_werte_weg(self):
        ss, ff, fb, fh, _l, _s = M.einpassen(
            [1, 2, 3, 4, 5, 6, 7], [1, 2, 3, 4, 5, 6, 7], 40.0, 25.0)
        self.assertLess(len(ff), 7)
        self.assertGreaterEqual(min(fb, fh), 3.0)

    def test_die_raender_bleiben_erhalten(self):
        """Dort sieht man, ob der Bereich ueberhaupt richtig gewaehlt war."""
        duenn = M._ausduennen([100, 300, 500, 700, 900])
        self.assertEqual(duenn[0], 100)
        self.assertEqual(duenn[-1], 900)

    def test_zu_wenig_platz_sagt_es_statt_unsinn_zu_bauen(self):
        with self.assertRaises(SystemExit):
            M.einpassen([1, 2], [1, 2], 12.0, 8.0)


if __name__ == "__main__":
    unittest.main()
