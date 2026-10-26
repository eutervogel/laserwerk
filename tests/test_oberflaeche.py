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
        if self.wurzel is not None:
            app_schliessen(self.wurzel, getattr(self, "app", None))

    def motiv(self, breite=400, hoehe=200):
        """Ein Element anlegen, wie es das Laden einer Datei tut."""
        im = Image.new("L", (breite, hoehe), 0)
        self.app.src = im
        self.app.src_path = "/tmp/probe.png"
        self.app.vec = self.app.vec_bb = None
        self.app.elemente = [{"anzeige": "probe.png", "src": im, "vec": None,
                              "vec_bb": None, "pfad": "/tmp/probe.png",
                              "quelle": "/tmp/probe.png"}]
        self.app.aktiv = 0
        self.app._element_sichern()
        self.app._liste_auffrischen()


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


@ohne_bildschirm
class Beenden(Grundlage):
    def test_ohne_job_einfach_zu(self):
        self.gezeigt.clear()
        self.app.beenden()
        self.assertEqual(self.gezeigt, [])
        self.wurzel = self.app = None          # schon zerstoert

    def test_mit_job_wird_gefragt_und_angehalten(self):
        gefragt = []
        self.L.messagebox.askokcancel = lambda t, m: (gefragt.append(m), True)[1]
        self.app.grbl.job_running = True
        self.app.beenden()
        self.assertTrue(gefragt)
        self.assertIn("STOPP", self.app.grbl.protokoll)
        self.wurzel = self.app = None

    def test_abbrechen_laesst_den_job_laufen(self):
        self.L.messagebox.askokcancel = lambda t, m: False
        self.app.grbl.job_running = True
        self.app.beenden()
        self.assertNotIn("STOPP", self.app.grbl.protokoll)
        self.assertTrue(self.wurzel.winfo_exists())


@ohne_bildschirm
class AnlaufPasstVorDenNullpunkt(Grundlage):
    def test_versatz_wird_angehoben(self):
        self.motiv()
        self.app.cfg["accel"] = 30.0
        self.app.v_f.set(1000)
        self.app.v_over.set(0)                 # automatisch: 5,3 mm
        self.app.v_xoff.set(2.0)               # zu wenig davor
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        self.app.v_mode.set("raster")
        self.app.generate()
        self.assertGreaterEqual(self.app.v_xoff.get(), 5.2)
        self.assertGreaterEqual(J.extent(self.app.lines)[0], -0.001)

    def test_job_laeuft_danach(self):
        self.motiv()
        self.app.cfg["accel"] = 30.0
        self.app.v_f.set(1000)
        self.app.v_over.set(0)
        self.app.v_xoff.set(0.0)
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        self.app.generate()
        self.gezeigt.clear()
        self.app._run(self.app.lines, "Test")
        self.assertEqual(self.gezeigt, [])

    def test_grosser_versatz_bleibt(self):
        self.motiv()
        self.app.v_over.set(0)
        self.app.v_xoff.set(40.0)
        self.app.v_w.set(30.0)
        self.app._keep_ratio("w")
        self.app.generate()
        self.assertEqual(self.app.v_xoff.get(), 40.0)


@ohne_bildschirm
class Mausrad(Grundlage):
    """Fruehr rief jeder Reiter bind_all auf und ueberschrieb den vorherigen -
    nur der letzte liess sich rollen."""

    def setUp(self):
        super().setUp()
        # Im unsichtbaren Fenster sind die Flaechen 1 Pixel hoch; ohne echte
        # Hoehe bewegt eine Rastung rechnerisch nichts.
        for _, cv in self.app._rollflaechen:
            cv.configure(height=600)
        self.wurzel.update()

    def rollen(self, widget, hoch=False):
        import types
        e = types.SimpleNamespace(widget=widget, num=4 if hoch else 5, delta=0)
        return self.app._rad(e)

    def test_jeder_reiter_laesst_sich_rollen(self):
        self.wurzel.update()
        for name, tab in (("Motiv", self.app.tab_motiv),
                          ("Material", self.app.tab_mat),
                          ("Maschine", self.app.tab_masch),
                          ("Tests", self.app.tab_test)):
            cv = tab.master
            cv.yview_moveto(0.0)
            self.wurzel.update()
            kind = tab.winfo_children()[-1]
            self.rollen(kind)
            self.wurzel.update()
            if cv.bbox("all")[3] > cv.winfo_height():
                self.assertGreater(cv.yview()[0], 0.0, "%s rollt nicht" % name)

    def test_ueber_der_leeren_flaeche_rollt_es_auch(self):
        self.wurzel.update()
        cv = self.app.tab_motiv.master
        cv.yview_moveto(0.0)
        self.rollen(cv)
        self.wurzel.update()
        self.assertGreater(cv.yview()[0], 0.0)

    def test_zurueck_nach_oben(self):
        self.wurzel.update()
        cv = self.app.tab_motiv.master
        cv.yview_moveto(0.5)
        self.wurzel.update()
        vorher = cv.yview()[0]
        self.rollen(self.app.tab_motiv, hoch=True)
        self.wurzel.update()
        self.assertLess(cv.yview()[0], vorher)

    def test_zeichenflaeche_bleibt_dem_zoom(self):
        """Ueber der Arbeitsflaeche darf das Rad nicht die Spalte rollen."""
        self.assertIsNone(self.rollen(self.app.cv))

    def test_kurzer_reiter_zappelt_nicht(self):
        self.wurzel.update()
        cv = self.app.tab_mat.master
        if cv.bbox("all")[3] <= cv.winfo_height():
            self.assertIsNone(self.rollen(self.app.tab_mat))


