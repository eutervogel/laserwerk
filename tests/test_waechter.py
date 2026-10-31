"""
Der Waechter, der einem langen Job von aussen zusieht.

Geprueft wird vor allem, dass er die richtigen Schluesse aus den
Anzeigetexten zieht - und zwei Dinge, die weh tun, wenn sie falsch sind:

  * Er darf nur das eigene Programm beobachten. Eine Vorwarnung aus einem
    fremden Tk-Fenster waere schlimmer als keine.
  * Er darf bei Telegram niemals getUpdates rufen. Das darf nur der Bot in
    der laufenden Oberflaeche; zwei Abholer nehmen sich die Nachrichten weg.

Es wird nichts gesendet, kein Port geoeffnet und nichts an die Maschine
gegeben.
"""
import json
import os
import tempfile
import unittest

from hilfe import ohne_bildschirm                             # noqa: F401
import waechter as W


# So steht es wirklich in der Oberflaeche, waehrend ein Job laeuft.
ECHT = ["Arbeitsbereich (295 x 180 mm, Nullpunkt unten links)",
        "/dev/ttyUSB1  |  Run  |  Vorschub 1000  Leistung 0",
        "Zeile 123 von 1599",
        "6 %   noch ~623 min",
        "Nullpunkt: gesetzt   Z-Ref: gültig",
        "Materialdicke",
        "Vorschau + G-Code erzeugen",
        "'Leistung ab' ist die kleinste Leistung, bei der das\n"
        "Material überhaupt zeichnet. Graustufen werden dann\n"
        "zwischen diesen beiden Werten verteilt statt zwischen\n"
        "30 % und S. Für Strichgrafik ohne Bedeutung."]


class Deuten(unittest.TestCase):

    def test_zeile(self):
        d = W.deuten(ECHT)
        self.assertEqual((d["art"], d["nr"], d["gesamt"]), ("zeile", 123, 1599))
        self.assertEqual(d["marke"], "Zeile 123 von 1599")

    def test_fortschritt_genau(self):
        """Der Hilfetext enthaelt '30 %' - er darf das Feld nicht kapern."""
        d = W.deuten(ECHT)
        self.assertEqual(d["prog"], "6 %   noch ~623 min")
        self.assertEqual((d["prozent"], d["restmin"]), (6, 623))

    def test_zustand(self):
        self.assertEqual(W.deuten(ECHT)["zustand"], "Run")

    def test_kontur(self):
        d = W.deuten(["Kontur 3 von 12"])
        self.assertEqual((d["art"], d["nr"], d["gesamt"]), ("kontur", 3, 12))

    def test_knopf_ist_keine_marke(self):
        """Die Knoepfe heissen 'Kontur' und 'Rahmen' - ohne Zahlen."""
        self.assertIsNone(W.deuten(["Kontur", "Rahmen", "Start"])["art"])

    def test_englisch(self):
        d = W.deuten(["Row 7 of 40", "6 %   ~626 min left",
                      "/dev/ttyUSB1  |  Run  |  Feed 1000  Power 0"])
        self.assertEqual((d["art"], d["nr"], d["gesamt"]), ("zeile", 7, 40))
        self.assertEqual((d["prozent"], d["restmin"]), (6, 626))
        self.assertEqual(d["zustand"], "Run")

    def test_jobende(self):
        for t in ("Hunde.svg: fertig",
                  "Hunde.svg: abgebrochen (Laser aus)",
                  "Hunde.svg: ALARM - gestoppt",
                  "Hunde.svg: Verbindung verloren",
                  "Hunde.svg: zu viele Übertragungsfehler"):
            self.assertEqual(W.deuten([t])["schluss"], t, t)

    def test_leer(self):
        d = W.deuten([])
        self.assertIsNone(d["art"])
        self.assertEqual((d["marke"], d["prog"], d["schluss"]), ("", "", ""))


class Erkennen(unittest.TestCase):

    def test_echtes_fenster(self):
        self.assertTrue(W.erkannt(ECHT))

    def test_ein_merkmal_genuegt_nicht(self):
        """Ein fremdes Fenster, in dem zufaellig 'Nullpunkt' steht, ist
        noch kein Laserwerk."""
        self.assertFalse(W.erkannt(["Nullpunkt: gesetzt", "Zeile 5 von 30"]))

    def test_fremdes_fenster(self):
        self.assertFalse(W.erkannt(["Datei", "Bearbeiten", "Hilfe"]))

    def test_zwei_merkmale(self):
        self.assertTrue(W.erkannt(["Nullpunkt: gesetzt", "Materialdicke"]))


class Hochrechnen(unittest.TestCase):

    def test_zu_kurz_gemessen(self):
        """Lieber keine Schaetzung als eine aus drei Sekunden."""
        self.assertIsNone(W.rate([(1000.0, 10), (1003.0, 11)]))

    def test_eine_probe(self):
        self.assertIsNone(W.rate([(1000.0, 10)]))

    def test_steht(self):
        self.assertIsNone(W.rate([(1000.0, 10), (1600.0, 10)]))

    def test_rueckwaerts(self):
        """Neuer Job, Zaehler faengt wieder vorn an - nicht hochrechnen."""
        self.assertIsNone(W.rate([(1000.0, 500), (1600.0, 3)]))

    def test_rate(self):
        # 100 Zeilen in 2400 s = 24 s pro Zeile
        r = W.rate([(1000.0, 100), (3400.0, 200)])
        self.assertAlmostEqual(1 / r, 24.0, places=6)

    def test_restzeit(self):
        r = W.rate([(1000.0, 100), (3400.0, 200)])
        self.assertAlmostEqual((1599 - 200) / r, 1399 * 24.0, places=3)

    def test_dauer(self):
        self.assertEqual(W.dauer(None), "?")
        self.assertEqual(W.dauer(45), "45 s")
        self.assertEqual(W.dauer(600), "10 min")

    def test_uhrzeit_leer(self):
        self.assertEqual(W.uhrzeit(None), "")

    def test_uhrzeit(self):
        self.assertRegex(W.uhrzeit(600), r"^ \(gegen \d\d:\d\d\)$")


