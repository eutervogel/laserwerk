"""
Oberflaeche mit unsichtbarem Fenster und Maschinenattrappe.

Hier stehen die Faelle, die im Betrieb wehgetan haben: der Nullpunkt, der
den STOPP nicht ueberlebte; die Grenzpruefung, die ueber die blosse Spanne
ging; Leistungen, die auf einer fremden Maschine viermal zu hoch gewesen
waeren; Beschriftungen, die sich gegenseitig verdeckten.

Ohne Anzeige werden diese Tests uebersprungen.
"""
import unittest

import numpy as np
from PIL import Image

from hilfe import (ohne_bildschirm, app_bauen, app_schliessen,
                   Attrappe)                                  # noqa: F401
import lw_job as J


@ohne_bildschirm
class Grundlage(unittest.TestCase):
    def setUp(self):
        self.wurzel, self.app, self.L = app_bauen()
        self.app.zero_ok = True
        self.gezeigt = []
        self.L.messagebox.showerror = lambda t, m: self.gezeigt.append(("!", m))
        self.L.messagebox.showinfo = lambda t, m: self.gezeigt.append(("i", m))
        self.L.messagebox.showwarning = lambda t, m: self.gezeigt.append(("w", m))
        self.L.messagebox.askokcancel = lambda t, m: True
        self.L.messagebox.askyesno = lambda t, m: True

    def tearDown(self):
        app_schliessen(self.wurzel, getattr(self, "app", None))

    def motiv(self, breite=400, hoehe=200):
        self.app.src = Image.new("L", (breite, hoehe), 0)
        self.app.src_path = "/tmp/probe.png"