@ohne_bildschirm
class Raender(Grundlage):
    def setUp(self):
        super().setUp()
        self.motiv()
        self.app.v_bw.set(120.0)
        self.app.v_bh.set(80.0)
        self.app.v_job.set("schnitt")          # ohne Anlaufgrenze rechnen
        self.app.v_w.set(80.0)
        self.app.v_h.set(40.0)
        self.app.v_xoff.set(10.0)
        self.app.v_yoff.set(5.0)
        self.app._draw()

    def test_abstaende_werden_angezeigt(self):
        r = self.app.v_rand
        self.assertAlmostEqual(r["l"].get(), 10.0, places=1)
        self.assertAlmostEqual(r["r"].get(), 30.0, places=1)   # 120-10-80
        self.assertAlmostEqual(r["u"].get(), 5.0, places=1)
        self.assertAlmostEqual(r["o"].get(), 35.0, places=1)   # 80-5-40

    def test_rechten_rand_eintippen(self):
        self.app.v_rand["r"].set(5.0)
        self.app._rand_setzen("r")
        self.assertAlmostEqual(self.app.v_xoff.get(), 35.0, places=1)  # 120-80-5
        self.assertAlmostEqual(self.app.v_rand["r"].get(), 5.0, places=1)

    def test_oberen_rand_eintippen(self):
        self.app.v_rand["o"].set(8.0)
        self.app._rand_setzen("o")
        self.assertAlmostEqual(self.app.v_yoff.get(), 32.0, places=1)  # 80-40-8

    def test_abstaende_folgen_dem_schieben(self):
        self.app.v_xoff.set(25.0)
        self.app._draw()
        self.assertAlmostEqual(self.app.v_rand["l"].get(), 25.0, places=1)
        self.assertAlmostEqual(self.app.v_rand["r"].get(), 15.0, places=1)

    def test_abstaende_folgen_dem_brettmass(self):
        self.app.v_bw.set(200.0)
        self.app._draw()
        self.assertAlmostEqual(self.app.v_rand["r"].get(), 110.0, places=1)

    def test_rueckseite_zeigt_die_echte_lage(self):
        self.app.v_spiegel.set("x")
        self.app.v_achse.set(60.0)
        self.app._draw()
        # gespiegelt sitzt das Motiv bei x = 2*60-10-80 = 30
        self.assertAlmostEqual(self.app.v_rand["l"].get(), 30.0, places=1)
        self.app.v_rand["r"].set(5.0)
        self.app._rand_setzen("r")
        self.app._draw()
        self.assertAlmostEqual(self.app.v_rand["r"].get(), 5.0, places=1)

    def test_anlauf_begrenzt_den_linken_rand(self):
        self.app.v_job.set("gravur")
        self.app.v_over.set(4.0)
        self.app.v_rand["l"].set(1.0)
        self.app._rand_setzen("l")
        self.assertGreaterEqual(self.app.v_xoff.get(), 4.0)


@ohne_bildschirm
class KonturFahren(Grundlage):
    def svg_laden(self):
        import os
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "k.svg")
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="40" '
                    'height="20" viewBox="0 0 40 20">'
                    '<path d="M 0 0 L 40 0 L 40 20 L 0 20 Z"/>'
                    '<circle cx="20" cy="10" r="5"/></svg>')
        self.L.filedialog.askopenfilename = lambda **k: p
        self.app.open_image()

    def test_faehrt_die_echte_kontur_nicht_den_kasten(self):
        self.svg_laden()
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        self.app.v_xoff.set(10.0)
        self.app.v_yoff.set(10.0)
        self.app.kontur()
        gesendet = [z for z in self.app.grbl.gesendet if z.startswith("G1")]
        # ein Kasten haette vier G1-Fahrten, der Kreis bringt viel mehr
        self.assertGreater(len(gesendet), 20)

    def test_schwache_leistung(self):
        import re
        self.svg_laden()
        self.app.v_zeig_s.set(50)
        self.app.kontur()
        werte = {int(m.group(1)) for z in self.app.grbl.gesendet
                 for m in [re.search(r"S(\d+)", z)] if m}
        self.assertLessEqual(max(werte), 50)

    def test_leistung_wird_gedeckelt(self):
        """Ueber S120 geht es nicht - bei F600 ist das S/F 0,20, die Grenze,
        ab der es sichtbar einbrennt."""
        import re
        self.svg_laden()
        self.app.v_zeig_s.set(400)
        self.app.kontur()
        werte = {int(m.group(1)) for z in self.app.grbl.gesendet
                 for m in [re.search(r"S(\d+)", z)] if m}
        self.assertLessEqual(max(werte), 120)
        self.assertLessEqual(max(werte) / J.POINTER_FEED, 0.20)

    def test_ohne_konturen_hinweis(self):
        self.motiv()                          # Pixelbild
        self.gezeigt.clear()
        self.app.kontur()
        self.assertTrue(self.gezeigt)

    def test_braucht_keinen_nullpunkt_wie_der_rahmen(self):
        self.svg_laden()
        self.app.zero_ok = False
        self.app.kontur()
        self.assertTrue(any(z.startswith("JOB") for z in self.app.grbl.protokoll))