class Registry(unittest.TestCase):
    """Die Liste der Tk-Interpreter kommt aus xprop."""

    def setUp(self):
        self.echt = W.subprocess.run
        self.addCleanup(setattr, W.subprocess, "run", self.echt)

    def _xprop(self, zeile):
        class Aus:
            stdout = zeile
        W.subprocess.run = lambda *a, **k: Aus()

    def test_zwei(self):
        self._xprop('InterpRegistry(STRING) = "3c00007 tk #2", "2e00007 tk"\n')
        self.assertEqual(W.interps(), ["tk #2", "tk"])

    def test_einer(self):
        self._xprop('InterpRegistry(STRING) = "2e00007 tk"\n')
        self.assertEqual(W.interps(), ["tk"])

    def test_keiner(self):
        self._xprop("InterpRegistry:  not found.\n")
        self.assertEqual(W.interps(), [])


class Telegram(unittest.TestCase):

    def setUp(self):
        self.verz = tempfile.mkdtemp(prefix="laserwerk-test-")
        self.datei = os.path.join(self.verz, "telegram.json")
        self.alt = W.TELEGRAMDATEI
        W.TELEGRAMDATEI = self.datei
        self.addCleanup(setattr, W, "TELEGRAMDATEI", self.alt)

    def _schreib(self, d):
        with open(self.datei, "w", encoding="utf-8") as f:
            json.dump(d, f)

    def test_zugang(self):
        self._schreib({"token": "123:abc", "chat": 42})
        self.assertEqual(W.zugang(), ("123:abc", 42))

    def test_ohne_chat(self):
        """Ohne verknuepften Chat gibt es nichts zu melden - und das soll
        beim Start auffallen, nicht erst in zehn Stunden."""
        self._schreib({"token": "123:abc", "chat": None})
        self.assertRaises(SystemExit, W.zugang)

    def test_ohne_token(self):
        self._schreib({"token": "", "chat": 42})
        self.assertRaises(SystemExit, W.zugang)


class NurSenden(unittest.TestCase):
    """Niemals getUpdates: das wuerde dem Bot in der laufenden Oberflaeche
    die Nachrichten wegnehmen (HTTP 409)."""

    def setUp(self):
        self.gerufen = []

        class Antwort:
            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(url, data=None, timeout=None):
            self.gerufen.append((url, data))
            return Antwort()

        self.alt = W.urllib.request.urlopen
        W.urllib.request.urlopen = fake
        self.addCleanup(setattr, W.urllib.request, "urlopen", self.alt)

    def test_sendet(self):
        self.assertTrue(W.senden("123:abc", 42, "Zeilen fast durch"))
        url, daten = self.gerufen[0]
        self.assertTrue(url.endswith("/sendMessage"))
        self.assertIn(b"chat_id=42", daten)
        self.assertIn(b"Zeilen+fast+durch", daten)

    def test_kein_getupdates(self):
        W.senden("123:abc", 42, "egal")
        self.assertFalse(any("getUpdates" in u for u, _ in self.gerufen))

    def test_scheitert_leise(self):
        """Ein Netzaussetzer darf den Waechter nicht beenden."""
        def kaputt(*a, **k):
            raise OSError("kein Netz")
        W.urllib.request.urlopen = kaputt
        self.assertFalse(W.senden("123:abc", 42, "egal", versuche=1))


@ohne_bildschirm
class UeberDieSchulter(unittest.TestCase):
    """Der Blick in einen fremden Tk-Interpreter, einmal richtig."""

    def setUp(self):
        import tkinter as tk
        self.r = tk.Tk()
        self.r.withdraw()
        for t in ("Nullpunkt: gesetzt   Z-Ref: gültig", "Materialdicke",
                  "Zeile 123 von 1599", "6 %   noch ~623 min"):
            tk.Label(self.r, text=t).pack()
        self.r.update()
        self.name = self.r.tk.call("tk", "appname")
        self.addCleanup(self.r.destroy)

    def test_liest_die_felder(self):
        texte = W.lese_direkt(self.name)
        self.assertIn("Zeile 123 von 1599", texte)
        self.assertTrue(W.erkannt(texte))
        d = W.deuten(texte)
        self.assertEqual((d["art"], d["nr"], d["gesamt"]), ("zeile", 123, 1599))

    def test_aendert_nichts(self):
        """Der Blick ist lesend: danach steht da, was vorher dastand."""
        vorher = [w.cget("text") for w in self.r.winfo_children()]
        W.lese_direkt(self.name)
        self.assertEqual([w.cget("text") for w in self.r.winfo_children()],
                         vorher)


if __name__ == "__main__":
    unittest.main()
