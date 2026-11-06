"""
Die Dialoge laufen ueber zenity, damit sie wie der Rest des Schreibtischs
aussehen. Geprueft wird hier ohne zenity: was das Programm aufruft, muss es
geben, und was zenity antwortet, muss richtig gedeutet werden.
"""
import ast
import os
import unittest

from hilfe import WURZEL
import lw_dialog as D


class WasGerufenWirdGibtEs(unittest.TestCase):
    """laserwerk ruft die Dialoge namentlich auf. Fehlt einer, faellt das
    erst in dem Moment auf, in dem er gebraucht wird - askyesnocancel
    fehlte und riss die Warnung vor ungleichen Schnittwerten mit, also
    genau die Stelle, an der nichts schiefgehen darf."""

    def gerufene(self):
        namen = set()
        for datei in sorted(os.listdir(WURZEL)):
            if not datei.endswith(".py") or datei == "lw_dialog.py":
                continue
            with open(os.path.join(WURZEL, datei)) as f:
                baum = ast.parse(f.read())
            for k in ast.walk(baum):
                if (isinstance(k, ast.Attribute)
                        and isinstance(k.value, ast.Name)
                        and k.value.id in ("messagebox", "filedialog")):
                    namen.add((datei, k.value.id, k.attr))
        return namen

    def test_jeder_aufruf_hat_sein_gegenstueck(self):
        gefunden = self.gerufene()
        self.assertTrue(gefunden, "keine Dialogaufrufe gefunden")
        for datei, modul, name in sorted(gefunden):
            self.assertTrue(
                hasattr(getattr(D, modul), name),
                "%s ruft %s.%s - das gibt es in lw_dialog nicht"
                % (datei, modul, name))


class DreiAntworten(unittest.TestCase):
    """Ja, nein, abbrechen. zenity kennt nur zwei Knoepfe; der dritte geht
    als Zusatzknopf und meldet sich ueber seine Beschriftung."""

    def setUp(self):
        self.echt_z, self.echt_zenity = D._z, D.ZENITY
        D.ZENITY = "/bin/true"
        self.args = []

    def tearDown(self):
        D._z, D.ZENITY = self.echt_z, self.echt_zenity

    def antwort(self, rc, aus=""):
        def z(args):
            self.args = args
            return rc, aus
        D._z = z

    def test_ja(self):
        self.antwort(0)
        self.assertIs(D.messagebox.askyesnocancel("T", "Text"), True)

    def test_nein_kommt_ueber_die_ausgabe(self):
        self.antwort(1, "Nein")
        self.assertIs(D.messagebox.askyesnocancel("T", "Text"), False)

    def test_abbrechen_ist_none(self):
        """None heisst 'nichts tun' - das darf nicht als 'nein' durchgehen,
        sonst erzeugt ein Abbruch trotzdem den G-Code."""
        self.antwort(1, "")
        self.assertIsNone(D.messagebox.askyesnocancel("T", "Text"))

    def test_der_dritte_knopf_ist_dabei(self):
        self.antwort(0)
        D.messagebox.askyesnocancel("T", "Text")
        self.assertIn("--extra-button=Nein", self.args)
        self.assertIn("--ok-label=Ja", self.args)


class MehrereDateien(unittest.TestCase):
    def setUp(self):
        self.echt_z, self.echt_zenity = D._z, D.ZENITY
        D.ZENITY = "/bin/true"
        # hilfe.py haengt eine Attrappe an die Instanz, damit kein Test aus
        # Versehen ein echtes Fenster oeffnet. Hier ist die echte Methode
        # der Prueflling, also kommt die Attrappe solange weg.
        self.attrappe = D.filedialog.__dict__.pop("askopenfilenames", None)

    def tearDown(self):
        D._z, D.ZENITY = self.echt_z, self.echt_zenity
        if self.attrappe is not None:
            D.filedialog.askopenfilenames = self.attrappe

    def antwort(self, rc, aus=""):
        self.args = []

        def z(args):
            self.args = args
            return rc, aus
        D._z = z

    def test_eine_datei_je_zeile(self):
        self.antwort(0, "/tmp/a.svg\n/tmp/b mit Luecke.svg\n")
        self.assertEqual(D.filedialog.askopenfilenames(title="x"),
                         ("/tmp/a.svg", "/tmp/b mit Luecke.svg"))
        self.assertIn("--multiple", self.args)

    def test_abbrechen_gibt_nichts_zurueck(self):
        """Ein leeres Tupel, keine leere Zeichenkette: der Aufrufer laeuft
        darueber hinweg."""
        self.antwort(1, "")
        self.assertEqual(D.filedialog.askopenfilenames(title="x"), ())


if __name__ == "__main__":
    unittest.main()