@ohne_bildschirm
class GravierenUndSchneiden(Grundlage):
    def svg_laden(self):
        import os
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "teil.svg")
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="40" '
                    'height="20" viewBox="0 0 40 20">'
                    '<path d="M 0 0 L 40 0 L 40 20 L 0 20 Z"/>'
                    '<circle cx="20" cy="10" r="6" fill="black"/></svg>')
        self.L.filedialog.askopenfilename = lambda **k: p
        self.app.open_image()
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        self.app.v_xoff.set(10.0)
        self.app.v_yoff.set(10.0)

    def test_beides_haengt_den_schnitt_an_die_gravur(self):
        self.svg_laden()
        self.app.v_mode.set("schwelle")
        self.app.v_job.set("gravur")
        self.app.generate()
        nur_gravur = len(self.app.lines)
        self.app.v_job.set("beides")
        self.app.generate()
        self.assertGreater(len(self.app.lines), nur_gravur)
        # die Konturen liegen jetzt beim Element, nicht mehr global
        self.assertTrue(self.app.elemente[0]["ergebnis"]["cut_polys"])

    def test_erst_gravieren_dann_schneiden(self):
        """Umgekehrt faellt das Teil heraus, bevor es graviert ist."""
        self.svg_laden()
        self.app.v_job.set("beides")
        self.app.generate()
        schnitt = next(i for i, z in enumerate(self.app.lines)
                       if z.startswith("; Laserwerk Schnitt"))
        gravur = next(i for i, z in enumerate(self.app.lines)
                      if z.startswith("; Laserwerk "))
        self.assertLess(gravur, schnitt)

    def test_eigene_schnittwerte(self):
        import re
        self.svg_laden()
        self.app.v_s.set(300)
        self.app.v_f.set(1000)
        self.app.v_cs.set(800)
        self.app.v_cf.set(400)
        self.app.v_job.set("beides")
        self.app.generate()
        werte = {int(m.group(1)) for z in self.app.lines if z.startswith("G1")
                 for m in [re.search(r"S(\d+)", z)] if m}
        self.assertIn(300, werte)          # Gravur
        self.assertIn(800, werte)          # Schnitt
        self.assertTrue(any("F400" in z for z in self.app.lines))

    def test_null_heisst_werte_vom_material(self):
        self.svg_laden()
        self.app.v_s.set(300)
        self.app.v_f.set(900)
        self.app.v_cs.set(0)
        self.app.v_cf.set(0)
        self.assertEqual(self.app._schnittwerte(), (300, 900))

    def test_laufzeit_ist_die_summe(self):
        self.svg_laden()
        self.app.v_job.set("gravur")
        self.app.generate()
        t_gravur = self.app.info["sekunden"]
        self.app.v_job.set("beides")
        self.app.generate()
        self.assertGreater(self.app.info["sekunden"], t_gravur)
        self.assertIn("schnitt_sekunden", self.app.info)

    def test_ohne_konturen_kein_gemischter_modus(self):
        self.motiv()                       # Pixelbild
        self.app.v_job.set("beides")
        self.app._job_changed()
        self.assertEqual(self.app.v_job.get(), "gravur")

    def test_anlauf_gilt_auch_im_gemischten_modus(self):
        self.svg_laden()
        self.app.v_job.set("beides")
        self.app.v_over.set(4.0)
        self.assertEqual(self.app._xmin(), 4.0)

    def test_job_laeuft_am_stueck(self):
        self.svg_laden()
        self.app.v_job.set("beides")
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


@ohne_bildschirm
class GemischterInfotext(Grundlage):
    def test_beide_teile_stehen_im_infofeld(self):
        import os
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "t.svg")
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="40" '
                    'height="20" viewBox="0 0 40 20">'
                    '<path d="M 0 0 L 40 0 L 40 20 L 0 20 Z"/></svg>')
        self.L.filedialog.askopenfilename = lambda **k: p
        self.app.open_image()
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        self.app.v_job.set("beides")
        self.app.generate()
        text = self.app.lbl_info.cget("text")
        self.assertIn("Motiv", text)
        self.assertIn("Schnitt", text)