class Aufbau(Grundlage):
    def test_kein_feld_verdeckt_ein_anderes(self):
        for name, tab in (("Motiv", self.app.tab_motiv),
                          ("Material", self.app.tab_mat),
                          ("Maschine", self.app.tab_masch),
                          ("Tests", self.app.tab_test)):
            kaesten = [(c.winfo_x(), c.winfo_y(), c.winfo_width(), c.winfo_height())
                       for c in tab.winfo_children() if c.grid_info()]
            for i in range(len(kaesten)):
                for j in range(i + 1, len(kaesten)):
                    a, b = kaesten[i], kaesten[j]
                    quer = (min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
                    hoch = (min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
                    self.assertLessEqual(min(quer, hoch), 0,
                                         "%s: Felder ueberlappen" % name)

    def test_jobleiste_passt_ins_fenster(self):
        """Summe der angeforderten Breiten muss hineinpassen - sonst quetscht
        grid den Fortschrittsbalken auf einen Pixel."""
        self.wurzel.update()
        leiste = self.app.btn_gen.master
        gebraucht = sum(c.winfo_reqwidth() + 8
                        for c in leiste.winfo_children())
        self.assertLessEqual(gebraucht, 1270,
                             "Jobleiste braucht %d px" % gebraucht)

    def test_erzeugen_knopf_zeigt_fehlenden_gcode(self):
        self.motiv()
        self.app._gen_knopf()
        self.assertEqual(self.app.btn_gen.cget("style"), "Accent.TButton")
        self.app.v_w.set(40.0)
        self.app.generate()
        self.assertEqual(self.app.btn_gen.cget("style"), "TButton")
        self.app.v_s.set(300)                 # Aenderung macht ihn ungueltig
        self.assertEqual(self.app.btn_gen.cget("style"), "Accent.TButton")


class Platzieren(Grundlage):
    def setUp(self):
        super().setUp()
        self.motiv()
        self.app.v_bw.set(120.0)
        self.app.v_bh.set(80.0)
        self.app.v_w.set(80.0)
        self.app.v_h.set(40.0)
        self.app.v_xoff.set(10.0)
        self.app.v_yoff.set(5.0)
        self.app.v_job.set("schnitt")         # ohne Anlaufgrenze rechnen

    def ziehen(self, von_mm, nach_mm):
        import types
        p = self.app._mm(*von_mm)
        q = self.app._mm(*nach_mm)
        self.app._press(types.SimpleNamespace(x=int(round(p[0])), y=int(round(p[1]))))
        art = self.app.drag[0] if self.app.drag else None
        self.app._drag_move(types.SimpleNamespace(x=int(round(q[0])), y=int(round(q[1]))))
        self.app.drag = None
        return art

    def test_schieben(self):
        self.app.v_snap.set(False)
        art = self.ziehen((50, 25), (70, 35))
        self.assertEqual(art, "move")
        self.assertAlmostEqual(self.app.v_xoff.get(), 30.0, delta=0.5)
        self.assertAlmostEqual(self.app.v_yoff.get(), 15.0, delta=0.5)

    def test_einrasten_auf_die_mitte(self):
        self.app.v_snap.set(True)
        # Brett 120 x 80, Motiv 80 x 40 -> Mitte liegt bei 20 / 20
        self.ziehen((50, 25), (60.3, 40.3))
        self.assertAlmostEqual(self.app.v_xoff.get(), 20.0, places=2)
        self.assertAlmostEqual(self.app.v_yoff.get(), 20.0, places=2)

    def test_einrasten_auf_die_kante(self):
        self.app.v_snap.set(True)
        self.ziehen((50, 25), (40.2, 25))
        self.assertAlmostEqual(self.app.v_xoff.get(), 0.0, places=2)

    def test_skalieren_haelt_die_gegenecke(self):
        self.app.v_snap.set(False)
        self.app.v_lock.set(False)
        art = self.ziehen((10, 5), (20, 10))
        self.assertEqual(art, "size")
        x, y = self.app.v_xoff.get(), self.app.v_yoff.get()
        self.assertAlmostEqual(x + self.app.v_w.get(), 90.0, delta=0.5)
        self.assertAlmostEqual(y + self.app.v_h.get(), 45.0, delta=0.5)

    def test_mittig_setzen(self):
        self.app.center_motif()
        self.assertAlmostEqual(self.app.v_xoff.get(), 20.0, places=2)
        self.assertAlmostEqual(self.app.v_yoff.get(), 20.0, places=2)

    def test_anlauf_bleibt_beim_gravieren_frei(self):
        self.app.v_job.set("gravur")
        self.app.v_over.set(1.5)
        self.app.v_snap.set(False)
        self.ziehen((50, 25), (20, 25))
        self.assertAlmostEqual(self.app.v_xoff.get(), 1.5, places=2)

    def test_klick_neben_das_motiv_greift_nichts(self):
        import types
        p = self.app._mm(5, 70)
        self.app._press(types.SimpleNamespace(x=int(p[0]), y=int(p[1])))
        self.assertIsNone(self.app.drag)

    def test_rueckseite_rechnet_zurueck(self):
        self.app.v_snap.set(False)
        self.app.v_spiegel.set("x")
        self.app.v_achse.set(60.0)
        kasten = self.app._box()
        self.assertAlmostEqual(kasten[0], 2 * 60 - 10 - 80, places=2)
        self.ziehen((kasten[0] + 40, kasten[1] + 20), (kasten[0] + 45, kasten[1] + 20))
        self.assertAlmostEqual(self.app.v_xoff.get(), 5.0, delta=0.5)


class Drehen(Grundlage):
    def test_beliebige_winkel_im_seitenverhaeltnis(self):
        import math
        self.motiv(200, 100)
        for grad in (0, 30, 45, 90, 180, 270):
            self.app.v_rot.set(grad)
            self.app.v_w.set(80.0)
            self.app._keep_ratio("w")
            a = math.radians(grad)
            soll = ((200 * abs(math.cos(a)) + 100 * abs(math.sin(a)))
                    / (200 * abs(math.sin(a)) + 100 * abs(math.cos(a))))
            self.assertAlmostEqual(self.app.v_w.get() / self.app.v_h.get(),
                                   soll, places=2)

    def test_winkel_wird_auf_den_kreis_geholt(self):
        self.app.v_rot.set(370.0)
        self.app._rotated()
        self.assertAlmostEqual(self.app.v_rot.get(), 10.0, places=1)


class Grenzen(Grundlage):
    def setUp(self):
        super().setUp()
        self.motiv()
        self.app.v_mode.set("schwelle")

    def erzeuge(self, xoff, breite):
        self.app.v_xoff.set(xoff)
        self.app.v_yoff.set(5.0)
        self.app.v_w.set(breite)
        self.app._keep_ratio("w")
        self.app.generate()

    def test_passender_job_laeuft(self):
        self.app.cfg["x_max"], self.app.cfg["y_max"] = 200.0, 200.0
        self.erzeuge(10.0, 150.0)
        self.gezeigt.clear()
        self.app._run(self.app.lines, "Test")
        self.assertEqual(self.gezeigt, [])

    def test_zu_breiter_job_wird_abgelehnt(self):
        self.app.cfg["x_max"], self.app.cfg["y_max"] = 200.0, 200.0
        self.erzeuge(10.0, 250.0)
        self.gezeigt.clear()
        self.app._run(self.app.lines, "Test")
        self.assertTrue(self.gezeigt)

    def test_weit_aussen_liegender_job_wird_abgelehnt(self):
        """Schmal, aber jenseits des Verfahrwegs - die blosse Spanne
        haette das frueher durchgelassen."""
        self.app.cfg["x_max"], self.app.cfg["y_max"] = 200.0, 200.0
        self.erzeuge(170.0, 100.0)
        self.gezeigt.clear()
        self.app._run(self.app.lines, "Test")
        self.assertTrue(self.gezeigt)

    def test_groessere_maschine_nimmt_ihn_an(self):
        self.app.cfg["x_max"], self.app.cfg["y_max"] = 300.0, 180.0
        self.erzeuge(170.0, 100.0)
        self.gezeigt.clear()
        self.app._run(self.app.lines, "Test")
        self.assertEqual(self.gezeigt, [])


class Starten(Grundlage):
    def test_job_geht_bis_zum_streamen(self):
        self.motiv()
        self.app.v_mode.set("schwelle")
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        self.app.generate()
        self.app.start()
        import time
        t0 = time.time()
        while time.time() - t0 < 3 and not any(
                z.startswith("JOB") for z in self.app.grbl.protokoll):
            self.wurzel.update()
            time.sleep(0.02)
        self.assertTrue(any(z.startswith("JOB") for z in self.app.grbl.protokoll))
        self.assertEqual(self.app.grbl.gesendet[-1], "G0 X0 Y0")

    def test_ohne_gcode_passiert_nichts(self):
        self.app.lines = None
        self.gezeigt.clear()
        self.app.start()
        self.assertTrue(self.gezeigt)
        self.assertFalse(any(z.startswith("JOB") for z in self.app.grbl.protokoll))


class Leistung(Grundlage):
    def test_umrechnung_auf_die_fremde_skala(self):
        self.app.grbl = Attrappe(s30=255.0)
        self.app._einstellungen_pruefen(self.app.grbl.settings)
        self.assertEqual(self.app.s_max, 255.0)
        self.assertEqual(self.app._s(830), 212)      # derselbe Anteil
        self.assertEqual(self.app._s(50), 13)

    def test_eigene_maschine_bleibt_unveraendert(self):
        self.app._einstellungen_pruefen(self.app.grbl.settings)
        self.assertEqual(self.app._s(830), 830)
        self.assertEqual(self.gezeigt, [])

    def test_lasermodus_aus_wird_gemeldet(self):
        self.app.grbl = Attrappe(s32=0.0)
        self.app._einstellungen_pruefen(self.app.grbl.settings)
        self.assertTrue(any("$32" in m for _, m in self.gezeigt))

    def test_untergrenze_fuer_graustufen(self):
        self.assertAlmostEqual(self.app._s_unten(200), 60.0, places=1)
        self.app.v_smin.set(150)
        self.assertEqual(self.app._s_unten(200), 150)
        self.app.v_smin.set(500)
        self.assertEqual(self.app._s_unten(200), 199)     # nie ueber S


class Nullpunkt(Grundlage):
    def pumpe(self, sekunden=1.5):
        import time
        t0 = time.time()
        while time.time() - t0 < sekunden:
            self.wurzel.update()
            time.sleep(0.01)

    def test_ueberlebt_den_stopp(self):
        self.app.grbl = Attrappe(mpos=(120.0, 80.0, 12.0), app=self.app)
        self.app.set_zero()
        # 'G92 X0 Y0' setzt nur X und Y, der Versatz in Z bleibt, wie er war
        self.assertEqual(self.app.grbl.wco, (120.0, 80.0, 0.0))
        self.app.grbl.mpos = (150.0, 95.0, 12.0)
        self.app.stop()
        self.pumpe()
        self.assertEqual(self.app.grbl.wco, (120.0, 80.0, 0.0))
        self.assertTrue(self.app.zero_ok)
        self.app.goto_zero()
        self.pumpe(0.6)
        self.assertEqual(self.app.grbl.mpos[:2], (120.0, 80.0))

    def test_wartet_bei_alarm_auf_das_entsperren(self):
        self.app.grbl = Attrappe(mpos=(120.0, 80.0, 0.0), app=self.app)
        self.app.set_zero()
        self.app.grbl.mpos = (150.0, 95.0, 0.0)
        echt = self.app.grbl.stop

        def stop_mit_alarm():
            echt()
            self.app.grbl.alarm = "ALARM:2"
        self.app.grbl.stop = stop_mit_alarm
        self.app.stop()
        self.pumpe()
        self.assertEqual(self.app.grbl.wco, (0.0, 0.0, 0.0))
        self.assertIsNotNone(self.app._rettung)
        self.app.unlock()
        self.pumpe()
        self.assertEqual(self.app.grbl.wco, (120.0, 80.0, 0.0))

    def test_nach_abriss_wird_nichts_wiederhergestellt(self):
        self.app.grbl = Attrappe(mpos=(120.0, 80.0, 0.0), app=self.app)
        self.app.set_zero()
        self.app.stop()
        self.pumpe()
        self.app._event("lost", "Port weg")
        self.assertIsNone(self.app._rettung)
        self.app.grbl.wco = (0.0, 0.0, 0.0)
        self.app._event("reset", "Grbl 1.1f")
        self.pumpe(0.6)
        self.assertEqual(self.app.grbl.wco, (0.0, 0.0, 0.0))
        self.assertFalse(self.app.zero_ok)


class Projektrundlauf(Grundlage):
    def test_alle_werte_kommen_zurueck(self):
        import os
        import tempfile
        ordner = tempfile.mkdtemp(prefix="laserwerk-gui-")
        quelle = os.path.join(ordner, "motiv.png")
        Image.new("L", (400, 200), 30).save(quelle)
        ziel = os.path.join(ordner, "p.lwp")
        self.L.filedialog.askopenfilename = lambda **k: quelle
        self.L.filedialog.asksaveasfilename = lambda **k: ziel
        self.app.open_image()
        self.app.v_w.set(137.5)
        self.app.v_h.set(102.3)
        self.app.v_lock.set(False)
        self.app.v_rot.set(23.0)
        self.app.v_mode.set("raster")
        self.app.v_gamma.set(1.7)
        self.app.v_s.set(173)
        self.app.v_smin.set(151)
        self.app.v_line.set(0.13)
        self.app.v_notiz.set("Buche")
        soll = {f: getattr(self.app, f).get() for f, _ in self.app.PROJEKTFELDER}
        self.app.save_project()
        # Zwei Tk-Wurzeln gleichzeitig teilen sich die Bilder nicht - die
        # erste Sitzung muss zu sein, bevor die zweite aufmacht.
        app_schliessen(self.wurzel, self.app)
        self.wurzel, self.app, L2 = app_bauen()
        app2 = self.app
        L2.filedialog.askopenfilename = lambda **k: ziel
        os.remove(quelle)                         # Vorlage verschwindet
        app2.open_project()
        ist = {f: getattr(app2, f).get() for f, _ in app2.PROJEKTFELDER}
        self.assertEqual(ist, soll)
        self.assertIsNotNone(app2.src)


if __name__ == "__main__":
    unittest.main()


@ohne_bildschirm
class AnlaufAusDerMaschine(Grundlage):
    def test_null_heisst_gerechnet(self):
        self.app.cfg["accel"] = 30.0
        self.app.v_f.set(1000)
        self.app.v_over.set(0)
        self.assertAlmostEqual(self.app._anlauf(), 5.3, delta=0.2)   # 4,63 + Luft

    def test_eigener_wert_gilt(self):
        self.app.v_over.set(8.0)
        self.assertEqual(self.app._anlauf(), 8.0)

    def test_schnelle_maschine_braucht_kaum_anlauf(self):
        self.app.cfg["accel"] = 500.0
        self.app.v_f.set(1000)
        self.app.v_over.set(0)
        self.assertLess(self.app._anlauf(), 1.0)

    def test_hinweis_warnt_vor_zu_kurzem_anlauf(self):
        self.app.cfg["accel"] = 30.0
        self.app.v_f.set(1000)
        self.app.v_over.set(1.5)
        self.app._anlauf_zeigen()
        self.assertIn("kurz", self.app.lbl_anlauf.cget("text"))
        self.app.v_over.set(0)
        self.app._anlauf_zeigen()
        self.assertNotIn("kurz", self.app.lbl_anlauf.cget("text"))

    def test_beschleunigung_kommt_aus_dollar_120(self):
        self.app.grbl = Attrappe()
        self.app.grbl.settings["120"] = 250.0
        self.app._einstellungen_pruefen(self.app.grbl.settings)
        self.assertEqual(self.app.cfg["accel"], 250.0)

    def test_gcode_nimmt_den_gerechneten_anlauf(self):
        self.motiv()
        self.app.cfg["accel"] = 30.0
        self.app.v_f.set(1000)
        self.app.v_over.set(0)
        self.app.v_xoff.set(20.0)
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        self.app.v_mode.set("schwelle")
        self.app.generate()
        self.assertAlmostEqual(self.app.info["xmin"], 20.0 - 5.3, delta=0.3)