@ohne_bildschirm
class MehrereElemente(Grundlage):
    """Der Fall, fuer den das Ganze gebaut ist: Motiv als PNG, Rahmen als
    SVG, uebereinander auf einem Brettchen."""

    def dateien(self):
        import os
        import tempfile
        ordner = tempfile.mkdtemp(prefix="laserwerk-el-")
        png = os.path.join(ordner, "motiv.png")
        Image.new("L", (400, 300), 40).save(png)
        svg = os.path.join(ordner, "rahmen.svg")
        with open(svg, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="80" '
                    'height="60" viewBox="0 0 80 60"><rect x="0" y="0" '
                    'width="80" height="60" fill="none" stroke="black"/></svg>')
        return ordner, png, svg

    def beide_laden(self):
        ordner, png, svg = self.dateien()
        self.app.v_bw.set(120.0)
        self.app.v_bh.set(80.0)
        self.L.filedialog.askopenfilename = lambda **k: png
        self.app.open_image()
        self.app.v_mode.set("schwelle")
        self.app.v_w.set(60.0)
        self.app._keep_ratio("w")
        self.app.center_motif()
        self.L.filedialog.askopenfilename = lambda **k: svg
        self.app.open_image()
        self.app.v_job.set("schnitt")
        self.app.v_w.set(80.0)
        self.app._keep_ratio("w")
        self.app.center_motif()
        return ordner, png, svg

    def test_zwei_elemente_in_der_liste(self):
        self.beide_laden()
        self.assertEqual(len(self.app.elemente), 2)
        self.assertEqual(self.app.aktiv, 1)
        self.assertEqual(self.app.lb_el.size(), 2)

    def test_umschalten_haelt_die_einstellungen(self):
        self.beide_laden()
        self.app.lb_el.selection_clear(0, "end")
        self.app.lb_el.selection_set(0)
        self.app._element_gewaehlt()
        self.assertEqual(self.app.v_job.get(), "gravur")
        self.assertAlmostEqual(self.app.v_w.get(), 60.0, places=1)
        self.app.lb_el.selection_clear(0, "end")
        self.app.lb_el.selection_set(1)
        self.app._element_gewaehlt()
        self.assertEqual(self.app.v_job.get(), "schnitt")
        self.assertAlmostEqual(self.app.v_w.get(), 80.0, places=1)

    def test_ein_gcode_fuer_beide(self):
        self.beide_laden()
        self.app.generate()
        self.assertIsNotNone(self.app.lines)
        for e in self.app.elemente:
            self.assertIn("ergebnis", e)
        # Gravur zuerst, Schnitt danach
        gravur = next(i for i, z in enumerate(self.app.lines)
                      if z.startswith("; Laserwerk motiv"))
        schnitt = next(i for i, z in enumerate(self.app.lines)
                       if z.startswith("; Laserwerk Schnitt"))
        self.assertLess(gravur, schnitt)

    def test_beide_sind_konzentrisch(self):
        self.beide_laden()
        self.app.generate()
        raender = []
        for i in (0, 1):
            r = self.app.elemente[i]["ergebnis"]["info"]
            raender.append(round(r["xmin"], 1))
        self.assertNotEqual(raender[0], raender[1])     # verschieden gross
        self.app.lb_el.selection_set(0)
        self.app._element_gewaehlt()
        links_png = self.app.v_rand["l"].get()
        rechts_png = self.app.v_rand["r"].get()
        self.assertAlmostEqual(links_png, rechts_png, places=1)

    def test_entfernen(self):
        self.beide_laden()
        self.app.element_entfernen()
        self.assertEqual(len(self.app.elemente), 1)
        self.assertEqual(self.app.aktiv, 0)
        self.assertIsNotNone(self.app.src)

    def test_alles_entfernen(self):
        self.beide_laden()
        self.app.element_entfernen()
        self.app.element_entfernen()
        self.assertEqual(self.app.elemente, [])
        self.assertIsNone(self.app.src)
        self.gezeigt.clear()
        self.app.generate()
        self.assertTrue(self.gezeigt)

    def test_projekt_haelt_beide(self):
        import os
        ordner, png, svg = self.beide_laden()
        ziel = os.path.join(ordner, "p.lwp")
        self.L.filedialog.asksaveasfilename = lambda **k: ziel
        self.app.save_project()
        soll = [(e["anzeige"], e["v_job"], round(e["v_w"], 1),
                 round(e["v_xoff"], 1)) for e in self.app.elemente]

        app_schliessen(self.wurzel, self.app)
        self.wurzel, self.app, L2 = app_bauen()
        L2.filedialog.askopenfilename = lambda **k: ziel
        os.remove(png)
        os.remove(svg)                      # Vorlagen verschwinden
        self.app.open_project()
        ist = [(e["anzeige"], e["v_job"], round(e["v_w"], 1),
                round(e["v_xoff"], 1)) for e in self.app.elemente]
        self.assertEqual(ist, soll)
        self.assertEqual(len(self.app.elemente), 2)


@ohne_bildschirm
class AltesProjekt(Grundlage):
    def test_projekt_ohne_elementliste(self):
        import os
        import shutil
        import tempfile
        import lw_projekt as PR
        ordner = tempfile.mkdtemp(prefix="laserwerk-altp-")
        quelle = os.path.join(ordner, "motiv.png")
        Image.new("L", (400, 200), 30).save(quelle)
        p = os.path.join(ordner, "alt.lwp")
        PR.speichern(p, {"breite": 55.0, "hoehe": 27.5, "modus": "schwelle",
                         "versatz_x": 12.0, "versatz_y": 7.0, "leistung": 444,
                         "brett_x": 150.0, "brett_y": 90.0},
                     quelle=quelle)
        self.L.filedialog.askopenfilename = lambda **k: p
        self.app.open_project()
        self.assertEqual(len(self.app.elemente), 1)
        self.assertAlmostEqual(self.app.v_w.get(), 55.0, places=1)
        self.assertAlmostEqual(self.app.v_xoff.get(), 12.0, places=1)
        self.assertEqual(self.app.v_s.get(), 444)
        self.assertAlmostEqual(self.app.v_bw.get(), 150.0, places=1)
        shutil.rmtree(ordner, ignore_errors=True)


@ohne_bildschirm
class RahmenUndAnfasser(Grundlage):
    """Beim Umbau auf mehrere Elemente war dieser Block versehentlich mit
    herausgeschnitten - ohne Anfasser laesst sich nichts mehr ziehen."""

    def anfasser(self):
        """Die vier kleinen gefuellten Rechtecke in Akzentfarbe."""
        import lw_style as S
        return [i for i in self.app.cv.find_all()
                if self.app.cv.type(i) == "rectangle"
                and self.app.cv.itemcget(i, "fill") == S.ACCENT]

    def test_vier_anfasser_am_gewaehlten_element(self):
        self.motiv()
        self.app.v_w.set(80.0)
        self.app.v_h.set(40.0)
        self.app.v_xoff.set(10.0)
        self.app.v_yoff.set(5.0)
        self.app._draw()
        griffe = self.anfasser()
        self.assertEqual(len(griffe), 4)
        ecken = {tuple(self.app.cv.coords(g)[:2]) for g in griffe}
        self.assertEqual(len(ecken), 4)

    def test_anfasser_sitzen_auf_den_ecken(self):
        self.motiv()
        self.app.v_w.set(80.0)
        self.app.v_h.set(40.0)
        self.app.v_xoff.set(10.0)
        self.app.v_yoff.set(5.0)
        self.app._draw()
        mitten = sorted((self.app.cv.coords(g)[0] + 4,
                         self.app.cv.coords(g)[1] + 4) for g in self.anfasser())
        links_unten = self.app._mm(10.0, 5.0)
        rechts_oben = self.app._mm(90.0, 45.0)
        self.assertAlmostEqual(min(m[0] for m in mitten), links_unten[0], delta=1.5)
        self.assertAlmostEqual(max(m[0] for m in mitten), rechts_oben[0], delta=1.5)

    def test_massangabe_steht_am_rahmen(self):
        self.motiv()
        self.app.v_w.set(63.5)
        self.app.v_h.set(31.75)
        self.app._draw()
        texte = [self.app.cv.itemcget(i, "text") for i in self.app.cv.find_all()
                 if self.app.cv.type(i) == "text"]
        self.assertTrue(any("63.5" in t and "31.8" in t for t in texte), texte)

    def test_ohne_motiv_keine_anfasser(self):
        self.app.clear_motif()
        self.app._draw()
        self.assertEqual(self.anfasser(), [])

    def test_anfasser_folgen_dem_umschalten(self):
        self.motiv()
        self.app.v_w.set(80.0)
        self.app.v_h.set(40.0)
        self.app.v_xoff.set(10.0)
        self.app._element_sichern()
        zweites = dict(self.app.elemente[0])
        zweites["anzeige"] = "zweites.png"
        self.app.elemente.append(zweites)
        self.app._element_laden(1)
        self.app.v_w.set(30.0)
        self.app.v_h.set(15.0)
        self.app.v_xoff.set(60.0)
        self.app._draw()
        mitten = [self.app.cv.coords(g)[0] for g in self.anfasser()]
        self.assertAlmostEqual(min(mitten) + 4, self.app._mm(60.0, 0)[0], delta=1.5)


@ohne_bildschirm
class AlleElementeSichtbar(Grundlage):
    """Von den nicht gewaehlten Elementen war nur ein Rechteck zu sehen -
    man wusste nicht, was darin steht."""

    def zwei(self):
        self.motiv()
        self.app.v_w.set(60.0)
        self.app.v_h.set(30.0)
        self.app.v_xoff.set(10.0)
        self.app.v_yoff.set(10.0)
        self.app._element_sichern()
        zweites = dict(self.app.elemente[0])
        zweites["anzeige"] = "zweites.png"
        zweites["src"] = Image.new("L", (200, 100), 80)
        self.app.elemente.append(zweites)
        self.app._element_laden(1)
        self.app.v_w.set(40.0)
        self.app.v_h.set(20.0)
        self.app.v_xoff.set(80.0)
        self.app.v_yoff.set(50.0)
        self.app._element_sichern()
        self.app._draw()

    def test_beide_motive_werden_gezeichnet(self):
        self.zwei()
        bilder = [i for i in self.app.cv.find_all()
                  if self.app.cv.type(i) == "image"]
        self.assertEqual(len(bilder), 2)

    def test_nur_das_gewaehlte_hat_anfasser(self):
        import lw_style as S
        self.zwei()
        griffe = [i for i in self.app.cv.find_all()
                  if self.app.cv.type(i) == "rectangle"
                  and self.app.cv.itemcget(i, "fill") == S.ACCENT]
        self.assertEqual(len(griffe), 4)

    def test_kasten_eines_fremden_elements(self):
        self.zwei()
        e = self.app.elemente[0]
        self.assertEqual(tuple(round(v, 1) for v in self.app._box_von(e)),
                         (10.0, 10.0, 60.0, 30.0))

    def test_kasten_beachtet_die_rueckseite(self):
        self.zwei()
        e = self.app.elemente[0]
        e["v_spiegel"] = "x"
        e["v_achse"] = 60.0
        self.assertAlmostEqual(self.app._box_von(e)[0], 2 * 60 - 10 - 60, places=1)


@ohne_bildschirm
class FarbEbenen(Grundlage):
    """Motiv und Schnittkontur in einer Datei, getrennt durch die Farbe."""

    def svg(self):
        import os
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "layer.svg")
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="100" '
                    'height="60" viewBox="0 0 100 60">'
                    '<path d="M 20 20 L 50 20 L 50 40 Z" stroke="black" '
                    'fill="none"/>'
                    '<path d="M 1 1 L 99 1 L 99 59 L 1 59 Z" stroke="#ff0000" '
                    'fill="none"/></svg>')
        return p

    def laden(self, aufteilen=True):
        self.L.messagebox.askyesno = lambda t, m: aufteilen
        self.L.filedialog.askopenfilename = lambda **k: self.svg()
        self.app.open_image()

    def test_aufteilen_macht_zwei_elemente(self):
        self.laden()
        self.assertEqual(len(self.app.elemente), 2)
        arten = {e["anzeige"].split()[-1]: e["v_job"] for e in self.app.elemente}
        self.assertEqual(arten.get("#ff0000"), "schnitt")
        self.assertEqual(arten.get("#000000"), "gravur")

    def test_ablehnen_laesst_eine_datei(self):
        self.laden(aufteilen=False)
        self.assertEqual(len(self.app.elemente), 1)

    def test_ebenen_bleiben_in_deckung(self):
        self.laden()
        for e in self.app.elemente:
            e["v_w"] = 80.0
            e["v_h"] = 48.0
            e["v_xoff"] = 10.0
            e["v_yoff"] = 5.0
        self.app._element_laden(0)
        self.app.generate()
        kaesten = [tuple(round(v, 1) for v in (
            e["ergebnis"]["info"]["xmin"], e["ergebnis"]["info"]["xmax"]))
            for e in self.app.elemente]
        # die rote Aussenkontur umschliesst die schwarze Zeichnung
        rot = next(k for k, e in zip(kaesten, self.app.elemente)
                   if e["v_job"] == "schnitt")
        schwarz = next(k for k, e in zip(kaesten, self.app.elemente)
                       if e["v_job"] == "gravur")
        self.assertLess(rot[0], schwarz[0])
        self.assertGreater(rot[1], schwarz[1])

    def test_rot_erkennen(self):
        self.assertTrue(self.app._ist_rot("#ff0000"))
        self.assertTrue(self.app._ist_rot("#e01010"))
        self.assertFalse(self.app._ist_rot("#000000"))
        self.assertFalse(self.app._ist_rot("#ff00ff"))
        self.assertFalse(self.app._ist_rot("kaputt"))

    def test_einfarbige_zeichnung_fragt_nicht(self):
        import os
        import tempfile
        gefragt = []
        self.L.messagebox.askyesno = lambda t, m: (gefragt.append(1), True)[1]
        p = os.path.join(tempfile.mkdtemp(), "eine.svg")
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="40" '
                    'height="20" viewBox="0 0 40 20"><rect width="40" '
                    'height="20" fill="none" stroke="black"/></svg>')
        self.L.filedialog.askopenfilename = lambda **k: p
        self.app.open_image()
        self.assertEqual(gefragt, [])
        self.assertEqual(len(self.app.elemente), 1)


@ohne_bildschirm
class EbeneWirdNichtMitgraviert(FarbEbenen):
    """Der Kern der Sache: die Gravurebene darf die Schnittlinie nicht
    mitbrennen. Beim Erzeugen wurde frueher die ganze Datei neu gerendert."""

    def test_gravur_bleibt_innerhalb_des_schnitts(self):
        self.laden()
        for e in self.app.elemente:
            e["v_w"] = 80.0
            e["v_h"] = 48.0
            e["v_xoff"] = 10.0
            e["v_yoff"] = 5.0
        self.app._element_laden(0)
        self.app.generate()
        grenzen = {}
        for e in self.app.elemente:
            grenzen[e["v_job"]] = J.brenn_extent(e["ergebnis"]["lines"])
        g, s = grenzen["gravur"], grenzen["schnitt"]
        self.assertGreater(g[0], s[0] + 5)      # links innerhalb
        self.assertLess(g[1], s[1] - 5)         # rechts innerhalb
        self.assertGreater(g[2], s[2] + 5)
        self.assertLess(g[3], s[3] - 5)

    def test_hohe_aufloesung_bleibt_bei_der_ebene(self):
        """Auch beim Nachschaerfen darf nicht die ganze Datei gerendert
        werden."""
        self.laden()
        e = next(e for e in self.app.elemente if e["v_job"] == "gravur")
        self.app._element_laden(self.app.elemente.index(e))
        self.app.v_w.set(200.0)                 # verlangt mehr Aufloesung
        self.app.v_h.set(120.0)
        self.app.v_line.set(0.05)
        self.app.v_xoff.set(5.0)
        self.app.v_yoff.set(5.0)
        self.app._element_sichern()
        self.app.generate()
        x0, x1, y0, y1 = J.brenn_extent(e["ergebnis"]["lines"])
        self.assertGreater(x0, 20.0)            # nicht am Rand des Rahmens
        self.assertLess(x1, 190.0)


@ohne_bildschirm
class Zeilenzaehler(Grundlage):
    """Wie der Schichtzaehler am 3D-Drucker: wo im Bild steht der Kopf?"""

    def test_marken_im_rastercode(self):
        self.motiv()
        self.app.v_mode.set("schwelle")
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        self.app.generate()
        marken = self.app.info["marken"]
        self.assertEqual(len(marken), self.app.info["rows"])
        self.assertEqual(marken[0][1], "zeile")
        self.assertEqual(marken[-1][2], self.app.info["rows"])
        # streng aufsteigend
        self.assertEqual([m[0] for m in marken],
                         sorted(m[0] for m in marken))

    def test_text_zur_befehlsnummer(self):
        self.motiv()
        self.app.v_mode.set("schwelle")
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        self.app.generate()
        self.app.marken = self.app.info["marken"]
        self.app._marken_idx = [m[0] for m in self.app.marken]
        gesamt = self.app.info["rows"]
        self.assertIn("1", self.app._marke_text(self.app._marken_idx[0]))
        letzte = self.app._marke_text(self.app._marken_idx[-1])
        self.assertIn(str(gesamt), letzte)
        self.assertEqual(self.app._marke_text(0), "")

    def test_zaehler_laeuft_waehrend_des_jobs(self):
        self.motiv()
        self.app.v_mode.set("schwelle")
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        self.app.generate()
        self.app.marken = self.app.info["marken"]
        self.app._marken_idx = [m[0] for m in self.app.marken]
        mitte = len(self.app.lines) // 2
        self.app._event("prog", (mitte, len(self.app.lines), 10.0, 0))
        text = self.app.lbl_marke.cget("text")
        self.assertTrue(text, "kein Zeilenzaehler")
        self.assertIn("von", text)

    def test_schnitt_zaehlt_konturen(self):
        import os
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "k.svg")
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="40" '
                    'height="20" viewBox="0 0 40 20">'
                    '<path d="M 0 0 L 40 0 L 40 20 L 0 20 Z"/>'
                    '<circle cx="20" cy="10" r="5"/></svg>')
        self.L.filedialog.askopenfilename = lambda **k: p
        self.app.open_image()
        self.app.v_job.set("schnitt")
        self.app.generate()
        marken = self.app.info["marken"]
        self.assertTrue(marken)
        self.assertEqual(marken[0][1], "kontur")

    def test_zaehler_verschwindet_am_ende(self):
        self.motiv()
        self.app.lbl_marke.configure(text="Zeile 5 von 9")
        self.app._event("jobend", ("Gravur", "fertig"))
        self.assertEqual(self.app.lbl_marke.cget("text"), "")


@ohne_bildschirm
class MotivFolgtDemRahmen(Grundlage):
    """Nach dem Erzeugen blieb das Vorschaubild stehen, waehrend der Rahmen
    schon verschoben war - man zog einen leeren Kasten durch die Gegend."""

    def setUp(self):
        super().setUp()
        self.motiv()
        self.app.v_mode.set("schwelle")
        self.app.v_bw.set(140.0)
        self.app.v_bh.set(100.0)
        self.app.v_w.set(60.0)
        self.app.v_h.set(30.0)
        self.app.v_xoff.set(10.0)
        self.app.v_yoff.set(10.0)
        self.app.v_job.set("gravur")
        self.app.generate()

    def ziehen(self, von_mm, nach_mm):
        import types
        p = self.app._mm(*von_mm)
        q = self.app._mm(*nach_mm)
        self.app._press(types.SimpleNamespace(x=int(round(p[0])), y=int(round(p[1]))))
        self.app._drag_move(types.SimpleNamespace(x=int(round(q[0])),
                                                  y=int(round(q[1]))))
        self.app.drag = None

    def test_verschieben_verwirft_die_alte_vorschau(self):
        self.assertIn("ergebnis", self.app.elemente[0])
        self.app.v_snap.set(False)
        self.ziehen((40, 25), (70, 45))
        self.assertNotIn("ergebnis", self.app.elemente[0])
        self.assertIsNone(self.app.lines)

    def test_bild_sitzt_nach_dem_ziehen_am_rahmen(self):
        self.app.v_snap.set(False)
        self.ziehen((40, 25), (70, 45))
        self.app._draw()
        kasten = self.app._box()
        bilder = [i for i in self.app.cv.find_all()
                  if self.app.cv.type(i) == "image"]
        self.assertEqual(len(bilder), 1)
        x, y = self.app.cv.coords(bilder[0])
        soll = self.app._mm(kasten[0], kasten[1] + kasten[3])
        self.assertAlmostEqual(x, soll[0], delta=2)
        self.assertAlmostEqual(y, soll[1], delta=2)

    def test_groesse_aendern_zieht_das_bild_mit(self):
        self.app.v_snap.set(False)
        self.app.v_lock.set(False)
        vorher = self.app.v_w.get()
        self.ziehen((70, 40), (90, 55))        # rechte obere Ecke
        self.assertGreater(self.app.v_w.get(), vorher)
        self.app._draw()
        bilder = [i for i in self.app.cv.find_all()
                  if self.app.cv.type(i) == "image"]
        self.assertEqual(len(bilder), 1)
        breite_px = self.app.cv.bbox(bilder[0])[2] - self.app.cv.bbox(bilder[0])[0]
        self.assertAlmostEqual(breite_px, self.app.v_w.get() * self.app._scale(),
                               delta=3)

    def test_zahlenfeld_wirkt_genauso(self):
        self.app.v_xoff.set(55.0)
        self.assertNotIn("ergebnis", self.app.elemente[0])


class Tiefe(Grundlage):
    """Fraesen: geht die Datei tiefer als das Material, schneidet sie in
    die Unterlage. Beim Lasern ist Z konstant, da darf nichts fragen."""

    def tasche(self, tiefe):
        return ["G21", "G90", "G0 Z5.000", "G0 X10.000 Y10.000",
                f"G1 Z{-tiefe:.3f} F200", "G1 X50.000 F600",
                "G1 Y40.000", "G0 Z5.000", "G0 X0.000 Y0.000"]

    def setUp(self):
        super().setUp()
        self.gefragt = []
        self.antwort = True
        self.L.messagebox.askokcancel = lambda t, m: (
            self.gefragt.append(m), self.antwort)[1]
        self.app.v_dicke.set(12.0)

    def test_zu_tief_wird_gefragt(self):
        self.app._run(self.tasche(18.0), "Test")
        self.assertTrue(self.gefragt)
        self.assertIn("18", self.gefragt[0])

    def test_abbrechen_startet_nicht(self):
        self.antwort = False
        self.app.grbl.protokoll.clear()
        self.app._run(self.tasche(18.0), "Test")
        self.assertFalse([z for z in self.app.grbl.protokoll
                          if z.startswith("JOB")])

    def test_im_material_bleibt_still(self):
        self.app._run(self.tasche(6.0), "Test")
        self.assertEqual(self.gefragt, [])

    def test_knapp_durch_ist_erlaubt(self):
        """Durchfraesen heisst bis knapp unter die Materialunterkante -
        ein halber Millimeter Zugabe ist normal, keine Warnung wert."""
        self.app._run(self.tasche(12.3), "Test")
        self.assertEqual(self.gefragt, [])

    def test_ohne_materialdicke_keine_frage(self):
        self.app.v_dicke.set(0.0)
        self.app._run(self.tasche(18.0), "Test")
        self.assertEqual(self.gefragt, [])

    def test_gravur_ohne_z_fragt_nicht(self):
        self.app._run(["G21", "G90", "G1 X10.000 Y10.000 S300 F1000"], "Test")
        self.assertEqual(self.gefragt, [])

    def test_infotext_nennt_die_z_spanne(self):
        """Geladene Fremddateien: die Z-Spanne gehoert mit ins Infofeld,
        sonst sieht man erst beim Start, dass die Datei zustellt."""
        import tempfile
        f = tempfile.NamedTemporaryFile("w", suffix=".nc", delete=False)
        f.write("\n".join(self.tasche(2.0)) + "\n")
        f.close()
        self.L.filedialog.askopenfilename = lambda **k: f.name
        self.app.load_gcode()
        text = self.app.lbl_info.cget("text")
        self.assertIn("Z", text)
        self.assertIn("-2.00", text)
        self.assertIn("5.00", text)
