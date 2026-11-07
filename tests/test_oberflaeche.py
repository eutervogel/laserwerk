"""
Oberflaeche mit unsichtbarem Fenster und Maschinenattrappe.

Hier stehen die Faelle, die im Betrieb wehgetan haben: der Nullpunkt, der
den STOPP nicht ueberlebte; die Grenzpruefung, die ueber die blosse Spanne
ging; Leistungen, die auf einer fremden Maschine viermal zu hoch gewesen
waeren; Beschriftungen, die sich gegenseitig verdeckten.

Ohne Anzeige werden diese Tests uebersprungen.
"""
import os
import re
import tempfile
import time
import unittest

import numpy as np
from PIL import Image

from hilfe import (ohne_bildschirm, app_bauen, app_schliessen,
                   Attrappe)                                  # noqa: F401
import lw_job as J
import lw_vector as L_vector


@ohne_bildschirm
class Grundlage(unittest.TestCase):
    # Beschleunigung, Eilgang, Kreuzungstoleranz und Leistung gelten
    # modulweit und stehen in der Wegwerfkonfiguration. Ein Test, der sie
    # aendert, aendert sie sonst fuer alle folgenden - die Datei ueberlebt
    # den Testlauf, und die naechste App liest sie wieder ein.
    MASCHINE = ("accel", "eilgang", "kreuzung", "watt")

    def setUp(self):
        self.wurzel, self.app, self.L = app_bauen()
        self._modulwerte = (J.ACCEL, J.EILGANG, J.KREUZUNG, J.WATT)
        self._cfgwerte = {k: self.app.cfg.get(k) for k in self.MASCHINE}
        self._maschinen = self.L.P.kopie(self.app.maschinen)
        self.app.zero_ok = True
        self.gezeigt = []
        self.L.messagebox.showerror = lambda t, m: self.gezeigt.append(("!", m))
        self.L.messagebox.showinfo = lambda t, m: self.gezeigt.append(("i", m))
        self.L.messagebox.showwarning = lambda t, m: self.gezeigt.append(("w", m))
        self.L.messagebox.askokcancel = lambda t, m: True
        self.L.messagebox.askyesno = lambda t, m: True
        # Nein heisst "so erzeugen, wie es dasteht" - aendert nichts.
        self.L.messagebox.askyesnocancel = lambda t, m: False

    def tearDown(self):
        J.ACCEL, J.EILGANG, J.KREUZUNG, J.WATT = self._modulwerte
        app = getattr(self, "app", None)
        if app is not None and {k: app.cfg.get(k)
                                for k in self.MASCHINE} != self._cfgwerte:
            app.cfg.update(self._cfgwerte)
            self.L.P.save_config(app.cfg)
        if app is not None and app.maschinen != self._maschinen:
            self.L.P.save_maschinen(self._maschinen)
        if self.wurzel is not None:
            app_schliessen(self.wurzel, app)

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


@ohne_bildschirm
class NullpunktUeberDieSitzung(Nullpunkt):
    """Der Nullpunkt soll waehrend einer Sitzung nie verschwinden. Er tat es
    trotzdem: vom Handy aus jedes Mal, am Rechner ab und zu."""

    def gesetzt(self, mpos=(120.0, 80.0, 0.0)):
        self.app.grbl = Attrappe(mpos=mpos, app=self.app)
        self.app.set_zero()
        return self.app.grbl

    def test_stopp_vom_handy_behaelt_ihn(self):
        """fern_tun rief grbl.stop() statt app.stop() - und nur dort wird der
        Versatz vor dem Soft-Reset gemerkt."""
        g = self.gesetzt()
        g.mpos = (150.0, 95.0, 0.0)
        self.app.fern_tun("stopp")
        self.pumpe()
        self.assertEqual(g.wco, (120.0, 80.0, 0.0))
        self.assertTrue(self.app.zero_ok)

    def test_entsperren_vom_handy_holt_ihn_zurueck(self):
        g = self.gesetzt()
        echt = g.stop

        def stop_mit_alarm():
            echt()
            g.alarm = "ALARM:2"
        g.stop = stop_mit_alarm
        g.mpos = (150.0, 95.0, 0.0)
        self.app.fern_tun("stopp")
        self.pumpe()
        self.assertEqual(g.wco, (0.0, 0.0, 0.0))     # wartet noch
        self.app.fern_tun("frei")
        self.pumpe()
        self.assertEqual(g.wco, (120.0, 80.0, 0.0))

    def test_kein_zeitfenster_mehr(self):
        """Frueher verfiel die Rettung nach zwei Minuten. Wer nach einem
        STOPP erst nachsah, warum, stand danach ohne Nullpunkt da."""
        g = self.gesetzt()
        echt = g.stop

        def stop_mit_alarm():
            echt()
            g.alarm = "ALARM:2"
        g.stop = stop_mit_alarm
        self.app.stop()
        self.pumpe()
        wco, n, z, _ = self.app._rettung
        self.app._rettung = (wco, n, z, time.time() - 3600)   # eine Stunde her
        self.assertTrue(self.app._rettbar())
        self.app.unlock()
        self.pumpe()
        self.assertEqual(g.wco, (120.0, 80.0, 0.0))

    def test_versatz_gilt_die_ganze_sitzung(self):
        g = self.gesetzt()
        self.assertEqual(self.app.null_wco, (120.0, 80.0, 0.0))
        self.app.stop()
        self.pumpe()
        self.assertEqual(self.app.null_wco, (120.0, 80.0, 0.0))

    def test_zurueckholen_auch_ohne_stopp(self):
        """Das Netz unter allem anderen: ist er doch mal weg, holt man ihn."""
        g = self.gesetzt()
        g.wco = (0.0, 0.0, 0.0)
        self.app.zero_ok = False
        self.app.nullpunkt_zurueck()
        self.pumpe()
        self.assertEqual(g.wco, (120.0, 80.0, 0.0))
        self.assertTrue(self.app.zero_ok)

    def test_stopp_mitten_im_job_behaelt_ihn(self):
        """Der haeufigste Fall ueberhaupt - und der einzige, der hier
        gefehlt hat: STOPP, waehrend ein Job laeuft."""
        g = self.gesetzt()
        g.job_running = True
        g.mpos = (150.0, 95.0, 0.0)
        self.app.stop()
        self.app._event("jobend", ("Gravur", "abgebrochen"))
        self.pumpe()
        self.assertTrue(self.app.zero_ok)
        self.assertEqual(g.wco, (120.0, 80.0, 0.0))

    def test_spaetes_jobende_loescht_ihn_nicht(self):
        """Das Jobende kommt nicht immer zuerst: haengt der Sendethread noch
        in einer Quittung, trifft es erst nach der Rettung ein. Dann stand
        der Nullpunkt wieder - und wurde hier geloescht."""
        g = self.gesetzt()
        g.mpos = (150.0, 95.0, 0.0)
        self.app.stop()
        self.pumpe(0.5)
        self.assertTrue(self.app.zero_ok)          # Rettung ist durch
        self.app._event("jobend", ("Gravur", "abgebrochen"))
        self.pumpe(0.3)
        self.assertTrue(self.app.zero_ok)
        self.assertEqual(g.wco, (120.0, 80.0, 0.0))

    def test_abbruch_ohne_stopp_rettet_auch(self):
        """Zu viele Uebertragungsfehler halten den Job selbst an - dann hat
        niemand vorher etwas gemerkt, der Versatz ist aber derselbe."""
        g = self.gesetzt()
        g.mpos = (150.0, 95.0, 0.0)
        g.stop()                                   # wie _halt(): Reset
        self.pumpe(0.3)
        self.assertFalse(self.app.zero_ok)
        self.app._event("jobend", ("Gravur", "fehler"))
        self.pumpe()
        self.assertTrue(self.app.zero_ok)
        self.assertEqual(g.wco, (120.0, 80.0, 0.0))

    def test_abriss_bleibt_endgueltig(self):
        """Nach einem Abriss weiss niemand, wo der Kopf steht - da darf auch
        das Jobende nichts wiederherstellen."""
        g = self.gesetzt()
        self.app._event("jobend", ("Gravur", "verbindung"))
        self.pumpe(0.3)
        self.assertFalse(self.app.zero_ok)

    def test_fremde_firmware_ohne_startzeile(self):
        """Die Rettung hing daran, dass der Controller sich mit einer Zeile
        zurueckmeldet, die "Grbl" heisst. Der Soft-Reset ist aber unser
        eigener - eine Firmware, die sich anders meldet, darf den Nullpunkt
        nicht kosten. (Der Creality-Controller kommt die Tage.)"""
        g = self.gesetzt()
        g.melden = False                       # Startzeile wird nicht erkannt
        g.mpos = (150.0, 95.0, 0.0)
        self.app.stop()
        self.pumpe(4.0)                        # der Faden wartet 3 s darauf
        self.assertTrue(self.app.zero_ok)
        self.assertEqual(g.wco, (120.0, 80.0, 0.0))

    def test_nullpunkt_auf_der_maschinennull_ueberlebt_auch(self):
        """Wer ihn setzt, ohne vorher zu fahren, hat den Versatz (0, 0, 0) -
        nach dem Verbinden steht die Maschine auf ihrer eigenen Null. Genau
        der galt als "nichts gemerkt": kein G92 zurueck, und X0 Y0 war
        danach die Null der Maschine, nicht die des Werkstuecks."""
        g = self.gesetzt(mpos=(0.0, 0.0, 0.0))
        self.assertEqual(self.app.null_wco, (0.0, 0.0, 0.0))
        g.mpos = (30.0, 15.0, 0.0)
        self.app.stop()
        self.pumpe()
        self.assertTrue(self.app.zero_ok)
        self.assertIn("G92 X30.000 Y15.000 Z0.000", g.protokoll)
        self.app.goto_zero()
        self.pumpe(0.6)
        self.assertEqual(g.mpos[:2], (0.0, 0.0))

    def test_maschinennull_auch_vom_handy(self):
        g = self.gesetzt(mpos=(0.0, 0.0, 0.0))
        g.mpos = (30.0, 15.0, 0.0)
        self.app.fern_tun("stopp")
        self.pumpe()
        self.assertTrue(self.app.zero_ok)
        self.assertIn("G92 X30.000 Y15.000 Z0.000", g.protokoll)

    def test_maschinennull_laesst_sich_zurueckholen(self):
        """Derselbe Fehler steckte im Knopf 'Nullpunkt zurückholen'."""
        g = self.gesetzt(mpos=(0.0, 0.0, 0.0))
        g.mpos, g.wco = (30.0, 15.0, 0.0), (0.0, 0.0, 0.0)
        self.app.zero_ok = False
        antwort = self.app.nullpunkt_zurueck()
        self.pumpe()
        self.assertNotIn("Kein Nullpunkt", antwort)
        self.assertTrue(self.app.zero_ok)
        self.assertIn("G92 X30.000 Y15.000 Z0.000", g.protokoll)

    def test_nach_abriss_wird_nichts_zurueckgeholt(self):
        """Nach einem USB-Abriss weiss niemand mehr, wo der Kopf steht - ein
        wiederhergestellter Versatz waere schlimmer als keiner."""
        g = self.gesetzt()
        self.app._event("lost", "Port weg")
        self.assertIsNone(self.app.null_wco)
        antwort = self.app.nullpunkt_zurueck()
        self.pumpe(0.4)
        self.assertIn("Kein Nullpunkt", antwort)
        self.assertEqual(g.wco, (120.0, 80.0, 0.0))   # unveraendert, kein G92

    def test_neu_verbinden_vergisst_ihn(self):
        self.gesetzt()
        self.app.toggle_connect()                     # trennt
        self.assertIsNone(self.app.null_wco)

    def test_knopf_holt_ihn_auch(self):
        g = self.gesetzt()
        g.wco = (0.0, 0.0, 0.0)
        self.app.null_zurueck_knopf()
        self.pumpe()
        self.assertEqual(g.wco, (120.0, 80.0, 0.0))

    def test_knopf_deckt_nichts_zu(self):
        """Die Lehre aus der Jobleiste: zwei Widgets in derselben Zelle
        decken sich lautlos."""
        b = self.app.btn_null_zurueck
        # Der Knopf sitzt auf dem Maschinenreiter: der muss gewaehlt und das
        # Fenster sichtbar sein, sonst liegt gar nichts auf dem Schirm.
        self.app.nb.select(2)
        self.wurzel.deiconify()
        self.wurzel.update()
        x = b.winfo_rootx() + b.winfo_width() // 2
        y = b.winfo_rooty() + b.winfo_height() // 2
        self.assertIs(self.wurzel.winfo_containing(x, y), b)


@ohne_bildschirm
class PresetsMerkenDenSchnitt(Grundlage):
    """Durchgaenge, Schnitt-S und Schnitt-F gehoeren ins Preset. Sie kosten
    am meisten Zeit zum Herausfinden und standen bisher nirgends - ein halber
    Tag Erle fuer drei Zahlen, und beim naechsten Start waren sie weg."""

    def test_werte_gehen_hin_und_zurueck(self):
        self.app.v_dicke.set(12.0)
        self.app.v_passes.set(5)
        self.app.v_cs.set(725)
        self.app.v_cf.set(300)
        self.app.v_pname.set("Erle 3")
        self.app.save_preset()

        self.app.v_passes.set(1)
        self.app.v_cs.set(0)
        self.app.v_cf.set(0)
        self.app.v_preset.set("Erle 3")
        self.app.load_preset()
        self.assertEqual(self.app.v_passes.get(), 5)
        self.assertEqual(self.app.v_cs.get(), 725)
        self.assertEqual(self.app.v_cf.get(), 300)

    def test_ueberlebt_ein_neues_fenster(self):
        self.app.v_passes.set(5)
        self.app.v_cs.set(725)
        self.app.v_cf.set(300)
        self.app.v_pname.set("Erle 3")
        self.app.save_preset()
        app_schliessen(self.wurzel, self.app)
        self.wurzel, self.app, self.L = app_bauen()
        self.app.v_preset.set("Erle 3")
        self.app.load_preset()
        self.assertEqual(self.app.v_passes.get(), 5)
        self.assertEqual(self.app.v_cs.get(), 725)

    def test_altes_preset_ohne_schnittwerte(self):
        """Presets von vorher haben die Felder nicht. 0 heisst 'nimm die vom
        Material', ein Durchgang - genau das Verhalten von frueher."""
        self.app.presets["alt"] = dict(dicke=3.0, korrektur=0.0, s=830, f=1000,
                                       line=0.1, mode="schwelle", schwelle=0.5)
        self.app.v_passes.set(7)
        self.app.v_cs.set(900)
        self.app.v_preset.set("alt")
        self.app.load_preset()
        self.assertEqual(self.app.v_passes.get(), 1)
        self.assertEqual(self.app.v_cs.get(), 0)
        self.assertEqual(self.app.v_cf.get(), 0)

    def test_mitgeliefertes_erle_preset_passt_zur_messung(self):
        d = self.L.P.DEFAULTS["Erle 3 mm (Schnitt)"]
        energie = 0.33 * d["schnitt_s"] / d["schnitt_f"] * d["durchgaenge"]
        self.assertAlmostEqual(energie, 3.99, places=2)


@ohne_bildschirm
class Verwerfen(Grundlage):
    """Geladenen G-Code wieder loswerden. clear_motif konnte das immer, aber
    es gab keinen Knopf - eine geladene .nc blieb, bis man eine andere lud."""

    def nc(self, text="G21\nG90\nM4 S0\nG0 X10 Y10\nG1 X40 Y10 S300 F600\n"
                      "G1 S0\nM5\nG0 X0 Y0\n"):
        import os
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), "j.nc")
        with open(p, "w") as f:
            f.write(text)
        self.L.filedialog.askopenfilename = lambda **k: p
        self.app.load_gcode()
        return p

    def test_geladener_gcode_geht_wieder_weg(self):
        self.nc()
        self.assertIsNotNone(self.app.lines)
        self.app.verwerfen()
        self.assertIsNone(self.app.lines)
        self.assertIsNone(self.app.info)
        self.assertIsNone(self.app.src_path)
        self.assertEqual(self.app.lbl_info.cget("text"), "")

    def test_ohne_nachfrage_wenn_nur_gcode_geladen_ist(self):
        gefragt = []
        self.L.messagebox.askyesno = lambda t, m: (gefragt.append(m), True)[1]
        self.nc()
        self.app.verwerfen()
        self.assertEqual(gefragt, [])

    def test_bei_gesetzten_motiven_wird_gefragt(self):
        """Ein geladener G-Code ist mit einem Griff wieder da. Gesetzte
        Motive sind Arbeit."""
        gefragt = []
        self.L.messagebox.askyesno = lambda t, m: (gefragt.append(m), False)[1]
        self.motiv()
        self.app.verwerfen()
        self.assertTrue(gefragt)
        self.assertTrue(self.app.elemente)          # Nein heisst nein

    def test_ja_wirft_die_motive_weg(self):
        self.L.messagebox.askyesno = lambda t, m: True
        self.motiv()
        self.app.verwerfen()
        self.assertEqual(self.app.elemente, [])
        self.assertIsNone(self.app.src)

    def test_leer_passiert_nichts(self):
        self.L.messagebox.askyesno = lambda t, m: self.fail("nichts zu fragen")
        self.app.verwerfen()
        self.assertIsNone(self.app.lines)

    def test_knopf_deckt_nichts_zu(self):
        """Die Lehre aus der Jobleiste. Anklicken laesst sich der Knopf hier
        nicht pruefen - die Reihe liegt im Rollbereich weit unten -, also
        wird die Geometrie innerhalb der Reihe geprueft."""
        self.wurzel.deiconify()
        self.wurzel.update()
        k = [(c.winfo_x(), c.winfo_y(), c.winfo_width(), c.winfo_height())
             for c in self.app.btn_weg.master.winfo_children()]
        self.assertEqual(len(k), 3)
        for i in range(len(k)):
            for j in range(i + 1, len(k)):
                a, b = k[i], k[j]
                quer = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
                hoch = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
                self.assertLessEqual(min(quer, hoch), 0,
                                     "%r deckt %r zu" % (a, b))


@ohne_bildschirm
class FokusUeberlebtDenNeustart(Grundlage):
    """Materialdicke und Fokuskorrektur standen nur in der Oberflaeche und in
    Presets. Wer kein Preset von Hand speicherte, fing nach jedem Start wieder
    bei 0,0 an - und schnitt ausser Fokus weiter, ohne dass sich sichtbar
    etwas geaendert haette. Genau so ist es passiert."""

    def test_gemessene_korrektur_wird_sofort_gesichert(self):
        self.app.v_dicke.set(12.0)
        self.app.fokus_zs = [10.0, 11.0, 12.0, 13.0, 14.0]
        self.app.lb_fz.delete(0, "end")
        for z in self.app.fokus_zs:
            self.app.lb_fz.insert("end", "Z %.2f" % z)
        self.app.lb_fz.selection_set(4)          # 14.0 -> Korrektur +2,00
        self.app.take_focus()
        self.assertAlmostEqual(self.app.v_korr.get(), 2.0, places=3)
        self.assertAlmostEqual(self.L.P.load_config()["korrektur"], 2.0, places=3)

    def test_neues_fenster_bringt_sie_mit(self):
        self.app.v_dicke.set(3.0)
        self.app.v_korr.set(-1.75)
        self.app._save_cfg()
        app_schliessen(self.wurzel, self.app)
        self.wurzel, self.app, self.L = app_bauen()
        self.assertAlmostEqual(self.app.v_dicke.get(), 3.0, places=3)
        self.assertAlmostEqual(self.app.v_korr.get(), -1.75, places=3)
        self.assertAlmostEqual(self.app._z_target(), 1.25, places=3)

    def test_preset_laden_sichert_die_dicke(self):
        self.app.presets["Erle 3"] = dict(dicke=3.0, s=740, f=230, line=0.1,
                                          mode="schwelle")
        self.app.v_preset.set("Erle 3")
        self.app.load_preset()
        self.assertAlmostEqual(self.L.P.load_config()["dicke"], 3.0, places=3)

    def test_halb_getipptes_feld_zerschiesst_nichts(self):
        self.app.v_korr.set(-1.0)
        self.app._save_cfg()
        self.app.v_korr.set("")                  # mitten im Tippen
        self.app._save_cfg()
        self.assertAlmostEqual(self.L.P.load_config()["korrektur"], -1.0, places=3)

    def test_kein_preset_fasst_die_korrektur_an(self):
        """Die Korrektur sagt, wo die Brennebene zur Z-Referenz liegt - das
        haengt an der Maschine, nicht am Material. Lief sie in jedem Preset
        mit, nahm ein Preset mit alter oder nie gemessener Zahl die frische
        Messung mit, ohne dass sich sichtbar etwas aenderte."""
        self.app.v_dicke.set(12.0)
        self.app.v_korr.set(4.0)
        self.app._save_cfg()
        for d in (dict(dicke=3.0, s=740, f=230, line=0.1, mode="schwelle"),
                  dict(dicke=3.0, korrektur=0.0, s=740, f=230, line=0.1,
                       mode="schwelle")):
            with self.subTest(korrektur=d.get("korrektur")):
                self.app.presets["alt"] = d
                self.app.v_preset.set("alt")
                self.app.load_preset()
                self.assertAlmostEqual(self.app.v_dicke.get(), 3.0, places=3)
                self.assertAlmostEqual(self.app.v_korr.get(), 4.0, places=3)
                self.assertAlmostEqual(self.L.P.load_config()["korrektur"],
                                       4.0, places=3)

    def test_gespeichertes_preset_traegt_sie_nicht_mehr(self):
        self.app.v_korr.set(4.0)
        self.app.v_pname.set("Linde 3")
        self.app.save_preset()
        self.assertNotIn("korrektur", self.app.presets["Linde 3"])
        self.assertNotIn("korrektur", self.L.P.load_presets()["Linde 3"])

    def test_mitgelieferte_presets_sind_frei_davon(self):
        for name, d in self.L.P.DEFAULTS.items():
            self.assertNotIn("korrektur", d, name)

    def test_beide_beschriftungen_zeigen_die_hoehe(self):
        """Der Wert wirkt still weiter - man muss sehen, welche Z-Hoehe
        daraus wird, ohne einen neuen Test zu fahren."""
        self.app.v_dicke.set(12.0)
        self.app.v_korr.set(-0.3)
        for lbl in (self.app.lbl_fokus, self.app.lbl_zhoehe):
            # Deutsche Oberflaeche: Komma, und ein echtes Minuszeichen.
            self.assertIn("11,70", lbl.cget("text"))
            self.assertIn("−0,30", lbl.cget("text"))

    def test_von_hand_gesetzt_wird_auch_gesichert(self):
        """Ohne das bliebe ein neuer Fokustest der einzige Weg zu einem
        anderen Wert."""
        self.app.v_korr.set(-0.8)
        self.assertIsNotNone(self.app._fokus_job)
        self.app.root.after_cancel(self.app._fokus_job)
        self.app._fokus_spaet()                  # statt der Wartezeit
        self.assertAlmostEqual(self.L.P.load_config()["korrektur"], -0.8,
                               places=3)
        self.assertIsNone(self.app._fokus_job)

    def test_beenden_sichert_den_offenen_wert(self):
        """Der Wert wird verzoegert geschrieben. Wer das Fenster vorher
        zumacht, haette ihn sonst verloren - oder der Zeitgeber liefe in ein
        zerstoertes Fenster."""
        self.app.v_korr.set(3.5)
        self.assertIsNotNone(self.app._fokus_job)
        self.app.beenden(fragen=False)
        self.assertIsNone(self.app._fokus_job)
        self.assertAlmostEqual(self.L.P.load_config()["korrektur"], 3.5,
                               places=3)
        self.wurzel, self.app, self.L = app_bauen()

    def test_start_sagt_was_noch_gilt(self):
        self.app.v_dicke.set(3.0)
        self.app.v_korr.set(-1.25)
        self.app._save_cfg()
        app_schliessen(self.wurzel, self.app)
        self.wurzel, self.app, self.L = app_bauen()
        t = self.app.log.get("1.0", "end")
        self.assertIn("-1.25", t)
        self.assertIn("1.75", t)                 # 3,00 - 1,25


@ohne_bildschirm
class LaufzeitLerntDazu(Grundlage):
    """Die Schaetzung stand bisher nur da; ob sie stimmt, erfuhr niemand -
    bis ein Job eine Viertelstunde laenger lief als angesagt. Jetzt wird
    nach jedem fertigen Job verglichen und gemerkt."""

    def setUp(self):
        super().setUp()
        # Die Wegwerf-Konfiguration haelt die ganze Klasse durch - jeder
        # Test faengt hier aber bei null Messungen an.
        self.app.cfg["zeitmessungen"] = []
        self.L.P.save_config(self.app.cfg)

    def test_ohne_messungen_bleibt_das_modell_stehen(self):
        self.assertEqual(self.app._zeitfaktor(), 1.0)
        self.assertAlmostEqual(self.app._min(600.0), 10.0, places=6)

    def test_ein_lauf_aendert_noch_nichts(self):
        """So ist der alte Faktor 0,80 entstanden: aus einem einzigen Lauf."""
        self.app._zeit_merken(1800.0, 1200.0)
        self.assertEqual(self.app.cfg["zeitmessungen"], [1.5])
        self.assertEqual(self.app._zeitfaktor(), 1.0)

    def test_ab_drei_laeufen_zaehlt_der_median(self):
        for echt in (1500.0, 1800.0, 1560.0):
            self.app._zeit_merken(echt, 1200.0)
        self.assertEqual(self.app._zeitfaktor(), 1.3)
        self.assertAlmostEqual(self.app._min(1200.0), 26.0, places=6)

    def test_ein_ausreisser_zieht_nicht_alles_mit(self):
        for echt in (1200.0, 1260.0, 1200.0, 6000.0, 1230.0):
            self.app._zeit_merken(echt, 1200.0)
        self.assertLess(self.app._zeitfaktor(), 1.1)

    def test_gemerkt_wird_gegen_das_rohe_modell(self):
        """Sonst rechnet der Faktor gegen die schon korrigierte Ansage und
        wandert mit jedem Lauf zurueck auf eins."""
        for _ in range(3):
            self.app._zeit_merken(2400.0, 1200.0)
        self.assertEqual(self.app._zeitfaktor(), 2.0)
        self.app._zeit_merken(2400.0, 1200.0)
        self.assertEqual(self.app.cfg["zeitmessungen"][-1], 2.0)

    def test_kurze_laeufe_lehren_nichts(self):
        self.app._zeit_merken(100.0, 90.0)
        self.assertEqual(self.app.cfg.get("zeitmessungen"), [])

    def test_mehr_als_zehn_werden_nicht_gesammelt(self):
        for k in range(14):
            self.app._zeit_merken(1200.0 + k, 1200.0)
        self.assertEqual(len(self.app.cfg["zeitmessungen"]), 10)

    def test_ueberlebt_das_fenster(self):
        for echt in (1500.0, 1800.0, 1560.0):
            self.app._zeit_merken(echt, 1200.0)
        app_schliessen(self.wurzel, self.app)
        self.wurzel, self.app, self.L = app_bauen()
        self.assertEqual(self.app._zeitfaktor(), 1.3)

    def test_das_protokoll_sagt_beide_zahlen(self):
        self.app._zeit_merken(1800.0, 1200.0)
        t = self.app.log.get("1.0", "end")
        self.assertIn("20 min angesagt", t)
        self.assertIn("30 min gebraucht", t)
        self.assertIn("+50 %", t)


@ohne_bildschirm
class FernPauseUndWeiter(Grundlage):
    def test_pause_haelt_am_zeilenende(self):
        self.app.grbl.job_running = True
        self.app.v_pause_ende.set(True)
        self.app.fern_tun("pause")
        self.assertIn("Pause am Zeilenende", self.app.grbl.protokoll)

    def test_pause_ohne_schalter_ist_feed_hold(self):
        self.app.grbl.job_running = True
        self.app.v_pause_ende.set(False)
        self.app.fern_tun("pause")
        self.assertIn("Pause", self.app.grbl.protokoll)

    def test_weiter_setzt_fort(self):
        self.app.grbl.job_running = True
        self.app.fern_tun("weiter")
        self.assertIn("Weiter", self.app.grbl.protokoll)

    def test_ohne_job_passiert_nichts(self):
        self.app.grbl.job_running = False
        for a in ("pause", "weiter"):
            self.assertIn("kein Job", self.app.fern_tun(a))
        self.assertNotIn("Pause", self.app.grbl.protokoll)
        self.assertNotIn("Weiter", self.app.grbl.protokoll)

    def test_schon_pausiert(self):
        self.app.grbl.job_running = True
        self.app.grbl.pausiert = True
        self.assertIn("Steht schon", self.app.fern_tun("pause"))

    def test_jobsperre_nennt_die_beiden(self):
        self.app.grbl.job_running = True
        antwort = self.app.fern_tun("jog", ("x", 1.0))
        self.assertIn("/pause", antwort)
        self.assertIn("/weiter", antwort)


class Projektrundlauf(Grundlage):
    def test_alle_werte_kommen_zurueck(self):
        import os
        import tempfile
        ordner = tempfile.mkdtemp(prefix="laserwerk-gui-")
        quelle = os.path.join(ordner, "motiv.png")
        Image.new("L", (400, 200), 30).save(quelle)
        ziel = os.path.join(ordner, "p.lwp")
        self.L.filedialog.askopenfilenames = lambda **k: (quelle,)
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
    def test_vorgabe_rechnet_selbst(self):
        """Die Vorgabe war 1,5 mm - der Wert, den man ueberall abschreibt und
        der bei F1000 nur ein Drittel des Anlaufwegs ist. Schlimmer: er stand
        nach jedem Neustart wieder da, weil er nirgends gesichert wird. Wer
        seinen Rechner neu startete, gravierte danach mit zu schwachen
        Zeilenanfaengen weiter, ohne dass sich etwas sichtbar geaendert hat."""
        self.assertEqual(self.app.v_over.get(), 0.0)
        self.app.cfg["accel"] = 30.0
        self.app.v_f.set(1000)
        self.assertGreater(self.app._anlauf(), 4.63)

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
        self.app.grbl.settings["121"] = 250.0
        self.app._einstellungen_pruefen(self.app.grbl.settings)
        self.assertEqual(self.app.cfg["accel"], 250.0)
        self.assertEqual(J.ACCEL, 250.0)

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
        self.L.filedialog.askopenfilenames = lambda **k: (p,)
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
        self.L.filedialog.askopenfilenames = lambda **k: (p,)
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

    def test_schnitt_steht_genau_einmal_im_job(self):
        """Er stand zweimal drin: einmal vor der Beschriftung des Infofelds
        und einmal danach. Gemerkt haette man es erst am Werkstueck - der
        zweite Satz Durchgaenge faehrt ueber Teile, die schon lose sind."""
        self.svg_laden()
        self.app.v_job.set("beides")
        self.app.generate()
        kopfe = [i for i, z in enumerate(self.app.lines)
                 if z.startswith("; Laserwerk Schnitt")]
        self.assertEqual(len(kopfe), 1, "Schnitt mehrfach im Job")

    def test_schnittweg_wird_einfach_gezaehlt(self):
        self.svg_laden()
        self.app.v_job.set("schnitt")
        self.app.generate()
        allein = self.app.info["cut_m"]
        self.app.v_job.set("gravur")
        self.app.generate()
        gravur = self.app.info["cut_m"]
        self.app.v_job.set("beides")
        self.app.generate()
        self.assertAlmostEqual(self.app.info["cut_m"], gravur + allein, places=6)
        self.assertAlmostEqual(self.app.info["schnitt_m"], allein, places=6)

    def test_konturmarken_liegen_hinter_der_gravur(self):
        """Ohne sie bliebe die Anzeige den ganzen Schnitt ueber auf der
        letzten Gravurzeile stehen."""
        self.svg_laden()
        self.app.v_job.set("beides")
        self.app.generate()
        marken = self.app.info["marken"]
        schnitt = next(i for i, z in enumerate(self.app.lines)
                       if z.startswith("; Laserwerk Schnitt"))
        konturen = [m for m in marken if m[1] == "kontur"]
        self.assertTrue(konturen, "keine Konturmarken im gemischten Job")
        self.assertTrue(all(m[0] >= schnitt for m in konturen))
        self.assertTrue(all(m[0] < schnitt for m in marken if m[1] == "zeile"))
        self.assertEqual([m[0] for m in marken], sorted(m[0] for m in marken))

    def test_anzeige_zaehlt_im_schnitt_konturen(self):
        self.svg_laden()
        self.app.v_job.set("beides")
        self.app.generate()
        self.app.marken = self.app.info["marken"]
        self.app._marken_idx = [m[0] for m in self.app.marken]
        letzte = self.app.marken[-1]
        self.assertIn("Kontur", self.app._marke_text(letzte[0]))
        erste = next(m for m in self.app.marken if m[1] == "zeile")
        self.assertIn("Zeile", self.app._marke_text(erste[0]))

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
        self.L.filedialog.askopenfilenames = lambda **k: (p,)
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
        self.L.filedialog.askopenfilenames = lambda **k: (png,)
        self.app.open_image()
        self.app.v_mode.set("schwelle")
        self.app.v_w.set(60.0)
        self.app._keep_ratio("w")
        self.app.center_motif()
        self.L.filedialog.askopenfilenames = lambda **k: (svg,)
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
        # Deutsche Oberflaeche: Komma.
        self.assertTrue(any("63,5" in t and "31,8" in t for t in texte), texte)

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
        self.L.filedialog.askopenfilenames = lambda **k: (self.svg(),)
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
        self.L.filedialog.askopenfilenames = lambda **k: (p,)
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
        self.L.filedialog.askopenfilenames = lambda **k: (p,)
        self.app.open_image()
        self.app.v_job.set("schnitt")
        self.app.generate()
        marken = self.app.info["marken"]
        self.assertTrue(marken)
        self.assertEqual(marken[0][1], "kontur")

    def test_zaehler_verschwindet_am_ende(self):
        """Nach dem Job steht dort wieder die Position - aber keine Zeile
        aus einem Job, der vorbei ist."""
        self.motiv()
        self.app.lbl_marke.configure(text="Zeile 5 von 9")
        self.app._event("jobend", ("Gravur", "fertig"))
        self.assertNotIn("Zeile", self.app.lbl_marke.cget("text"))


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


class Skalieren(Grundlage):
    """Groesse eintippen, umschalten, ziehen.

    Hier steckten vier Fehler, die zusammen das Skalieren unbrauchbar
    gemacht haben: das Umschalten der Bearbeitung setzte die Groesse aufs
    Maximum zurueck, eine gerade Linie bekam das Seitenverhaeltnis 1
    (Strich wird Quadrat) oder 0 (Breite wird null), eine senkrechte Linie
    liess das Laden mit Division durch null abstuerzen, und beim Ziehen
    wurde jeder Richtung ein Mindestmass von 2 mm aufgezwungen.
    """

    RECHTECK = '''<svg xmlns="http://www.w3.org/2000/svg" width="40mm"
 height="20mm" viewBox="0 0 40 20"><rect x="1" y="1" width="38" height="18"
 fill="none" stroke="black"/></svg>'''
    WAAGRECHT = '''<svg xmlns="http://www.w3.org/2000/svg" width="50mm"
 height="10mm" viewBox="0 0 50 10"><path d="M 5 5 L 45 5" fill="none"
 stroke="black"/></svg>'''
    SENKRECHT = '''<svg xmlns="http://www.w3.org/2000/svg" width="10mm"
 height="50mm" viewBox="0 0 10 50"><path d="M 5 5 L 5 45" fill="none"
 stroke="black"/></svg>'''

    def svg(self, inhalt):
        import tempfile
        f = tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False)
        f.write(inhalt)
        f.close()
        self.assertTrue(self.app.lade_motiv(f.name, fragen=False))
        return f.name

    # ---------------------------------------------------- Umschalten
    def test_umschalten_haelt_die_groesse(self):
        self.svg(self.RECHTECK)
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        h = self.app.v_h.get()
        self.app.v_job.set("schnitt")
        self.app._job_changed()
        self.assertEqual(self.app.v_w.get(), 40.0)
        self.assertAlmostEqual(self.app.v_h.get(), h, delta=1.0)

    def test_umschalten_springt_nicht_aufs_maximum(self):
        self.svg(self.RECHTECK)
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        for ziel in ("schnitt", "beides", "gravur"):
            self.app.v_job.set(ziel)
            self.app._job_changed()
            self.assertNotEqual(self.app.v_w.get(), self.app.v_maxw.get())

    def test_umschalten_wirft_den_gcode_weg(self):
        self.svg(self.RECHTECK)
        self.app.v_w.set(40.0); self.app._keep_ratio("w")
        self.app.generate()
        self.assertIsNotNone(self.app.lines)
        self.app.v_job.set("schnitt")
        self.app._job_changed()
        self.assertIsNone(self.app.lines)

    # ---------------------------------------------------- Gerade Linien
    def test_waagrechte_linie_wird_kein_quadrat(self):
        self.svg(self.WAAGRECHT)
        self.app.v_job.set("schnitt")
        self.app._job_changed()
        self.assertIsNone(self.app._aspect())
        self.app.v_w.set(100.0)
        self.app._keep_ratio("w")
        self.assertEqual(self.app.v_w.get(), 100.0)
        self.assertNotEqual(self.app.v_h.get(), 100.0)

    def test_senkrechte_linie_laedt_ohne_absturz(self):
        """Ging frueher mit ZeroDivisionError unter, wenn beim Laden
        schon 'Schneiden' eingestellt war."""
        self.svg(self.RECHTECK)
        self.app.v_job.set("schnitt")
        self.app._job_changed()
        self.svg(self.SENKRECHT)
        self.assertEqual(self.app.v_w.get(), 0.0)
        self.assertGreater(self.app.v_h.get(), 0.0)

    def test_laenge_der_linie_laesst_sich_eintippen(self):
        self.svg(self.SENKRECHT)
        self.app.v_job.set("schnitt")
        self.app._job_changed()
        for ziel in (40.0, 120.0, 7.5):
            self.app.v_h.set(ziel)
            self.app._keep_ratio("h")
            self.assertEqual(self.app.v_h.get(), ziel)

    def test_rahmen_zeigt_die_echte_linie(self):
        """Der gezeichnete Kasten muss dem Schnitt entsprechen - sonst
        steht die Linie woanders als der Rahmen."""
        self.svg(self.WAAGRECHT)
        self.app.v_job.set("schnitt")
        self.app._job_changed()
        self.app.v_w.set(80.0); self.app.v_h.set(13.0)
        x, y, b, h = self.app._box()
        self.assertAlmostEqual(b, 80.0, places=2)
        self.assertAlmostEqual(h, 0.0, places=2)

    def test_ziehen_nagelt_die_linie_nicht_auf_2mm(self):
        import types
        self.svg(self.WAAGRECHT)
        self.app.v_job.set("schnitt")
        self.app._job_changed()
        self.app.v_bw.set(200.0); self.app.v_bh.set(120.0)
        self.app.v_w.set(50.0); self.app.v_h.set(0.0)
        self.app.v_xoff.set(10.0); self.app.v_yoff.set(20.0)
        self.app.v_snap.set(False)
        x, y, b, h = self.app._box()
        px, py = self.app._mm(x + b, y)              # rechte Ecke
        self.app._press(types.SimpleNamespace(x=int(round(px)), y=int(round(py))))
        self.assertIsNotNone(self.app.drag)
        self.assertEqual(self.app.drag[0], "size")
        ziel = self.app._mm(x + 90.0, y)
        self.app._drag_move(types.SimpleNamespace(x=int(round(ziel[0])),
                                                  y=int(round(ziel[1]))))
        self.app.drag = None
        self.assertAlmostEqual(self.app.v_w.get(), 90.0, delta=1.5)
        self.assertEqual(self.app.v_h.get(), 0.0)

    def test_gravieren_ohne_flaeche_wird_abgelehnt(self):
        self.svg(self.SENKRECHT)
        self.app.v_job.set("schnitt")
        self.app._job_changed()
        self.app.v_job.set("gravur")                 # von Hand, trotz Breite 0
        self.app.v_w.set(0.0)
        self.gezeigt.clear()
        self.app.generate()
        self.assertTrue(self.gezeigt)
        self.assertIsNone(self.app.lines)

    def test_einpassen_fuellt_die_laenge(self):
        self.svg(self.WAAGRECHT)
        self.app.v_job.set("schnitt")
        self.app._job_changed()
        self.app.fit()
        self.assertEqual(self.app.v_w.get(), self.app.v_maxw.get())
        self.assertEqual(self.app.v_h.get(), 0.0)

    # ---------------------------------------------------- Normalfall
    def test_originalgroesse_bleibt_beim_fokuswechsel(self):
        self.svg(self.RECHTECK)
        self.app.v_job.set("schnitt")
        self.app._job_changed()
        self.app.original_size()
        w, h = self.app.v_w.get(), self.app.v_h.get()
        self.app._keep_ratio("w")                    # FocusOut
        self.assertEqual((self.app.v_w.get(), self.app.v_h.get()), (w, h))

    def test_verhaeltnis_bleibt_beim_eintippen(self):
        self.svg(self.RECHTECK)
        self.app.v_w.set(76.0)
        self.app._keep_ratio("w")
        a = self.app._aspect()
        self.assertAlmostEqual(self.app.v_w.get() / self.app.v_h.get(), a,
                               places=2)


class GezeichneteFormen(Grundlage):
    """Rechteck und Rahmen aus dem Programm heraus, ohne Datei."""

    def test_rechteck_wird_ein_element(self):
        self.assertTrue(self.app.form_rechteck(80.0, 50.0))
        self.assertEqual(len(self.app.elemente), 1)
        self.assertEqual(self.app.v_job.get(), "schnitt")
        self.assertEqual((self.app.v_w.get(), self.app.v_h.get()), (80.0, 50.0))
        self.assertIsNone(self.app.src_path)

    def test_rechteck_bleibt_massgenau(self):
        """1:1, nicht eingepasst - 80 x 50 soll 80 x 50 ergeben."""
        self.app.form_rechteck(80.0, 50.0)
        self.app.v_xoff.set(10.0); self.app.v_yoff.set(5.0)
        self.app.generate()
        self.assertIsNotNone(self.app.lines)
        x0, x1, y0, y1 = J.brenn_extent(self.app.lines)
        self.assertAlmostEqual(x1 - x0, 80.0, delta=0.05)
        self.assertAlmostEqual(y1 - y0, 50.0, delta=0.05)
        self.assertAlmostEqual(x0, 10.0, delta=0.05)
        self.assertAlmostEqual(y0, 5.0, delta=0.05)

    def test_null_masse_werden_abgelehnt(self):
        self.gezeigt.clear()
        self.assertFalse(self.app.form_rechteck(0.0, 50.0))
        self.assertTrue(self.gezeigt)

    def test_rahmen_legt_sich_um_das_motiv(self):
        self.motiv(400, 200)
        self.app.v_w.set(80.0); self.app.v_h.set(40.0)
        self.app.v_xoff.set(20.0); self.app.v_yoff.set(15.0)
        self.assertTrue(self.app.rahmen_um_motiv(5.0))
        self.assertEqual(len(self.app.elemente), 2)
        self.assertEqual((self.app.v_w.get(), self.app.v_h.get()), (90.0, 50.0))
        self.assertEqual((self.app.v_xoff.get(), self.app.v_yoff.get()),
                         (15.0, 10.0))

    def test_rahmen_ist_konzentrisch_zum_motiv(self):
        self.motiv(400, 200)
        self.app.v_w.set(80.0); self.app.v_h.set(40.0)
        self.app.v_xoff.set(20.0); self.app.v_yoff.set(15.0)
        mx = 20.0 + 80.0 / 2
        my = 15.0 + 40.0 / 2
        self.app.rahmen_um_motiv(7.5)
        x, y, b, h = self.app._box()
        self.assertAlmostEqual(x + b / 2, mx, places=2)
        self.assertAlmostEqual(y + h / 2, my, places=2)

    def test_rahmen_am_rand_wird_gemeldet(self):
        self.motiv(400, 200)
        self.app.v_w.set(80.0); self.app.v_h.set(40.0)
        self.app.v_xoff.set(1.0); self.app.v_yoff.set(1.0)
        self.app.rahmen_um_motiv(5.0)
        self.assertEqual(self.app.v_xoff.get(), 0.0)
        self.assertEqual(self.app.v_yoff.get(), 0.0)

    def test_ohne_motiv_kein_rahmen(self):
        self.gezeigt.clear()
        self.assertFalse(self.app.rahmen_um_motiv(5.0))
        self.assertTrue(self.gezeigt)

    def test_gravur_und_rahmen_in_einem_lauf(self):
        self.motiv(400, 200)
        self.app.v_mode.set("schwelle")
        self.app.v_w.set(60.0); self.app.v_h.set(30.0)
        self.app.v_xoff.set(20.0); self.app.v_yoff.set(20.0)
        self.app.rahmen_um_motiv(5.0)
        self.app.generate()
        self.assertIsNotNone(self.app.lines)
        x0, x1, y0, y1 = J.brenn_extent(self.app.lines)
        self.assertAlmostEqual(x0, 15.0, delta=0.2)      # Rahmenkante
        self.assertAlmostEqual(x1, 85.0, delta=0.2)

    def test_projekt_haelt_die_form_ohne_datei(self):
        import tempfile, os
        self.app.form_rechteck(70.0, 45.0, 3.0)
        self.app.v_xoff.set(12.0)
        p = os.path.join(tempfile.mkdtemp(prefix="laserwerk-form-"), "p.lwp")
        self.L.filedialog.asksaveasfilename = lambda **k: p
        self.app.save_project()
        self.assertTrue(os.path.exists(p))
        import json
        with open(p) as f:
            d = json.load(f)
        self.assertEqual(d["elemente"][0]["form"]["art"], "rechteck")
        self.assertNotIn("vorlage", d["elemente"][0])     # kein Bild eingebettet
        self.app.clear_motif()
        self.L.filedialog.askopenfilename = lambda **k: p
        self.app.open_project()
        self.assertEqual(len(self.app.elemente), 1)
        self.assertEqual(self.app.elemente[0]["form"]["r"], 3.0)
        self.assertEqual((self.app.v_w.get(), self.app.v_h.get()), (70.0, 45.0))
        self.assertEqual(self.app.v_xoff.get(), 12.0)

    def test_form_laesst_sich_verschieben_und_ziehen(self):
        import types
        self.app.form_rechteck(60.0, 40.0)
        self.app.v_bw.set(200.0); self.app.v_bh.set(120.0)
        self.app.v_xoff.set(20.0); self.app.v_yoff.set(20.0)
        self.app.v_snap.set(False)
        x, y, b, h = self.app._box()
        p = self.app._mm(x + b / 2, y + h / 2)
        q = self.app._mm(x + b / 2 + 10.0, y + h / 2)
        self.app._press(types.SimpleNamespace(x=int(round(p[0])), y=int(round(p[1]))))
        self.assertEqual(self.app.drag[0], "move")
        self.app._drag_move(types.SimpleNamespace(x=int(round(q[0])),
                                                  y=int(round(q[1]))))
        self.app.drag = None
        self.assertAlmostEqual(self.app.v_xoff.get(), 30.0, delta=1.0)

    def _dialog_bedienen(self, knopf):
        """Den naechsten modalen Dialog anklicken, sobald er da ist."""
        def tun():
            for k in self.wurzel.winfo_children():
                if k.winfo_class() == "Toplevel":
                    for kind in k.winfo_children():
                        for b in kind.winfo_children():
                            if b.winfo_class() == "TButton" and \
                                    b.cget("text") == knopf:
                                b.invoke()
                                return
                    k.destroy()
                    return
            self.wurzel.after(50, tun)
        self.wurzel.after(50, tun)

    def test_dialog_liefert_die_werte(self):
        self._dialog_bedienen("OK")
        w = self.app._masse_fragen("Rechteck", [("b", "Breite", 80.0),
                                                ("h", "Höhe", 50.0)])
        self.assertEqual(w, {"b": 80.0, "h": 50.0})

    def test_dialog_abbrechen_gibt_nichts(self):
        self._dialog_bedienen("Abbrechen")
        self.assertIsNone(self.app._masse_fragen(
            "Rechteck", [("b", "Breite", 80.0)]))


class VerzerrtSchneiden(Grundlage):
    """Ohne den Haken 'Seitenverhaeltnis halten' muss sich auch ein Schnitt
    in die Breite ziehen lassen. V.fit hat frueher immer gleichmaessig
    skaliert, deshalb hat der Rahmen jede Eingabe wieder eingefangen."""

    def setUp(self):
        super().setUp()
        self.app.form_rechteck(80.0, 50.0)       # 8:5
        self.app.v_bw.set(200.0); self.app.v_bh.set(120.0)
        self.app.v_xoff.set(10.0); self.app.v_yoff.set(10.0)
        self.app.v_snap.set(False)

    def schnittmass(self):
        self.app.generate()
        self.assertIsNotNone(self.app.lines)
        x0, x1, y0, y1 = J.brenn_extent(self.app.lines)
        return round(x1 - x0, 2), round(y1 - y0, 2)

    def test_mit_haken_bleibt_es_verhaeltnistreu(self):
        self.app.v_lock.set(True)
        self.app.v_h.set(20.0)
        self.assertEqual(self.schnittmass(), (32.0, 20.0))

    def test_ohne_haken_gilt_das_eingetippte(self):
        self.app.v_lock.set(False)
        self.app.v_w.set(80.0); self.app.v_h.set(20.0)
        self.assertEqual(self.schnittmass(), (80.0, 20.0))

    def test_ohne_haken_auch_in_die_hoehe(self):
        self.app.v_lock.set(False)
        self.app.v_h.set(90.0)
        self.assertEqual(self.schnittmass(), (80.0, 90.0))

    def test_rahmen_zeigt_was_geschnitten_wird(self):
        self.app.v_lock.set(False)
        self.app.v_w.set(80.0); self.app.v_h.set(20.0)
        x, y, b, h = self.app._box()
        self.assertEqual((round(b, 2), round(h, 2)), self.schnittmass())

    def test_ziehen_ohne_haken_laesst_die_hoehe_stehen(self):
        import types
        self.app.v_lock.set(False)
        x, y, b, h = self.app._box()
        p = self.app._mm(x + b, y)
        q = self.app._mm(x + b + 40.0, y)
        self.app._press(types.SimpleNamespace(x=int(round(p[0])), y=int(round(p[1]))))
        self.assertEqual(self.app.drag[0], "size")
        self.app._drag_move(types.SimpleNamespace(x=int(round(q[0])),
                                                  y=int(round(q[1]))))
        self.app.drag = None
        self.assertAlmostEqual(self.app.v_w.get(), 120.0, delta=1.5)
        self.assertAlmostEqual(self.app.v_h.get(), 50.0, delta=0.01)

    def test_ziehen_mit_haken_haelt_das_verhaeltnis(self):
        import types
        self.app.v_lock.set(True)
        x, y, b, h = self.app._box()
        p = self.app._mm(x + b, y)
        q = self.app._mm(x + b + 40.0, y)
        self.app._press(types.SimpleNamespace(x=int(round(p[0])), y=int(round(p[1]))))
        self.app._drag_move(types.SimpleNamespace(x=int(round(q[0])),
                                                  y=int(round(q[1]))))
        self.app.drag = None
        self.assertAlmostEqual(self.app.v_w.get() / self.app.v_h.get(),
                               80.0 / 50.0, places=2)


class Haengerschutz(Grundlage):
    """Was nach dem Einfrieren gebaut wurde: Spuren sichern, Dialog
    entschaerfen, Protokoll begrenzen."""

    def test_protokoll_waechst_nicht_unbegrenzt(self):
        self.app.LOGZEILEN = 50
        for i in range(400):
            self.app._log("Zeile %d" % i)
        zeilen = int(self.app.log.index("end-1c").split(".")[0])
        self.assertLessEqual(zeilen, 51)
        self.assertIn("Zeile 399", self.app.log.get("1.0", "end"))

    def test_herzschlag_wird_gesetzt(self):
        import time
        self.app._herzschlag = 0
        self.app._poll()
        self.root_after_abbrechen()
        self.assertAlmostEqual(self.app._herzschlag, time.time(), delta=2.0)

    def root_after_abbrechen(self):
        try:
            self.wurzel.after_cancel(self.app._poll_id)
        except Exception:
            pass

    def test_falsche_eingabe_oeffnet_keinen_zweiten_dialog(self):
        """Ein zweiter Dialog waehrend des Tk-Griffs legt das Programm
        lahm - die Meldung muss im Dialog selbst stehen."""
        gezeigt = []
        self.L.messagebox.showerror = lambda t, m: gezeigt.append(m)

        def tun():
            for k in self.wurzel.winfo_children():
                if k.winfo_class() == "Toplevel":
                    for kind in k.winfo_children():
                        if kind.winfo_class() == "TEntry":
                            kind.delete(0, "end")
                            kind.insert(0, "acht")      # keine Zahl
                    for kind in k.winfo_children():
                        for b in kind.winfo_children():
                            if b.winfo_class() == "TButton" and b.cget("text") == "OK":
                                b.invoke()
                    self.assertTrue(k.winfo_exists(), "Dialog ist zu frueh zu")
                    hinweise = [kind.cget("text") for kind in k.winfo_children()
                                if kind.winfo_class() == "TLabel"]
                    self.assertTrue(any("ungültig" in h for h in hinweise),
                                    "kein Hinweis im Dialog: %r" % (hinweise,))
                    k.destroy()
                    return
            self.wurzel.after(50, tun)
        self.wurzel.after(50, tun)
        self.assertIsNone(self.app._masse_fragen("Rechteck",
                                                 [("b", "Breite", 80.0)]))
        self.assertEqual(gezeigt, [])

    def test_griff_wird_wieder_abgegeben(self):
        self._dialog_schliessen()
        self.app._masse_fragen("Rechteck", [("b", "Breite", 80.0)])
        self.assertEqual(self.wurzel.grab_current(), None)

    def _dialog_schliessen(self):
        def tun():
            for k in self.wurzel.winfo_children():
                if k.winfo_class() == "Toplevel":
                    k.destroy()
                    return
            self.wurzel.after(50, tun)
        self.wurzel.after(50, tun)

    def test_spurendatei_wird_angelegt(self):
        import os
        import lw_presets as P
        pfad = self.L.haenger_spuren()
        self.assertIsNotNone(pfad)
        self.assertEqual(os.path.dirname(pfad), P.DIR)


@ohne_bildschirm
class Jobleiste(Grundlage):
    """Die Leiste mit Start, Pause und STOPP.

    Der STOPP-Knopf lag jahrelang in derselben Gitterzelle wie der Schalter
    'Rahmen sichtbar' - der Schalter deckte ihn zu, und ein Klick auf STOPP
    schaltete nur den Rahmen um.
    """

    def kaesten(self):
        """Alle Knoepfe und Schalter der Leiste, in Fensterkoordinaten -
        die Leiste ist jetzt in Gruppen unterteilt, also eine Ebene tief."""
        self.wurzel.deiconify()
        self.wurzel.update()
        leiste = self.app.btn_gen.master.master
        kaesten = []
        for gruppe in leiste.winfo_children():
            kinder = (gruppe.winfo_children()
                      if gruppe.winfo_class() == "TFrame" else [gruppe])
            for c in kinder:
                kaesten.append((c.winfo_rootx(), c.winfo_rooty(),
                                c.winfo_width(), c.winfo_height()))
        return kaesten

    def test_nichts_deckt_sich(self):
        k = self.kaesten()
        for i in range(len(k)):
            for j in range(i + 1, len(k)):
                a, b = k[i], k[j]
                quer = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
                hoch = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
                self.assertLessEqual(min(quer, hoch), 0,
                                     "Jobleiste: %r deckt %r zu" % (a, b))

    def test_stopp_ist_anklickbar(self):
        """Direkt an die Stelle des Knopfes fassen - wer dort liegt, kriegt
        den Klick."""
        self.wurzel.deiconify()
        self.wurzel.update()
        knopf = self.app.jobknoepfe["stopp"]
        x = knopf.winfo_rootx() + knopf.winfo_width() // 2
        y = knopf.winfo_rooty() + knopf.winfo_height() // 2
        self.assertIs(self.wurzel.winfo_containing(x, y), knopf)


@ohne_bildschirm
class PauseAmZeilenende(Grundlage):
    def setUp(self):
        super().setUp()
        self.app.grbl.job_running = True

    def test_schalter_an_meldet_die_pause_an(self):
        self.app.v_pause_ende.set(True)
        self.app.pause()
        self.assertIn("Pause am Zeilenende", self.app.grbl.protokoll)
        self.assertNotIn("Pause", self.app.grbl.protokoll)

    def test_schalter_aus_haelt_sofort(self):
        self.app.v_pause_ende.set(False)
        self.app.pause()
        self.assertIn("Pause", self.app.grbl.protokoll)

    def test_ohne_job_sofort(self):
        """Vor dem Start gibt es keine Zeile, an deren Ende man halten
        koennte - dann ist Pause eben Feed Hold."""
        self.app.grbl.job_running = False
        self.app.v_pause_ende.set(True)
        self.app.pause()
        self.assertIn("Pause", self.app.grbl.protokoll)

    def test_marken_gehen_an_den_job(self):
        self.app.grbl.job_running = False
        self.motiv()
        self.app.v_w.set(40.0)
        self.app.generate()
        self.app.start()
        self.wurzel.update()
        self.assertTrue(getattr(self.app.grbl, "marken", None),
                        "ohne Marken kann der Job nicht am Zeilenende halten")


@ohne_bildschirm
class FehlerNachDemJob(Grundlage):
    """Die Fehlerzahl stand bisher nur in der Fortschrittsanzeige und war
    mit dem Jobende weg. Hinterher ist sie die einzige Spur, die eine
    ausgelassene Zeile im Werkstueck erklaeren koennte."""

    def protokoll(self):
        return self.app.log.get("1.0", "end")

    def test_fehler_landen_im_protokoll(self):
        self.app.grbl.job_errors = 3
        self.app.grbl.job_done = 1200
        self.app._event("jobend", ("Gravur", "fertig"))
        self.assertRegex(self.protokoll(), r"3 Fehler in 1200")

    def test_auch_ohne_fehler(self):
        self.app.grbl.job_errors = 0
        self.app.grbl.job_done = 90
        self.app._event("jobend", ("Gravur", "fertig"))
        self.assertRegex(self.protokoll(), r"0 Fehler in 90")

    def test_fehler_stehen_in_der_anzeige(self):
        self.app.grbl.job_errors = 2
        self.app._event("jobend", ("Gravur", "abgebrochen"))
        self.assertIn("2", self.app.lbl_prog.cget("text"))


@ohne_bildschirm
class NurDasBild(Grundlage):
    """Eine Schnittvorlage mit eingebettetem Bild: gerastert wird das Bild,
    nicht die Schnittlinien drumherum."""

    def vorlage(self, bild=True, linien=True):
        import base64, io, os, tempfile
        roh = io.BytesIO()
        Image.new("L", (40, 20), 255).save(roh, format="PNG")
        b64 = base64.b64encode(roh.getvalue()).decode()
        teile = ['<svg xmlns="http://www.w3.org/2000/svg" '
                 'xmlns:xlink="http://www.w3.org/1999/xlink" width="40mm" '
                 'height="20mm" viewBox="0 0 40 20">']
        if bild:
            teile.append('<image xlink:href="data:image/png;base64,%s" '
                         'x="0" y="0" width="40" height="20"/>' % b64)
        if linien:
            teile.append('<path d="M0 10 H40" stroke="#000000" '
                         'stroke-width="0.6" fill="none"/>')
        teile.append("</svg>")
        p = os.path.join(tempfile.mkdtemp(), "vorlage.svg")
        with open(p, "w") as f:
            f.write("".join(teile))
        self.L.filedialog.askopenfilenames = lambda **k: (p,)
        self.app.open_image()
        return p

    def test_schalter_erscheint(self):
        self.vorlage()
        self.assertTrue(self.app.bildlinien)
        self.assertTrue(self.app.chk_nurbild.winfo_manager())

    def test_schalter_bleibt_weg_ohne_bild(self):
        self.vorlage(bild=False)
        self.assertFalse(self.app.bildlinien)
        self.assertFalse(self.app.chk_nurbild.winfo_manager())

    def test_schalter_bleibt_weg_ohne_linien(self):
        self.vorlage(linien=False)
        self.assertFalse(self.app.bildlinien)

    def test_linien_kommen_nicht_in_den_gcode(self):
        """Das eingebettete Bild ist weiss, die Linie schwarz: taucht im
        Raster ueberhaupt Leistung auf, ist die Linie mitgraviert."""
        self.vorlage()
        # Eine Schnittvorlage wird von sich aus graviert UND geschnitten -
        # hier geht es nur um das Raster, der Schnitt haette eigene Werte.
        self.app.v_job.set("gravur")
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        self.app.v_mode.set("schwelle")
        self.app.generate()
        self.assertEqual(max(s_werte(self.app.lines), default=0), 0)

    def test_ausgeschaltet_brennt_die_linie_mit(self):
        self.vorlage()
        self.app.v_job.set("gravur")       # nur das Raster zaehlt hier
        self.app.v_nurbild.set(False)
        self.app._nurbild_anwenden()
        self.app.v_w.set(40.0)
        self.app._keep_ratio("w")
        self.app.v_mode.set("schwelle")
        self.app.generate()
        self.assertGreater(max(s_werte(self.app.lines), default=0), 0)

    def test_umschalten_rendert_neu(self):
        self.vorlage()
        vorher = self.app.src
        self.app.v_nurbild.set(False)
        self.app._nurbild_anwenden()
        self.assertIsNot(self.app.src, vorher)
        self.assertFalse(self.app.src_nurbild)


@ohne_bildschirm
class MitDerMausDrehen(Grundlage):
    """Drehen ging nur ueber ein Zahlenfeld und vier Knoepfe. Ein Motiv
    gerade auf ein schiefes Brettchen zu legen hiess: Winkel schaetzen,
    eintippen, hinsehen, wieder eintippen."""

    class Zeiger:
        def __init__(self, x, y):
            self.x, self.y = int(x), int(y)

    def aufbauen(self, b=120.0, h=None):
        self.motiv()
        self.app.v_lock.set(True)
        self.app.v_w.set(b)
        self.app._keep_ratio("w")
        self.app.v_xoff.set(40.0)
        self.app.v_yoff.set(40.0)
        self.app._element_sichern()
        self.app._draw()
        return self.app._box()

    def griff(self):
        return self.Zeiger(*self.app._drehgriff)

    def mitte_zeiger(self, dx, dy):
        x, y, b, h = self.app._box()
        mx, my = self.app._mm(x + b / 2, y + h / 2)
        return self.Zeiger(mx + dx, my + dy)

    def drehen(self, dx, dy):
        self.app._press(self.griff())
        self.app._drag_move(self.mitte_zeiger(dx, dy))
        self.app._drag_ende(self.mitte_zeiger(dx, dy))

    def test_griff_liegt_ueber_der_oberkante(self):
        x, y, b, h = self.aufbauen()
        mx, oy = self.app._mm(x + b / 2, y + h)
        gx, gy = self.app._drehgriff
        self.assertAlmostEqual(gx, mx, delta=1)
        self.assertAlmostEqual(gy, oy - self.app.DREHGRIFF, delta=1)
        art, _, _ = self.app._griff_unter(self.griff())
        self.assertEqual(art, "dreh")

    def test_ziehen_dreht(self):
        self.aufbauen()
        self.app.v_snap.set(True)
        self.drehen(120, 0)                      # Griff nach rechts
        self.assertEqual(self.app.v_rot.get() % 360, 90.0)

    def test_das_motiv_folgt_der_hand(self):
        """Der Griff steht oben. Wer ihn nach rechts zieht, dreht im
        Uhrzeigersinn - und das Motiv muss mitkommen, nicht dagegen.

        Hier stand ein Minus im Winkel, mit der Begruendung, der Schirm
        zaehle Y andersherum als die Maschine. Das hebt sich aber zweimal
        auf: der Griff drehte das Motiv gegen die Hand, und derselbe
        Winkel ins Zahlenfeld getippt drehte es herum.
        """
        self.aufbauen()
        self.app.v_snap.set(True)
        self.drehen(120, 0)                      # von oben nach rechts
        grad = self.app.v_rot.get() % 360
        self.assertEqual(grad, 90.0)
        # Und dieser Winkel dreht wirklich rechtsherum: ein Punkt rechts
        # der Mitte liegt danach darunter (Y zaehlt im Werkstueck hoch).
        x, y = L_vector.rotate(
            [{"pts": [(10.0, 0.0)], "closed": False}], grad)[0]["pts"][0]
        self.assertAlmostEqual(x, 0.0, delta=0.01)
        self.assertLess(y, -9.0)

    def test_linksherum_ziehen_dreht_linksherum(self):
        self.aufbauen()
        self.app.v_snap.set(True)
        self.drehen(-120, 0)                     # von oben nach links
        self.assertEqual(self.app.v_rot.get() % 360, 270.0)

    def test_motiv_behaelt_seine_groesse_und_mitte(self):
        """Der umschliessende Kasten dreht sich mit, das Motiv nicht."""
        x, y, b, h = self.aufbauen()
        mitte = (x + b / 2, y + h / 2)
        self.app.v_snap.set(True)
        self.drehen(120, 0)
        x2, y2, b2, h2 = self.app._box()
        self.assertAlmostEqual(b2, h, delta=1.0)     # vertauscht
        self.assertAlmostEqual(h2, b, delta=1.0)
        self.assertAlmostEqual(x2 + b2 / 2, mitte[0], delta=1.0)
        self.assertAlmostEqual(y2 + h2 / 2, mitte[1], delta=1.0)

    def test_einrasten_faengt_bei_fuenfzehn_grad(self):
        self.aufbauen()
        self.app.v_snap.set(True)
        self.drehen(100, 20)                     # irgendwo dazwischen
        self.assertAlmostEqual(self.app.v_rot.get() % 15, 0.0, places=6)

    def test_ohne_einrasten_jeder_winkel(self):
        self.aufbauen()
        self.app.v_snap.set(False)
        self.drehen(100, 23)
        self.assertNotAlmostEqual(self.app.v_rot.get() % 15, 0.0, places=3)

    def test_knopf_dreht_wie_die_maus(self):
        """Zwei Wege zum selben Winkel muessen dasselbe Ergebnis haben -
        sonst wird das Motiv je nach Weg groesser oder kleiner."""
        self.aufbauen()
        self.app._dreh_setzen(90)
        ueber_knopf = (round(self.app.v_w.get(), 1),
                       round(self.app.v_h.get(), 1))
        self.app._dreh_setzen(0)
        self.app.v_snap.set(True)
        self.drehen(120, 0)                      # dasselbe mit der Maus
        self.assertEqual(self.app.v_rot.get() % 360, 90.0)
        self.app._dreh_setzen(90)
        self.assertEqual((round(self.app.v_w.get(), 1),
                          round(self.app.v_h.get(), 1)), ueber_knopf)

    def test_zahlenfeld_dreht_wie_die_knoepfe(self):
        """Der Weg ueber das Feld haengt an keinem Vormerken mehr: der
        Massstab kommt aus dem Winkel, zu dem die Masse gehoeren."""
        self.aufbauen()
        self.app._dreh_setzen(45)
        ueber_knopf = (round(self.app.v_w.get(), 1),
                       round(self.app.v_h.get(), 1))
        self.app._dreh_setzen(0)
        self.app.v_rot.set(45)            # wie eingetippt, ohne Vorlauf
        self.app._rotated()
        self.assertEqual((round(self.app.v_w.get(), 1),
                          round(self.app.v_h.get(), 1)), ueber_knopf)

    def test_elementwechsel_verwirrt_die_drehung_nicht(self):
        """Jedes Element bringt seinen eigenen Winkel mit - die Masse des
        einen duerfen nicht am Winkel des anderen gemessen werden."""
        self.aufbauen()
        self.app._dreh_setzen(90)
        gedreht = (round(self.app.v_w.get(), 1), round(self.app.v_h.get(), 1))
        self.app._element_sichern()
        self.app._element_laden(0, zeichnen=False)
        self.app._dreh_setzen(90)         # schon dort: darf nichts aendern
        self.assertEqual((round(self.app.v_w.get(), 1),
                          round(self.app.v_h.get(), 1)), gedreht)

    def test_drehen_laesst_das_motiv_in_ruhe(self):
        """Vierteldreh und zurueck: dieselbe Groesse wie vorher. Frueher
        wuchs das Motiv dabei, weil die Breite blieb und die Hoehe dem
        neuen Seitenverhaeltnis folgte."""
        self.aufbauen()
        vorher = (round(self.app.v_w.get(), 1), round(self.app.v_h.get(), 1))
        self.app._dreh_setzen(90)
        self.app._dreh_setzen(0)
        self.assertEqual((round(self.app.v_w.get(), 1),
                          round(self.app.v_h.get(), 1)), vorher)

    def test_rundes_motiv_waechst_beim_drehen_nicht(self):
        """Der Kasten war das gedrehte RECHTECK um das Bild, nicht der
        gedrehte Inhalt: bei einem runden 60-mm-Anhaenger stand bei
        301 Grad ein Kasten von 80 x 78 mm um eine Scheibe von 56 x 55."""
        from PIL import ImageDraw
        im = Image.new("L", (800, 800), 255)
        ImageDraw.Draw(im).ellipse((40, 40, 760, 760), fill=0)
        p = os.path.join(tempfile.mkdtemp(), "rund.png")
        im.save(p)
        self.app.lade_motiv(p, fragen=False)
        self.app.v_lock.set(True)
        self.app.v_w.set(60.0)
        self.app._keep_ratio("w")
        for grad in (0, 30, 45, 301, 0):
            self.app._dreh_setzen(grad)
            b, h = self.app._box()[2:]
            self.assertAlmostEqual(b, 60.0, delta=1.0, msg="%d Grad" % grad)
            self.assertAlmostEqual(h, 60.0, delta=1.0, msg="%d Grad" % grad)

    def test_vorschau_fuellt_ihren_rahmen_auch_gedreht(self):
        """rotate(expand=True) legt weisse Zwickel um das Motiv. In einen
        Rahmen gezogen, der genau um den Inhalt liegt, schwaemme es darin
        mit Luft ringsum - kleiner, als es wirklich ist."""
        from PIL import ImageDraw
        im = Image.new("L", (400, 400), 255)
        ImageDraw.Draw(im).rectangle((60, 120, 340, 280), fill=0)
        p = os.path.join(tempfile.mkdtemp(), "balken.png")
        im.save(p)
        self.app.lade_motiv(p, fragen=False)
        self.app.v_lock.set(True)
        self.app.v_w.set(80.0)
        self.app._keep_ratio("w")
        def inhalt(bild):
            return bild.point(lambda v: 255 if v < 245 else 0).getbbox()

        gedreht = self.app.src.rotate(-45, expand=True, fillcolor=255)
        self.assertNotEqual(inhalt(gedreht),
                            (0, 0, gedreht.width, gedreht.height),
                            "ohne Zwickel waere nichts zu beschneiden")
        eng = self.app._auf_inhalt(gedreht)
        self.assertEqual(inhalt(eng), (0, 0, eng.width, eng.height))
        # und das Bild, das gezeichnet wird, geht durch dieselbe Stelle
        self.app._dreh_setzen(45)
        b, h = self.app._box()[2:]
        self.app._live_cache = None
        self.assertIsNotNone(self.app._live_image(b, h))

    def test_zeichnung_misst_ihre_kontur_auch_beim_gravieren(self):
        """Eine Zeichnung bringt ihre Kontur mit - die ist genauer als
        jedes gerenderte Bild, und sie waechst beim Drehen nur so viel,
        wie die Kontur wirklich waechst."""
        p = os.path.join(tempfile.mkdtemp(), "kreis.svg")
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="60mm" '
                    'height="60mm" viewBox="0 0 60 60">'
                    '<circle cx="30" cy="30" r="29" stroke="#ff0000" '
                    'stroke-width="0.2" fill="none"/></svg>')
        self.app.lade_motiv(p, fragen=False)
        self.app.v_job.set("gravur")
        self.app.v_lock.set(True)
        self.app._dreh_setzen(0)
        vorher = self.app._box()[2:]
        self.app._dreh_setzen(301)
        self.assertAlmostEqual(self.app._box()[2], vorher[0], delta=1.0)
        self.assertAlmostEqual(self.app._box()[3], vorher[1], delta=1.0)

    def test_zeigerform_sagt_was_ein_klick_taete(self):
        x, y, b, h = self.aufbauen()
        px, py = self.app._mm(x, y + h)
        qx, qy = self.app._mm(x + b, y)
        for zeiger, soll in ((self.griff(), "exchange"),
                             (self.Zeiger(px, py), "top_left_corner"),
                             (self.Zeiger(qx, qy), "bottom_right_corner"),
                             (self.Zeiger((px + qx) / 2, (py + qy) / 2), "fleur"),
                             (self.Zeiger(px - 80, py - 80), "")):
            self.app._zeiger(zeiger)
            self.assertEqual(self.app._zeigerform, soll)

    def test_waehrend_des_ziehens_bleibt_die_form(self):
        """Sonst flackert der Zeiger, sobald der Griff unter der Maus
        wegwandert - und er wandert beim Drehen staendig."""
        x, y, b, h = self.aufbauen()
        self.app._zeiger(self.griff())
        self.app._press(self.griff())
        self.app._zeiger(self.Zeiger(5, 5))
        self.assertEqual(self.app._zeigerform, "exchange")


@ohne_bildschirm
class WasNichtGehtSiehtManAuch(Grundlage):
    """Start, Pause, Weiter, STOPP, Rahmen und Kontur sahen immer gleich
    aus und antworteten mit einer Meldung. Abgeblendet sagen sie dasselbe,
    ohne dass man sie druecken muss."""

    def zustand(self, name):
        return str(self.app.jobknoepfe[name].cget("state"))

    def test_ohne_verbindung_geht_nur_erzeugen(self):
        self.motiv()
        self.app.grbl.connected = False
        self.app._status_zeigen()
        self.assertEqual(str(self.app.btn_gen.cget("state")), "normal")
        for k in ("start", "stopp", "rahmen", "kontur", "pause", "weiter"):
            self.assertEqual(self.zustand(k), "disabled", k)

    def test_ohne_gcode_kein_start(self):
        self.motiv()
        self.app.lines = None
        self.app._status_zeigen()
        self.assertEqual(self.zustand("start"), "disabled")
        self.assertEqual(self.zustand("stopp"), "normal")   # verbunden

    def test_mit_gcode_und_verbindung_geht_start(self):
        self.motiv()
        self.app.v_mode.set("schwelle")
        self.app.generate()
        self.assertEqual(self.zustand("start"), "normal")

    def test_waehrend_des_jobs_kein_start_und_kein_erzeugen(self):
        self.motiv()
        self.app.v_mode.set("schwelle")
        self.app.generate()
        self.app.grbl.job_running = True
        self.app._status_zeigen()
        self.assertEqual(self.zustand("start"), "disabled")
        self.assertEqual(str(self.app.btn_gen.cget("state")), "disabled")
        self.assertEqual(self.zustand("pause"), "normal")
        self.assertEqual(self.zustand("weiter"), "disabled")

    def test_pause_und_weiter_schliessen_sich_aus(self):
        self.motiv()
        self.app.grbl.job_running = True
        self.app.grbl.pausiert = True
        self.app._status_zeigen()
        self.assertEqual(self.zustand("pause"), "disabled")
        self.assertEqual(self.zustand("weiter"), "normal")

    def test_stopp_geht_immer_wenn_verbunden(self):
        """Der eine Knopf, der nie abgeblendet sein darf, solange die
        Maschine hoeren kann."""
        self.app.grbl.job_running = True
        self.app._status_zeigen()
        self.assertEqual(self.zustand("stopp"), "normal")


@ohne_bildschirm
class EineZeileSagtWoranManIst(Grundlage):
    """Maschine, Verbindung, Zustand, Nullpunkt und Z-Referenz standen an
    vier Stellen, zwei davon im Reiter 'Maschine' - den man beim
    Platzieren gar nicht offen hat."""

    def zeile(self):
        return self.app.lbl_status.cget("text")

    def test_nennt_die_maschine(self):
        self.app._status_zeigen()
        self.assertIn(self.app._maschine_name(), self.zeile())

    def test_sagt_ob_verbunden(self):
        self.app.grbl.connected = False
        self.app._status_zeigen()
        self.assertIn("nicht verbunden", self.zeile())
        self.app.grbl.connected = True
        self.app._status_zeigen()
        self.assertNotIn("nicht verbunden", self.zeile())

    def test_sagt_ob_der_nullpunkt_steht(self):
        self.app.zero_ok = False
        self.app._status_zeigen()
        self.assertIn("kein Nullpunkt", self.zeile())
        self.app.zero_ok = True
        self.app._status_zeigen()
        self.assertIn("Nullpunkt steht", self.zeile())

    def test_position_steht_rechts(self):
        self.app._event("status", {"wpos": (12.0, 34.0, 5.0), "state": "Idle",
                                   "fs": (0, 0), "mpos": (12.0, 34.0, 5.0),
                                   "wco": (0, 0, 0)})
        # Deutsche Oberflaeche: Komma, nicht Punkt.
        self.assertIn("12,00", self.app.lbl_marke.cget("text"))
        self.assertIn("Idle", self.zeile())


@ohne_bildschirm
class MaterialtestZumSchieben(Grundlage):
    """Ein Test gehoert auf das Reststueck, das man in der Hand hat.

    Frueher fuhr der Knopf sofort los, ab dem Nullpunkt, mit festen
    6-mm-Feldern. Jetzt kommt der Test als Element auf die Flaeche und
    laesst sich schieben und ziehen wie ein Motiv - die Werte je Feld
    bleiben dabei dieselben.
    """

    def anlegen(self, s="200,400,600", f="600,1000", b=80.0, h=40.0):
        self.app.v_mt_s.set(s)
        self.app.v_mt_f.set(f)
        self.app.v_mt_b.set(b)
        self.app.v_mt_h.set(h)
        self.app.materialtest_anlegen()
        self.app._element_laden(len(self.app.elemente) - 1)

    def erste_fahrt(self):
        self.app._erzeuge_eines()
        return [z for z in self.app.lines if z.startswith("G0")][0]

    def test_er_wird_ein_element(self):
        self.anlegen()
        e = self.app.elemente[-1]
        self.assertIn("Materialtest", e["anzeige"])
        self.assertEqual((e["v_w"], e["v_h"]), (80.0, 40.0))
        self.assertIsNotNone(e["src"], "ohne Bild laesst er sich nicht zeichnen")
        self.assertTrue(e["v_eigen"], "er bringt eigene Werte mit")

    def test_schieben_verschiebt_den_gcode(self):
        self.anlegen()
        self.app.v_xoff.set(10.0)
        self.app.v_yoff.set(10.0)
        a = self.erste_fahrt()
        self.app.v_xoff.set(110.0)
        self.app.v_yoff.set(60.0)
        b = self.erste_fahrt()
        ax = float(re.search(r"X(-?[\d.]+)", a).group(1))
        bx = float(re.search(r"X(-?[\d.]+)", b).group(1))
        ay = float(re.search(r"Y(-?[\d.]+)", a).group(1))
        by = float(re.search(r"Y(-?[\d.]+)", b).group(1))
        self.assertAlmostEqual(bx - ax, 100.0, delta=0.01)
        self.assertAlmostEqual(by - ay, 50.0, delta=0.01)

    def test_jedes_feld_bekommt_seine_werte(self):
        self.anlegen(s="200,400", f="600,1000")
        self.app._erzeuge_eines()
        text = "\n".join(self.app.lines)
        for sv in (200, 400):
            for fv in (600, 1000):
                self.assertIn("S%d F%d" % (sv, fv), text)

    def test_ziehen_aendert_die_feldgroesse_nicht_die_werte(self):
        self.anlegen()
        self.app._erzeuge_eines()
        gross = self.app.info["feld_b"]
        self.app.v_w.set(40.0)
        self.app._erzeuge_eines()
        self.assertLess(self.app.info["feld_b"], gross)
        self.assertIn("S600 F1000", "\n".join(self.app.lines))

    def test_zu_klein_sagt_er_statt_unsinn_zu_bauen(self):
        self.anlegen(b=6.0, h=4.0)
        self.gezeigt.clear()
        self.app._erzeuge_eines()
        self.assertTrue(self.gezeigt)

    def test_unsinnige_eingaben_werden_abgefangen(self):
        for sv, fv in (("", "600"), ("200", ""), ("200,x", "600")):
            self.gezeigt.clear()
            vorher = len(self.app.elemente)
            self.app.v_mt_s.set(sv)
            self.app.v_mt_f.set(fv)
            self.app.materialtest_anlegen()
            self.assertEqual(len(self.app.elemente), vorher)
            self.assertTrue(self.gezeigt, "%r/%r kam stillschweigend durch"
                            % (sv, fv))


@ohne_bildschirm
class KameraUnterDerZeichenflaeche(Grundlage):
    """Das entzerrte Kamerabild als Untergrund.

    Die Eichung gehoert zur Maschine - die Kamera ist festgeschraubt.
    Beim Umschalten auf die andere Maschine ist sie eine andere oder
    keine, und dann darf kein altes Bild stehenbleiben.
    """

    EICHUNG = {
        "version": 1, "geraet": "/dev/video2", "bild": [2592, 1944],
        "k1": -0.2339, "k2": 0.0520,
        "mitte": [1194.6, 918.5], "mass": 1000.0,
        "homographie": [[3.72406, -0.03045, 1182.56],
                        [-0.01254, -3.73558, 1094.28],
                        [3.2004e-07, -1.93535e-05, 1.0]],
        "massstab": 1.00753, "drehung": -0.1488,
        "versatz": [191.2, 192.2], "hoehe": 0.0, "dicke": 0.0,
        "aufnahmen": 11, "fehler_mm": 0.43,
    }

    def eichen(self):
        self.app.cfg["kamera"] = dict(self.EICHUNG)
        self.app._kam_zeigen()

    def bild(self):
        return Image.new("RGB", (2592, 1944), (90, 90, 90))

    def test_ohne_eichung_sagt_er_das(self):
        self.app.cfg.pop("kamera", None)
        self.app._kam_zeigen()
        self.assertIn("keine Eichung", self.app.lbl_kam.cget("text"))

    def test_mit_eichung_steht_da_was_sie_taugt(self):
        self.eichen()
        text = self.app.lbl_kam.cget("text")
        self.assertIn("0.43", text.replace(",", "."))
        self.assertIn("11", text)

    def test_bild_wird_entzerrt_und_gezeigt(self):
        self.eichen()
        self.app._kamera_uebernehmen(self.bild())
        self.assertIsNotNone(self.app.kam_bett)
        # 2 Bildpunkte je Millimeter ueber den ganzen Verfahrweg
        b, h = self.app.kam_bett.size
        self.assertAlmostEqual(b / 2.0, float(self.app.cfg["x_max"]), delta=1)
        self.assertAlmostEqual(h / 2.0, float(self.app.cfg["y_max"]), delta=1)
        self.assertTrue(self.app.v_kam_an.get())
        self.assertTrue(self.app.cv.find_withtag("kamera"))

    def test_falsche_aufloesung_wird_nicht_stillschweigend_gerechnet(self):
        """Die Eichung steht in Bildpunkten.

        bild_holen() hat eine Vorgabe von 1280x720, geeicht wurde bei
        2592x1944. Einmal ohne Groesse geholt, und jeder Koeffizient zeigt
        daneben - in X um 0,49, in Y um 0,37. Zwei Achsen, zwei Faktoren:
        dem Ergebnis sieht man es nicht an, es sieht nur falsch aus.
        """
        self.eichen()
        self.gezeigt.clear()
        self.app._kamera_uebernehmen(Image.new("RGB", (1280, 720)))
        self.assertIsNone(self.app.kam_bett)
        self.assertTrue(any(art == "w" for art, _ in self.gezeigt))
        self.assertIn("1280", "".join(m for _, m in self.gezeigt))

    def test_geholt_wird_in_der_geeichten_groesse(self):
        gerufen = {}
        self.eichen()
        self.app.v_kamera.set("/dev/video9")
        echt = self.L.KAM.bild_holen
        self.L.KAM.bild_holen = lambda g, b=0, h=0, **k: (
            gerufen.update(g=g, b=b, h=h) or Image.new("RGB", (b, h)))
        try:
            self.app.kamera_holen()
            for _ in range(200):
                self.wurzel.update()
                if gerufen:
                    break
        finally:
            self.L.KAM.bild_holen = echt
        self.assertEqual((gerufen.get("b"), gerufen.get("h")), (2592, 1944))

    def test_die_materialstaerke_ist_keine_kamerahoehe(self):
        """3 mm ins Hoehenfeld: der Faktor H/(H-d) ginge gegen unendlich."""
        self.eichen()
        self.app.v_kam_hoehe.set(3.0)
        self.gezeigt.clear()
        self.app._kam_hoehe_sichern()
        self.assertTrue(any(art == "w" for art, _ in self.gezeigt))
        self.assertEqual(self.app._kam_eichung().get("hoehe"), 0.0)
        self.assertEqual(self.app.v_kam_hoehe.get(), 0.0)

    def test_eine_echte_hoehe_wird_uebernommen(self):
        self.eichen()
        self.app.v_kam_hoehe.set(300.0)
        self.gezeigt.clear()
        self.app._kam_hoehe_sichern()
        self.assertEqual(self.gezeigt, [])
        self.assertEqual(self.app._kam_eichung().get("hoehe"), 300.0)

    def test_die_unterlage_zaehlt_zur_materialstaerke(self):
        """Wabenplatte plus Brett: beides hebt die Oberseite."""
        self.eichen()
        self.app.v_dicke.set(12.0)
        self.app.v_kam_unterlage.set(22.0)
        self.assertAlmostEqual(self.app._kam_dicke(), 34.0, places=3)

    def test_was_beim_eichen_schon_darunter_lag_zaehlt_nicht_doppelt(self):
        """Die Eichebene ist nicht immer das nackte Bett.

        Lag die Karte beim Eichen auf einem 3-mm-Brett, dann ist die
        Eichebene 3 mm hoch - ein 12-mm-Brett liegt nur 9 mm darueber.
        """
        self.eichen()
        self.app._kam_eichung()["dicke"] = 3.0
        self.app.v_dicke.set(12.0)
        self.app.v_kam_unterlage.set(0.0)
        self.assertAlmostEqual(self.app._kam_dicke(), 9.0, places=3)

    def test_die_unterlage_wird_gespeichert(self):
        self.eichen()
        self.app.v_kam_unterlage.set(22.0)
        self.app._kam_unterlage_sichern()
        self.assertAlmostEqual(float(self.app.cfg["kam_unterlage"]), 22.0)

    def test_eine_andere_staerke_rechnet_den_untergrund_neu(self):
        """Ohne neues Bild - das rohe liegt noch da.

        Wer nach dem Bildholen die Materialstaerke aendert, sah bisher
        weiter das Bild der alten Staerke; versetzt um H/(H-d), und
        nichts sagte es ihm.
        """
        self.eichen()
        self.app._kam_eichung()["hoehe"] = 260.0
        self.app.v_dicke.set(0.0)
        self.app.v_kam_unterlage.set(0.0)
        self.app._kamera_uebernehmen(self.bild())
        self.assertAlmostEqual(self.app.kam_dicke, 0.0, places=3)
        self.app.v_dicke.set(20.0)
        self.assertTrue(self.app._kamera_neu_rechnen())
        self.assertAlmostEqual(self.app.kam_dicke, 20.0, places=3)
        # Gleiche Staerke, gleiches Bild: nicht noch einmal rechnen
        self.assertFalse(self.app._kamera_neu_rechnen())

    def test_ohne_bild_gibt_es_nichts_umzurechnen(self):
        self.eichen()
        self.app.kam_roh = self.app.kam_bett = None
        self.app.v_dicke.set(18.0)
        self.assertFalse(self.app._kamera_neu_rechnen(zwingen=True))

    def hoehenfeld(self):
        for rahmen in self.app.tab_kam.winfo_children():
            for w in rahmen.winfo_children():
                if w.winfo_class() == "TSpinbox":
                    return w
        return None

    def test_getippte_hoehe_wird_auch_gespeichert(self):
        """Eine Spinbox mit command= meldet nur die Pfeilchen.

        Getippt und weitergeklickt hiess: nichts gespeichert, und auf dem
        Schirm aendert sich nichts - man sucht den Fehler dann im Bild,
        nicht im Feld. Return und der Fokuswechsel muessen es auch tun.

        Geprueft wird, dass die Bindungen da sind und der Handler den
        getippten Wert uebernimmt; ob Tk ein kuenstliches Tastenereignis
        zustellt, ist Sache von Tk und im kopflosen X-Server ohnehin
        nicht verlaesslich.
        """
        self.eichen()
        sp = self.hoehenfeld()
        self.assertIsNotNone(sp, "Hoehenfeld nicht gefunden")
        gebunden = set(sp.bind())
        self.assertIn("<Key-Return>", gebunden)
        self.assertIn("<FocusOut>", gebunden)
        self.app._kam_eichung()["hoehe"] = 0.0
        self.app.v_kam_hoehe.set(260.0)
        self.app._kam_hoehe_sichern()
        self.assertEqual(self.app._kam_eichung().get("hoehe"), 260.0)

    def test_ohne_eichung_bleibt_es_bei_einem_bild(self):
        self.app.cfg.pop("kamera", None)
        self.app._kamera_uebernehmen(self.bild())
        self.assertIsNone(self.app.kam_bett)
        self.assertFalse(self.app.cv.find_withtag("kamera"))

    def test_abgeschaltet_liegt_nichts_darunter(self):
        self.eichen()
        self.app._kamera_uebernehmen(self.bild())
        self.app.v_kam_an.set(False)
        self.app._kamera_zeigen()
        self.assertFalse(self.app.cv.find_withtag("kamera"))

    def test_die_eichung_gehoert_zur_maschine(self):
        """Umschalten heisst: andere Kamera oder keine."""
        self.app.maschinen = {"aktiv": "", "maschinen": {}}
        self.app.cfg.pop("maschine", None)
        self.app.cfg["kamera"] = dict(self.EICHUNG)
        self.app._maschine_einrichten()
        klein = self.app._maschine_name()
        self.L.messagebox.askyesno = lambda t, m: False
        self.app.v_mneu.set("Creality Falcon2 Pro 22 W")
        self.app.maschine_anlegen()
        self.app.cfg.pop("kamera", None)
        self.app._maschine_sichern()
        self.assertTrue(self.app.maschine_wechseln(klein, fragen=False))
        self.assertEqual(self.app._kam_eichung().get("massstab"),
                         self.EICHUNG["massstab"])


@ohne_bildschirm
class GeladenerGcodeIstAuchGcode(Grundlage):
    """Eine geladene .nc hat kein Motiv - sie ist eines.

    load_gcode() leert die Motivliste und setzt self.lines. Alles, was
    danach noch geht, muss sich an self.lines halten und nicht an der
    leeren Liste.
    """

    def laden(self):
        self.app.elemente = []
        self.app.aktiv = None
        self.app.src = None
        self.app.lines = ["G21", "G90", "M4 S40",
                          "G1 X10 Y0 F1000", "G1 X10 Y10", "M5", "G0 X0 Y0"]
        self.app._knoepfe_zeigen()

    def test_der_rahmen_laesst_sich_fahren(self):
        self.laden()
        self.assertEqual(str(self.app.jobknoepfe["rahmen"]["state"]), "normal")

    def test_start_sowieso(self):
        self.laden()
        self.assertEqual(str(self.app.jobknoepfe["start"]["state"]), "normal")

    def test_ohne_gcode_bleibt_er_abgeblendet(self):
        self.app.elemente = []
        self.app.lines = None
        self.app._knoepfe_zeigen()
        self.assertEqual(str(self.app.jobknoepfe["rahmen"]["state"]), "disabled")

    def test_die_rahmenfahrt_nimmt_die_ausmasse_des_gcodes(self):
        self.laden()
        self.app.v_frame_laser.set(False)
        self.app.frame()
        xs = [float(z.split("X")[1].split()[0])
              for z in self.app.grbl.gesendet if "X" in z]
        self.assertAlmostEqual(max(xs), 10.0, delta=0.5)


@ohne_bildschirm
class ZeigenHeisstNichtBrennen(Grundlage):
    """Sichtkreuz, Rahmen und Kontur sollen zeigen, wo etwas hinkommt.

    Die Grenze dafuer stand als feste 0,20 im Quelltext - S/F, nicht
    Energie. Das war die Grenze genau einer Maschine. An 22 W ist dasselbe
    S/F das Vierfache: der Rahmen, mit dem man ausrichtet, wird zur Spur
    auf dem Brett.
    """

    def watt(self, w):
        self.app.cfg["watt"] = w
        J.setze_maschine(self.app.cfg)

    def test_an_der_kleinen_bleibt_alles_wie_es_war(self):
        """Die alten festen Zahlen sind kein Zufall, sondern gemessen."""
        self.assertEqual(J.zeig_s(5.5, j=J.ZEIG_J_MAX), 120)
        self.assertAlmostEqual(J.zeig_s(5.5, j=J.ZEIG_J_MAX) / J.POINTER_FEED,
                               0.20, places=2)
        self.assertEqual(J.zeig_s(5.5), 47)

    def test_viermal_so_stark_heisst_ein_viertel(self):
        self.assertEqual(J.zeig_s(22.0), 12)
        self.assertEqual(J.zeig_s(22.0, j=J.ZEIG_J_MAX), 30)

    def test_dieselbe_zahl_wird_an_der_grossen_gedeckelt(self):
        self.watt(5.5)
        self.app.v_zeig_s.set(50)
        self.assertEqual(self.app._zeig_s(), 50)
        self.watt(22.0)
        self.assertEqual(self.app._zeig_s(), 30)

    def test_gedeckelt_wird_nicht_heimlich(self):
        self.watt(22.0)
        self.app.v_zeig_s.set(50)
        self.app._zeig_s()
        self.assertIn("S30", self.app.log.get("1.0", "end"))

    def test_erlaubtes_bleibt_unangetastet(self):
        self.watt(22.0)
        self.app.v_zeig_s.set(J.zeig_s(22.0))
        self.assertEqual(self.app._zeig_s(), J.zeig_s(22.0))

    def test_die_rahmenfahrt_deckelt_auch(self):
        """Die hatte als einzige gar keine eigene Grenze - und faehrt am
        weitesten."""
        import re
        self.watt(22.0)
        self.app.v_zeig_s.set(50)
        self.app.v_frame_laser.set(True)
        self.app.lines = ["G0 X0 Y0", "G1 X10 Y10 S100"]
        self.app.frame()
        werte = {int(m.group(1)) for z in self.app.grbl.gesendet
                 for m in [re.search(r"S(\d+)", z)] if m}
        self.assertTrue(werte)
        self.assertLessEqual(max(werte), 30)

    def test_der_maschinenwechsel_zieht_die_vorgabe_mit(self):
        # Mit leerer Ablage anfangen: die Wegwerfdatei ueberlebt von einem
        # Test zum naechsten, und dann gibt es den Namen schon.
        self.app.maschinen = {"aktiv": "", "maschinen": {}}
        self.app.cfg.pop("maschine", None)
        self.app.cfg["watt"] = 5.5
        self.app._maschine_einrichten()
        klein = self.app._maschine_name()
        self.app.v_zeig_s.set(50)
        self.L.messagebox.askyesno = lambda t, m: False   # nicht umrechnen
        self.app.v_mneu.set("Creality Falcon2 Pro 22 W")
        self.app.maschine_anlegen()
        self.assertEqual(self.app.v_zeig_s.get(), J.zeig_s(22.0))
        self.app.maschine_wechseln(klein, fragen=False)
        self.assertEqual(self.app.v_zeig_s.get(), J.zeig_s(5.5))


@ohne_bildschirm
class MaschinenProfile(Grundlage):
    """Zwei Maschinen abwechselnd: Verfahrweg, Leistung, Beschleunigung,
    Fokuskorrektur, Laufzeitmessungen und Presets gehoeren zu je einer.
    Dieselbe Presetliste an 5,5 W und an 22 W ist eine Falle, die beim
    ersten Brett zuschlaegt."""

    VORLAGE = "Creality Falcon2 Pro 22 W"

    def setUp(self):
        super().setUp()
        # Mit leerer Ablage anfangen: die Wegwerfdatei ueberlebt sonst von
        # einem Test zum naechsten.
        self.app.maschinen = {"aktiv": "", "maschinen": {}}
        self.app.cfg.pop("maschine", None)
        self.app.cfg.update(watt=5.5, x_max=200.0, y_max=200.0, accel=30.0)
        self.app._maschine_einrichten()
        self.app._maschine_zeigen()

    def anlegen(self, name, umrechnen=True):
        self.L.messagebox.askyesno = lambda t, m: umrechnen
        self.app.v_mneu.set(name)
        self.app.maschine_anlegen()

    def test_erster_start_macht_eine_maschine(self):
        self.assertEqual(len(self.app._maschinen_namen()), 1)
        self.assertEqual(self.app.cfg["maschine"], self.app._maschine_name())
        self.assertIn(self.app._maschine_name(), self.wurzel.title())

    def test_vorlage_bringt_ihre_werte_mit(self):
        self.anlegen(self.VORLAGE)
        self.assertEqual(self.app._maschine_name(), self.VORLAGE)
        self.assertEqual((self.app.cfg["x_max"], self.app.cfg["y_max"]),
                         (400.0, 415.0))
        self.assertEqual(self.app.cfg["watt"], 22.0)
        self.assertEqual(J.ACCEL, 500.0)         # das Zeitmodell zieht mit
        self.assertEqual(J.EILGANG, 8000.0)
        self.assertIn(self.VORLAGE, self.wurzel.title())

    def test_presets_werden_auf_die_leistung_umgerechnet(self):
        vorher = dict(self.app.presets["Erle 3 mm (Schnitt)"])
        self.anlegen(self.VORLAGE, umrechnen=True)
        jetzt = self.app.presets["Erle 3 mm (Schnitt)"]
        self.assertAlmostEqual(jetzt["schnitt_s"],
                               vorher["schnitt_s"] * 5.5 / 22.0, delta=1)
        self.assertIn("UNGETESTET", jetzt["notiz"])
        self.assertEqual(jetzt["schnitt_f"], vorher["schnitt_f"])

    def test_wer_nein_sagt_behaelt_die_werte(self):
        vorher = dict(self.app.presets["Erle 3 mm (Schnitt)"])
        self.anlegen(self.VORLAGE, umrechnen=False)
        self.assertEqual(self.app.presets["Erle 3 mm (Schnitt)"]["schnitt_s"],
                         vorher["schnitt_s"])

    def test_zurueckwechseln_holt_alles_zurueck(self):
        klein = self.app._maschine_name()
        self.app.cfg["zeitmessungen"] = [1.21, 1.19, 1.2]
        self.app.v_korr.set(4.0)
        self.app._fokus_sichern()
        self.anlegen(self.VORLAGE)
        self.assertEqual(self.app.cfg.get("zeitmessungen"), [])
        self.assertEqual(self.app.cfg.get("korrektur"), 0.0)
        self.assertTrue(self.app.maschine_wechseln(klein, fragen=False))
        self.assertEqual(self.app.cfg["zeitmessungen"], [1.21, 1.19, 1.2])
        self.assertEqual(self.app.cfg["korrektur"], 4.0)
        self.assertEqual(self.app.cfg["x_max"], 200.0)
        self.assertEqual(J.ACCEL, 30.0)

    def test_angeschlossene_maschine_wird_erkannt(self):
        """Umgesteckt und vergessen umzuschalten - $130/$131 verraten es."""
        klein = self.app._maschine_name()
        self.anlegen(self.VORLAGE)
        self.app.maschine_wechseln(klein, fragen=False)
        self.app.grbl = Attrappe(x130=400.0, y131=415.0, app=self.app)
        self.app._einstellungen_pruefen(self.app.grbl.settings)
        self.assertEqual(self.app._maschine_name(), self.VORLAGE)

    def test_ohne_passendes_profil_wird_nicht_gewechselt(self):
        klein = self.app._maschine_name()
        self.app.grbl = Attrappe(x130=400.0, y131=415.0, app=self.app)
        self.app._einstellungen_pruefen(self.app.grbl.settings)
        self.assertEqual(self.app._maschine_name(), klein)

    def test_waehrend_eines_jobs_kein_wechsel(self):
        klein = self.app._maschine_name()
        self.anlegen(self.VORLAGE)
        self.app.grbl.job_running = True
        self.assertFalse(self.app.maschine_wechseln(klein))
        self.assertEqual(self.app._maschine_name(), self.VORLAGE)

    def test_name_doppelt_geht_nicht(self):
        self.anlegen(self.VORLAGE)
        self.anlegen(self.VORLAGE)
        self.assertEqual(self.app._maschinen_namen().count(self.VORLAGE), 1)

    def test_label_sagt_die_kennwerte(self):
        self.anlegen(self.VORLAGE)
        text = self.app.lbl_maschine.cget("text")
        self.assertIn("400", text)
        self.assertIn("22", text)
        self.assertIn("500", text)


@ohne_bildschirm
class WerteKommenVonDerMaschine(Grundlage):
    """Beschleunigung, Eilgang und Kreuzungstoleranz gehoeren der Maschine.
    Als Vorgabe in den Funktionen rechnete jede Schaetzung mit den Werten
    des Geraets, auf dem Laserwerk entstanden ist: 30 mm/s^2, 3000 mm/min.
    Eine Creality Falcon2 Pro sagt 500 und 8000 - das ist keine Feinheit,
    das ist ein anderes Ergebnis."""

    def maschine(self, **werte):
        self.app.grbl = Attrappe(app=self.app)
        self.app.grbl.settings.update(werte)
        self.app._einstellungen_pruefen(self.app.grbl.settings)

    def test_uebernimmt_was_die_maschine_sagt(self):
        self.maschine(**{"11": 0.02, "110": 25000.0, "111": 8000.0,
                         "120": 500.0, "121": 500.0})
        self.assertEqual(J.ACCEL, 500.0)
        self.assertEqual(J.EILGANG, 8000.0)      # die langsamere Achse bremst
        self.assertEqual(J.KREUZUNG, 0.02)
        self.assertEqual(self.app.cfg["accel"], 500.0)

    def test_die_langsamere_achse_zaehlt(self):
        self.maschine(**{"120": 500.0, "121": 180.0})
        self.assertEqual(J.ACCEL, 180.0)

    def test_schaetzung_folgt_der_maschine(self):
        lahm = J.setze_maschine({"accel": 30.0}) and J.fahrzeit(100.0, 1000 / 60)
        flink = J.setze_maschine({"accel": 500.0}) and J.fahrzeit(100.0, 1000 / 60)
        self.assertLess(flink, lahm)

    def test_leistung_steht_in_der_konfiguration(self):
        self.app.v_watt.set(22.0)
        self.app.set_watt()
        self.assertEqual(J.WATT, 22.0)
        self.assertEqual(self.app.cfg["watt"], 22.0)
        # Dieselbe Energie braucht an 22 W ein Viertel von S/F
        self.assertAlmostEqual(J.energie(1000, 330), 4.0, delta=0.05)
        self.assertIn("J/mm", self.app.lbl_watt.cget("text"))

    def test_unsinnige_leistung_wird_abgelehnt(self):
        self.app.v_watt.set(0.0)
        self.app.set_watt()
        self.assertNotEqual(self.app.cfg.get("watt"), 0.0)


@ohne_bildschirm
class SchnittwerteGeltenJeElement(Grundlage):
    """Leistung, Vorschub und Durchgaenge fuers Schneiden gehoeren zum
    Element, und 0 heisst dort "nimm die Gravurwerte". In einem Projekt mit
    fuenf Baggern stand das an einem Element - das wurde geschnitten, die
    anderen vier mit S830/F1000 nur angeritzt. In der Liste steht die
    Betriebsart, die Werte dahinter nicht.

    Von Hand bekommt man solche Unterschiede nur noch mit dem Haken
    "Eigene Werte" hin - ohne ihn gelten die Werte fuer alle Elemente
    (siehe WerteGeltenFuersGanzeWerkstueck). Aus alten Projekten kommen
    sie aber weiter herein, und dann muss die Nachfrage stehen."""

    def setUp(self):
        super().setUp()
        self.gefragt = []
        self.app.cfg["x_max"], self.app.cfg["y_max"] = 200.0, 200.0
        self.ordner = tempfile.mkdtemp()

    def antwort(self, wert):
        def frage(titel, text):
            self.gefragt.append(text)
            return wert
        self.L.messagebox.askyesnocancel = frage

    def svg(self, cs=0, cf=0, passes=1):
        p = os.path.join(self.ordner, "s%d.svg" % len(self.app.elemente))
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="30mm" '
                    'height="20mm" viewBox="0 0 30 20">'
                    '<path d="M1 1 H29 V19 H1 Z" stroke="#ff0000" '
                    'stroke-width="0.1" fill="none"/></svg>')
        self.app.lade_motiv(p, fragen=False)
        self.app.v_job.set("schnitt")
        # Haken zuerst: ohne ihn wuerden die Werte auf die anderen
        # Elemente durchschlagen, und dann gaebe es nichts zu pruefen.
        self.app.v_eigen.set(True)
        self.app.v_cs.set(cs)
        self.app.v_cf.set(cf)
        self.app.v_passes.set(passes)
        self.app._element_sichern()
        return self.app.elemente[-1]

    def test_gleiche_werte_fragen_nicht(self):
        self.antwort(None)
        self.svg(cs=500, cf=600, passes=3)
        self.svg(cs=500, cf=600, passes=3)
        self.app.generate()
        self.assertEqual(self.gefragt, [])
        self.assertTrue(self.app.lines)

    def test_gravurwerte_neben_schnittwerten_fragen_nach(self):
        self.antwort(False)
        self.svg()                                  # 0/0 -> S830/F1000 x1
        self.svg(cs=1000, cf=330, passes=6)
        self.app.generate()
        self.assertEqual(len(self.gefragt), 1)
        self.assertIn("0.27 J/mm", self.gefragt[0])
        self.assertIn("6.00 J/mm", self.gefragt[0])

    def test_nein_erzeugt_es_wie_es_dasteht(self):
        self.antwort(False)
        eins = self.svg()
        self.svg(cs=1000, cf=330, passes=6)
        self.app.generate()
        self.assertTrue(self.app.lines)
        self.assertEqual(eins["v_cs"], 0)
        self.assertEqual(eins["v_passes"], 1)

    def test_ja_uebernimmt_die_staerksten_werte(self):
        self.antwort(True)
        eins = self.svg()
        self.svg(cs=1000, cf=330, passes=6)
        self.app.generate()
        self.assertEqual((eins["v_cs"], eins["v_cf"], eins["v_passes"]),
                         (1000, 330, 6))
        self.assertTrue(self.app.lines)

    def test_abbrechen_erzeugt_nichts(self):
        self.antwort(None)
        self.svg()
        self.svg(cs=1000, cf=330, passes=6)
        self.app.generate()
        self.assertIsNone(self.app.lines)

    def test_gravieren_zaehlt_nicht_mit(self):
        """Ein graviertes Element hat keine Schnittwerte - das darf die
        Frage nicht ausloesen."""
        self.antwort(None)
        self.svg(cs=1000, cf=330, passes=6)
        self.app.v_job.set("gravur")
        self.app._element_sichern()
        self.svg(cs=1000, cf=330, passes=6)
        self.app.generate()
        self.assertEqual(self.gefragt, [])

    def test_energie_steht_in_der_beschriftung(self):
        self.antwort(None)
        self.svg(cs=1000, cf=330, passes=6)
        self.app.generate()
        self.assertIn("J/mm", self.app.lbl_info.cget("text"))


@ohne_bildschirm
class WerteGeltenFuersGanzeWerkstueck(Grundlage):
    """Leistung, Vorschub, Zeilenabstand und Durchgaenge standen je Element.
    Bei fuenf Baggern auf einem Brett hiess das: fuenfmal dieselben Zahlen
    eintippen, und wer eines vergass, ritzte es nur an. Ein Werkstueck ist
    aber aus einem Stueck Holz - die Werte gehoeren zum Material."""

    def setUp(self):
        super().setUp()
        self.app.cfg["x_max"], self.app.cfg["y_max"] = 300.0, 300.0
        self.ordner = tempfile.mkdtemp()

    def svg(self, name=None):
        p = os.path.join(self.ordner,
                         name or "s%d.svg" % len(self.app.elemente))
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="30mm" '
                    'height="20mm" viewBox="0 0 30 20">'
                    '<path d="M1 1 H29 V19 H1 Z" stroke="#ff0000" '
                    'stroke-width="0.1" fill="none"/></svg>')
        self.assertTrue(self.app.lade_motiv(p, fragen=False))
        return self.app.elemente[-1]

    def werte(self, e):
        return (e.get("v_cs"), e.get("v_cf"), e.get("v_passes"),
                e.get("v_s"), e.get("v_f"))

    def test_eingestellt_an_einem_gilt_fuer_alle(self):
        eins, zwei = self.svg(), self.svg()
        self.app.v_cs.set(950)
        self.app.v_cf.set(300)
        self.app.v_passes.set(4)
        self.assertEqual((eins["v_cs"], eins["v_cf"], eins["v_passes"]),
                         (950, 300, 4))

    def test_auch_rueckwaerts_vom_ersten_element(self):
        """Nicht nur vom gerade geladenen aus: an jedem Element."""
        self.svg()
        zwei = self.svg()
        self.app._element_sichern()
        self.app._element_laden(0, zeichnen=False)
        self.app.v_cf.set(420)
        self.assertEqual(zwei["v_cf"], 420)

    def test_materialwerte_gehoeren_dazu(self):
        """Dasselbe Material heisst dieselbe Leistung und denselben
        Vorschub - auch die aus dem Reiter Material."""
        eins = self.svg()
        self.svg()
        self.app.v_s.set(700)
        self.app.v_f.set(1400)
        self.app.v_line.set(0.08)
        self.assertEqual((eins["v_s"], eins["v_f"], round(eins["v_line"], 3)),
                         (700, 1400, 0.08))

    def test_haken_nimmt_ein_element_heraus(self):
        eins = self.svg()
        self.svg()
        self.app.v_eigen.set(True)
        self.app._eigen_geaendert()
        self.app.v_cs.set(1000)
        self.app.v_passes.set(6)
        self.assertNotEqual(eins["v_cs"], 1000)
        self.assertEqual(eins["v_passes"], 1)
        self.assertTrue(self.app.elemente[1]["v_eigen"])

    def test_haken_weg_holt_die_gemeinsamen_werte(self):
        """Sonst hiesse 'gemeinsam' nur, dass die naechste Aenderung alle
        anderen mit den abweichenden Werten ueberschreibt."""
        eins = self.svg()
        self.app.v_cs.set(880)
        self.app.v_cf.set(360)
        self.svg()
        self.app.v_eigen.set(True)
        self.app._eigen_geaendert()
        self.app.v_cs.set(200)
        self.app.v_eigen.set(False)
        self.app._eigen_geaendert()
        self.assertEqual((self.app.v_cs.get(), self.app.v_cf.get()),
                         (880, 360))
        self.assertEqual(eins["v_cs"], 880)

    def test_neues_element_kommt_in_die_gruppe(self):
        """Ein neu geladenes Motiv erbte Haken und Werte des Elements, das
        gerade davor gewaehlt war - also davon, was man zuletzt anklickte."""
        eins = self.svg()
        self.app.v_cs.set(900)
        self.app.v_cf.set(350)
        self.svg()
        self.app.v_eigen.set(True)
        self.app._eigen_geaendert()
        self.app.v_cs.set(120)
        drei = self.svg()
        self.assertFalse(drei.get("v_eigen"))
        self.assertEqual((drei["v_cs"], drei["v_cf"]), (900, 350))
        self.assertEqual(eins["v_cs"], 900)

    def test_liste_zeigt_die_abweichung(self):
        self.svg()
        self.svg()
        self.app.v_eigen.set(True)
        self.app._eigen_geaendert()
        zeilen = self.app.lb_el.get(0, "end")
        self.assertNotIn("eigene Werte", zeilen[0])
        self.assertIn("eigene Werte", zeilen[1])

    def test_material_sagt_fuer_wen_es_gilt(self):
        self.svg()
        self.svg()
        self.assertIn("2", self.app.lbl_gemeinsam.cget("text"))
        self.app.v_eigen.set(True)
        self.app._eigen_geaendert()
        self.assertIn("Eigene Werte", self.app.lbl_gemeinsam.cget("text"))

    def test_betriebsart_fuer_alle_nimmt_die_werte_mit(self):
        """Wer die Frage nach der Betriebsart mit ja beantwortet, meint
        denselben Auftrag - nicht dieselbe Art mit anderen Werten."""
        eins = self.svg()
        self.app.v_eigen.set(True)
        self.app.v_job.set("gravur")
        self.app.v_cs.set(0)
        self.app.v_passes.set(1)
        self.app._element_sichern()
        self.svg()
        self.app.v_eigen.set(False)
        self.app.v_cs.set(980)
        self.app.v_cf.set(320)
        self.app.v_passes.set(5)
        self.app.v_job.set("schnitt")
        self.app._job_changed()          # fragt - askyesno sagt ja
        self.assertEqual(eins["v_job"], "schnitt")
        self.assertEqual((eins["v_cs"], eins["v_cf"], eins["v_passes"]),
                         (980, 320, 5))
        self.assertFalse(eins["v_eigen"])

    def test_altes_projekt_behaelt_seine_abweichungen(self):
        """Projekte ohne den Haken haben je Element eigene Zahlen. Sie
        stillschweigend als gemeinsam zu fuehren hiesse, dass die erste
        Aenderung irgendwo alle anderen ueberschreibt."""
        eins, zwei = self.svg(), self.svg()
        eins.update(v_cs=0, v_passes=1, v_eigen=False)
        zwei.update(v_cs=1000, v_passes=6, v_eigen=False)
        self.app._koppelung_pruefen()
        self.assertFalse(eins["v_eigen"])
        self.assertTrue(zwei["v_eigen"])

    def test_gleiche_werte_bleiben_gemeinsam(self):
        eins, zwei = self.svg(), self.svg()
        self.app._koppelung_pruefen()
        self.assertFalse(eins.get("v_eigen"))
        self.assertFalse(zwei.get("v_eigen"))

    def test_halb_getippte_zahl_wirft_nichts_weg(self):
        """Ein leeres Feld beim Tippen darf die anderen Elemente nicht auf
        null stellen - und erst recht nicht abstuerzen."""
        eins = self.svg()
        self.app.v_cf.set(900)
        self.svg()
        self.app.v_cf._root.globalsetvar(str(self.app.v_cf), "")
        self.assertEqual(eins["v_cf"], 900)


class NeueMotiveLiegenNebeneinander(Grundlage):
    """Jedes neu geladene Element wurde auf das Hoechstmass eingepasst und
    bekam denselben Versatz: fuenf Dateien hintereinander lagen deckungs-
    gleich uebereinander. Wer es nicht merkte, schnitt fuenfmal dieselbe
    Stelle - und sah nur ein Motiv."""

    def setUp(self):
        super().setUp()
        self.app.cfg["x_max"], self.app.cfg["y_max"] = 200.0, 200.0
        self.ordner = tempfile.mkdtemp()

    def svg(self, b, h):
        p = os.path.join(self.ordner, "m%d.svg" % len(self.app.elemente))
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" '
                    'height="%gmm" viewBox="0 0 %g %g">'
                    '<path d="M0 0 H%g V%g H0 Z" stroke="#ff0000" '
                    'stroke-width="0.1" fill="none"/></svg>'
                    % (b, h, b, h, b, h))
        self.app.lade_motiv(p, fragen=False)
        return self.app.elemente[-1]

    def test_zeichnung_kommt_im_originalmass(self):
        """Ein Schnitt, auf den Verfahrweg aufgeblasen, ist nie gemeint."""
        e = self.svg(40.0, 30.0)
        self.assertAlmostEqual(e["v_w"], 40.0, delta=0.3)
        self.assertAlmostEqual(e["v_h"], 30.0, delta=0.3)

    def test_zweites_motiv_liegt_rechts_daneben(self):
        eins = self.svg(40.0, 30.0)
        x1, y1 = eins["v_xoff"], eins["v_yoff"]
        zwei = self.svg(40.0, 30.0)
        self.assertGreaterEqual(zwei["v_xoff"], x1 + 40.0)
        self.assertEqual(zwei["v_yoff"], y1)
        self.assertAlmostEqual(zwei["v_w"], 40.0, delta=0.3)

    def test_volle_reihe_faengt_eine_neue_an(self):
        kaesten = [self.svg(40.0, 30.0) for _ in range(5)]
        letzte = kaesten[-1]
        self.assertLess(letzte["v_xoff"], kaesten[-2]["v_xoff"])
        self.assertGreaterEqual(letzte["v_yoff"], 30.0)
        self.assertAlmostEqual(letzte["v_w"], 40.0, delta=0.3)

    def test_keine_zwei_motive_uebereinander(self):
        kaesten = [self.svg(40.0, 30.0) for _ in range(6)]
        felder = [(k["v_xoff"], k["v_yoff"], k["v_w"], k["v_h"])
                  for k in kaesten]
        for i, (x, y, b, h) in enumerate(felder):
            for j, (x2, y2, b2, h2) in enumerate(felder):
                if i < j:
                    self.assertTrue(x + b <= x2 + 0.01 or x2 + b2 <= x + 0.01
                                    or y + h <= y2 + 0.01 or y2 + h2 <= y + 0.01,
                                    "%d und %d liegen uebereinander" % (i, j))

    def test_kein_platz_sagt_es_und_laesst_es_liegen(self):
        self.svg(190.0, 190.0)
        zwei = self.svg(190.0, 190.0)
        self.assertIn("Kein Platz", self.app.log.get("1.0", "end"))
        self.assertAlmostEqual(zwei["v_w"], 190.0, delta=0.3)

    def test_bild_behaelt_sein_eingepasstes_mass(self):
        """Ein Bild hat kein Mass in Millimetern - da bleibt das Einpassen."""
        self.svg(40.0, 30.0)
        im = Image.new("L", (200, 100), 0)
        p = os.path.join(self.ordner, "bild.png")
        im.save(p)
        self.app.lade_motiv(p, fragen=False)
        e = self.app.elemente[-1]
        # Eingepasst ist es breiter als der freie Platz rechts, also kommt
        # es in eine neue Reihe - aber nicht auf das erste Motiv.
        self.assertGreaterEqual(e["v_yoff"], 30.0)
        self.assertAlmostEqual(e["v_w"] / e["v_h"], 2.0, delta=0.1)


@ohne_bildschirm
class MehrereDateienAufEinmal(Grundlage):
    """Ein Werkstueck besteht selten aus einer Datei. Fuenf Bagger einzeln
    zu oeffnen heisst fuenfmal denselben Dialog - und wer sie aus dem
    Dateimanager herueberzieht, will gar keinen."""

    def setUp(self):
        super().setUp()
        self.app.cfg["x_max"], self.app.cfg["y_max"] = 300.0, 200.0
        self.ordner = tempfile.mkdtemp()

    def svg(self, name):
        p = os.path.join(self.ordner, name)
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="30mm" '
                    'height="20mm" viewBox="0 0 30 20">'
                    '<path d="M1 1 H29 V19 H1 Z" stroke="#ff0000" '
                    'stroke-width="0.1" fill="none"/></svg>')
        return p

    def test_drei_dateien_werden_drei_elemente(self):
        pfade = [self.svg("a.svg"), self.svg("b.svg"), self.svg("c.svg")]
        self.assertEqual(self.app.dateien_laden(pfade), 3)
        self.assertEqual(len(self.app.elemente), 3)
        self.assertEqual([e["anzeige"] for e in self.app.elemente],
                         ["a.svg", "b.svg", "c.svg"])

    def test_sie_liegen_nebeneinander(self):
        """Sonst laegen sie deckungsgleich uebereinander - genau das, was
        das Ablegen nebeneinander verhindern soll."""
        self.app.dateien_laden([self.svg("a.svg"), self.svg("b.svg")])
        a, b = (self.app._box_von(e) for e in self.app.elemente)
        self.assertTrue(self.app._platz_frei(b[0], b[1], b[2], b[3], [a]),
                        "zweites Motiv liegt auf dem ersten")

    def test_eine_kaputte_haelt_die_anderen_nicht_auf(self):
        kaputt = os.path.join(self.ordner, "kaputt.svg")
        with open(kaputt, "w") as f:
            f.write("das ist keine SVG")
        pfade = [self.svg("a.svg"), kaputt, self.svg("c.svg")]
        self.assertEqual(self.app.dateien_laden(pfade), 2)
        self.assertEqual(len(self.app.elemente), 2)

    def test_eine_meldung_statt_dreier(self):
        """Drei Fehlerdialoge hintereinander wegzuklicken hilft niemandem."""
        kaputt = []
        for i in range(2):
            p = os.path.join(self.ordner, "k%d.svg" % i)
            with open(p, "w") as f:
                f.write("kein SVG")
            kaputt.append(p)
        self.app.dateien_laden(kaputt + [self.svg("a.svg")])
        fehler = [m for art, m in self.gezeigt if art == "!"]
        self.assertEqual(len(fehler), 1)
        self.assertIn("k0.svg", fehler[0])
        self.assertIn("k1.svg", fehler[0])

    def test_einzelne_datei_meldet_wie_bisher(self):
        """Wer eine Datei oeffnet und sie geht nicht, soll den Grund sehen -
        nicht eine Liste mit einem Eintrag."""
        p = os.path.join(self.ordner, "kaputt.dxf")
        with open(p, "w") as f:
            f.write("keine DXF")
        self.assertEqual(self.app.dateien_laden([p]), 0)
        fehler = [m for art, m in self.gezeigt if art == "!"]
        self.assertEqual(len(fehler), 1)
        self.assertNotIn("kaputt.dxf", fehler[0])


class DateienHereinziehen(Grundlage):
    """Drag & Drop braucht die Tk-Erweiterung tkdnd. Was Laserwerk selbst
    tut - die Liste lesen und die Dateien ablegen - laesst sich auch ohne
    sie pruefen."""

    def setUp(self):
        super().setUp()
        self.app.cfg["x_max"], self.app.cfg["y_max"] = 300.0, 200.0
        self.ordner = tempfile.mkdtemp()

    def svg(self, name="a.svg"):
        p = os.path.join(self.ordner, name)
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="30mm" '
                    'height="20mm" viewBox="0 0 30 20">'
                    '<path d="M1 1 H29 V19 H1 Z" stroke="#ff0000" '
                    'stroke-width="0.1" fill="none"/></svg>')
        return p

    def warten(self, sekunden=3.0):
        """Den Zeitgeber durchlassen, der nach dem Fallenlassen laedt."""
        ende = time.time() + sekunden
        while time.time() < ende and not self.app.elemente:
            self.wurzel.update()
            time.sleep(0.02)
        self.wurzel.update()

    def test_ohne_tkdnd_laeuft_es_trotzdem(self):
        """Ein Programm, das wegen Drag & Drop nicht startet, waere
        schlimmer als eines ohne Drag & Drop."""
        self.assertIn(self.app._dnd_einrichten(), (True, False))
        self.assertIn(self.app.dnd, (True, False))

    def test_pfade_mit_leerzeichen(self):
        """tkdnd schickt eine Tcl-Liste; was Leerzeichen hat, steht in
        geschweiften Klammern."""
        self.assertEqual(
            self.app._dnd_dateien("{/tmp/mit Luecke.svg} /tmp/ohne.svg"),
            ["/tmp/mit Luecke.svg", "/tmp/ohne.svg"])

    def test_pfade_als_url(self):
        self.assertEqual(
            self.app._dnd_dateien("file:///tmp/mit%20Luecke.svg"),
            ["/tmp/mit Luecke.svg"])

    def test_url_mit_rechnernamen(self):
        self.assertEqual(self.app._dnd_dateien("file://localhost/tmp/a.svg"),
                         ["/tmp/a.svg"])

    def test_fallengelassene_dateien_werden_geladen(self):
        self.assertEqual(self.app._dnd_fallen("{%s}" % self.svg()), "copy")
        self.warten()
        self.assertEqual(len(self.app.elemente), 1)

    def test_geladen_wird_erst_nach_der_antwort(self):
        """Solange der Griff laeuft, wartet das abgebende Programm auf die
        Antwort und haelt den Zeiger fest. Eine SVG zu lesen dauert, und
        die Frage nach den Farbebenen wartet auf einen Menschen."""
        self.app._dnd_fallen("{%s}" % self.svg())
        self.assertEqual(self.app.elemente, [], "mitten im Griff geladen")
        self.warten()
        self.assertEqual(len(self.app.elemente), 1)

    def test_jedes_fenster_nimmt_dateien_an(self):
        """tkdnd fragt genau das Widget unter dem Zeiger, ob es Dateien
        nimmt, und geht dafuer nicht die Elternkette hoch. Nur das aeussere
        Fenster anzumelden hiess ueberall 'refuse_drop' - frei liegt es ja
        nirgends, ueberall sitzt die Flaeche, ein Reiter oder ein Feld."""
        if not self.app._dnd_einrichten():
            self.skipTest("tkdnd ist nicht installiert")
        for w in (self.wurzel, self.app.cv, self.app.nb, self.app.lb_el,
                  self.app.btn_gen):
            self.assertTrue(w.bind("<<DropTargetTypes>>"),
                            "%s nimmt keine Dateien" % w)
            self.assertTrue(w.bind("<<Drop:DND_Files>>"),
                            "%s hat keinen Griff fuers Loslassen" % w)

    def test_tkdnd_nimmt_den_zug_ueber_der_flaeche_an(self):
        """Dieselbe Frage, aber von tkdnd selbst gestellt: genau das kam
        vorher mit 'refuse_drop' zurueck."""
        if not self.app._dnd_einrichten():
            self.skipTest("tkdnd ist nicht installiert")
        self.wurzel.deiconify()
        self.wurzel.geometry("1200x800")
        self.wurzel.update()
        x = self.app.cv.winfo_rootx() + 200
        y = self.app.cv.winfo_rooty() + 150
        self.wurzel.tk.call("tkdnd::xdnd::_HandleXdndEnter", ".", "0x1",
                            "text/uri-list")
        self.assertEqual(
            self.wurzel.tk.call("tkdnd::xdnd::_HandleXdndPosition",
                                str(self.app.cv), x, y, "0x1"), "copy")

    def test_mit_tkdnd_haengt_es_am_fenster(self):
        """Mit der Erweiterung laesst sich der ganze Weg gehen: anmelden,
        genau das Stueck Tcl ausfuehren, das tkdnd beim Fallenlassen
        ausfuehrt, und nachsehen, ob die Datei da ist. Ohne tkdnd gibt es
        hier nichts zu pruefen - das deckt test_ohne_tkdnd_laeuft_es_
        trotzdem ab."""
        if not self.app._dnd_einrichten():
            self.skipTest("tkdnd ist nicht installiert")
        skript = self.wurzel.bind("<<Drop:DND_Files>>")
        self.assertTrue(skript, "kein Stueck Tcl am Fenster")
        antwort = self.wurzel.tk.eval(
            skript.replace("%D", "[list {%s}]" % self.svg()))
        self.assertEqual(antwort, "copy")
        self.warten()
        self.assertEqual(len(self.app.elemente), 1)

    def test_nichts_dabei_wird_abgelehnt(self):
        self.assertEqual(self.app._dnd_fallen(""), "refuse_drop")

    def test_die_lage_kommt_aus_dem_ziehen(self):
        """In <<Drop>> setzt tkdnd die Bildschirmlage fest auf 0,0
        (tkdnd_unix.tcl, _HandleXdndDrop). Brauchbar ist sie nur waehrend
        des Ziehens - sonst laegen alle Dateien in der Ecke."""
        self.wurzel.deiconify()
        self.wurzel.geometry("1200x800")
        self.wurzel.update()
        px = self.app.cv.winfo_rootx() + 200
        py = self.app.cv.winfo_rooty() + 150
        self.assertEqual(self.app._dnd_lage(px, py), "copy")
        self.assertEqual(
            [round(v, 2) for v in self.app._dnd_punkt],
            [round(v, 2) for v in self.app._mm_zurueck(200, 150)])
        # Neben der Flaeche gibt es keine Stelle, nur "mach auf"
        self.app._dnd_lage(5, 5)
        self.assertIsNone(self.app._dnd_punkt)

    def test_es_liegt_wo_man_loslaesst(self):
        """Sonst landet es irgendwo, und man schiebt es doch wieder von
        Hand - dann braucht es das Ziehen gar nicht erst."""
        self.motiv()
        self.app.v_w.set(40.0)
        self.app.v_h.set(30.0)
        self.app._platz_daneben(wunsch=(150.0, 100.0))
        self.assertAlmostEqual(self.app.v_xoff.get() + 20.0, 150.0, delta=0.1)
        self.assertAlmostEqual(self.app.v_yoff.get() + 15.0, 100.0, delta=0.1)

    def test_am_rand_bleibt_es_auf_der_flaeche(self):
        self.motiv()
        self.app.v_w.set(40.0)
        self.app.v_h.set(30.0)
        self.app._platz_daneben(wunsch=(299.0, 199.0))
        self.assertLessEqual(self.app.v_xoff.get() + 40.0, 300.0)
        self.assertLessEqual(self.app.v_yoff.get() + 30.0, 200.0)

    def test_besetzte_stelle_weicht_aus(self):
        """Lieber daneben als zweimal dieselbe Stelle geschnitten."""
        self.motiv()
        self.app.v_w.set(40.0); self.app.v_h.set(30.0)
        self.app.v_xoff.set(100.0); self.app.v_yoff.set(100.0)
        self.app._element_sichern()
        self.app.elemente.append(dict(self.app.elemente[0], anzeige="zwei"))
        self.app.aktiv = 1
        self.app._platz_daneben(wunsch=(110.0, 110.0))
        self.app._element_sichern()      # wie lade_motiv es auch tut
        zwei = self.app._box_von(self.app.elemente[1])
        self.assertTrue(self.app._platz_frei(
            zwei[0], zwei[1], zwei[2], zwei[3],
            [self.app._box_von(self.app.elemente[0])]))


class WasManSiehtIstWasDaSteht(Grundlage):
    """Nach dem Laden hat zuletzt fit() gezeichnet - danach hat
    _platz_daneben Groesse und Lage nochmal angefasst. Eine Zeichnung kommt
    im Originalmass herein, war aber vorher auf das Hoechstmass eingepasst:
    auf dem Schirm stand der grosse Kasten, in den Feldern das kleine Mass.
    Anfassen ging nicht (der Griff sucht am richtigen Kasten), und erst ein
    Klick in Breite oder Hoehe rueckte es zurecht."""

    def setUp(self):
        super().setUp()
        self.app.cfg["x_max"], self.app.cfg["y_max"] = 295.0, 180.0
        self.ordner = tempfile.mkdtemp()

    def svg(self, b=60, h=40):
        p = os.path.join(self.ordner, "s.svg")
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" width="%dmm" '
                    'height="%dmm" viewBox="0 0 %d %d">'
                    '<path d="M1 1 H%d V%d H1 Z" stroke="#ff0000" '
                    'stroke-width="0.2" fill="none"/></svg>'
                    % (b, h, b, h, b - 1, h - 1))
        return p

    def rahmen(self):
        """Der gestrichelte Kasten um das Motiv, in Bildpunkten."""
        for i in self.app.cv.find_all():
            if self.app.cv.type(i) != "rectangle":
                continue
            if self.app.cv.itemcget(i, "outline") != self.L.S.ACCENT:
                continue
            c = self.app.cv.coords(i)
            if abs(c[2] - c[0]) > 12:          # nicht der Drehgriff
                return c
        return None

    def test_frisch_geladen_steht_der_rahmen_am_motiv(self):
        self.app.lade_motiv(self.svg(), fragen=False)
        x, y, b, h = self.app._box()
        self.assertAlmostEqual(b, 58.0, delta=0.5)      # Originalmass, 1:1
        ax, ay = self.app._mm(x, y + h)
        cx, cy = self.app._mm(x + b, y)
        gezeichnet = self.rahmen()
        self.assertIsNotNone(gezeichnet, "kein Rahmen gezeichnet")
        for soll, ist in zip((ax, ay, cx, cy), gezeichnet):
            self.assertAlmostEqual(ist, soll, delta=2.0,
                                   msg="Rahmen %s, Kasten %s"
                                   % (gezeichnet, (ax, ay, cx, cy)))

    def test_es_laesst_sich_gleich_anfassen(self):
        """Der Griff sucht am richtigen Kasten - solange der gezeichnete
        groesser war, klickte man daneben."""
        self.app.lade_motiv(self.svg(), fragen=False)
        gezeichnet = self.rahmen()
        mitte = type("E", (), {})()
        mitte.x = int((gezeichnet[0] + gezeichnet[2]) / 2)
        mitte.y = int((gezeichnet[1] + gezeichnet[3]) / 2)
        self.assertEqual(self.app._griff_unter(mitte)[0], "move")


class FehlerStehenImProtokoll(Grundlage):
    """tkinter schreibt einen Fehler in der Oberflaeche auf die
    Standardfehlerausgabe - die es nicht gibt, wenn das Programm aus dem
    Menue gestartet wurde. Das Fenster steht dann da, als waere nichts
    gewesen, und die Haelfte eines Vorgangs ist nicht passiert."""

    def ausloesen(self):
        import sys
        try:
            raise ValueError("Probe")
        except ValueError:
            self.app._fehler_melden(*sys.exc_info())

    def test_im_protokoll_steht_was_los_war(self):
        self.ausloesen()
        text = self.app.log.get("1.0", "end")
        self.assertIn("ValueError", text)
        self.assertIn("Probe", text)

    def test_die_ganze_spur_steht_in_der_datei(self):
        self.ausloesen()
        pfad = os.path.join(self.L.P.DIR, self.L.HAENGERDATEI)
        with open(pfad) as f:
            inhalt = f.read()
        self.assertIn("Fehler in der Oberflaeche", inhalt)
        self.assertIn("ausloesen", inhalt)

    def test_tkinter_ruft_wirklich_hier_an(self):
        """Der Haken muss am Fenster haengen, sonst nuetzt er nichts."""
        self.assertEqual(self.wurzel.report_callback_exception,
                         self.app._fehler_melden)


class DerWachhundBelltNurBeiEchtenHaengern(unittest.TestCase):
    """Zwei Eintraege in der Haengerdatei waren gar keine Haenger: einer
    entstand, waehrend ein Dateidialog auf einen Menschen wartete, der
    andere beim Start - da hatte die Oberflaeche noch keinen Puls, und der
    Wachhund rechnete gegen die Null: 'steht seit 1793962100 s'."""

    def setUp(self):
        import laserwerk
        self.L = laserwerk

    def test_ohne_puls_zaehlt_die_startzeit(self):
        self.assertAlmostEqual(self.L.haenger_dauer(0, 1000.0, 1003.0), 3.0)

    def test_mit_puls_zaehlt_der_puls(self):
        self.assertAlmostEqual(self.L.haenger_dauer(1002.0, 1000.0, 1025.0), 23.0)

    def test_ein_offener_dialog_ist_kein_haenger(self):
        self.assertEqual(self.L.haenger_dauer(1002.0, 1000.0, 1900.0, dialoge=1),
                         0.0)

    def test_eine_stehende_schleife_meldet_sich_weiter(self):
        """Die Meldung soll nicht verschwinden - sie heisst dann wirklich
        etwas: die Schleife, die alle hundert Millisekunden laufen soll,
        laeuft nicht mehr."""
        self.assertGreater(self.L.haenger_dauer(1002.0, 1000.0, 1100.0), 20.0)


class DialogeZaehlenSichSelbst(unittest.TestCase):
    """Damit der Wachhund weiss, wann die Oberflaeche nur wartet."""

    def test_waehrend_des_dialogs_hochgezaehlt(self):
        import lw_dialog
        echt_z, echt_zenity = lw_dialog.ZENITY, lw_dialog.subprocess.run
        gesehen = []
        lw_dialog.ZENITY = "/bin/true"
        lw_dialog.subprocess.run = lambda *a, **k: (
            gesehen.append(lw_dialog.LAEUFT)
            or type("R", (), {"returncode": 0, "stdout": ""})())
        try:
            lw_dialog._z(["--info"])
        finally:
            lw_dialog.ZENITY, lw_dialog.subprocess.run = echt_z, echt_zenity
        self.assertEqual(gesehen, [1])
        self.assertEqual(lw_dialog.LAEUFT, 0)


class SchnittvorlageInDeckung(Grundlage):
    """Bei einer Schnittvorlage liegen die Schnittlinien NEBEN dem Motiv.

    Das Bild wird beim Laden auf seinen Inhalt zugeschnitten, die Pfade
    nicht - wer danach beide Kaesten aufeinander einpasst, verliert genau
    die Luft dazwischen. Der Rahmen landete dann auf der Zeichnung statt
    darum herum.
    """

    LUFT = 10.0      # mm zwischen Zeichnung und Schnittlinie

    def vorlage(self, xoff=20.0, yoff=20.0, job="beides"):
        """Blatt 100 x 100: Zeichnung 20..80, Schnitt 10..90."""
        import base64, io, os, tempfile
        im = Image.new("L", (400, 400), 255)
        im.paste(0, (80, 80, 320, 320))          # 20..80 mm schwarz
        roh = io.BytesIO()
        im.save(roh, format="PNG")
        b64 = base64.b64encode(roh.getvalue()).decode()
        p = os.path.join(tempfile.mkdtemp(), "vorlage.svg")
        with open(p, "w") as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg" '
                    'xmlns:xlink="http://www.w3.org/1999/xlink" width="100mm" '
                    'height="100mm" viewBox="0 0 100 100">'
                    '<image xlink:href="data:image/png;base64,%s" x="0" y="0" '
                    'width="100" height="100"/>'
                    '<path d="M10 10 H90 V90 H10 Z" stroke="#ff0000" '
                    'stroke-width="0.1" fill="none"/></svg>' % b64)
        self.app.lade_motiv(p, fragen=False)
        if job:
            self.app.v_job.set(job)
        self.app.v_lock.set(True)
        self.app.v_w.set(60.0)
        self.app.v_h.set(60.0)
        self.app.v_xoff.set(xoff)
        self.app.v_yoff.set(yoff)
        self.app._element_sichern()
        return p

    def test_bild_merkt_sich_seinen_platz_im_blatt(self):
        self.vorlage()
        x0, y0, x1, y1 = self.app.bild_bb
        self.assertAlmostEqual(x0, 20.0, delta=0.5)
        self.assertAlmostEqual(x1, 80.0, delta=0.5)
        self.assertAlmostEqual(y0, -80.0, delta=0.5)
        self.assertAlmostEqual(y1, -20.0, delta=0.5)

    def test_schnitt_behaelt_den_abstand_zur_gravur(self):
        """Gegenprobe ohne die Korrektur: 20..80 statt 10..90."""
        self.vorlage()
        polys = self.app._schnitt_polys(60.0, 60.0)
        self.assertEqual(self.gezeigt, [])
        x0, y0, x1, y1 = L_vector.bbox(polys)
        self.assertAlmostEqual(x0, 20.0 - self.LUFT, delta=0.6)
        self.assertAlmostEqual(y0, 20.0 - self.LUFT, delta=0.6)
        self.assertAlmostEqual(x1, 80.0 + self.LUFT, delta=0.6)
        self.assertAlmostEqual(y1, 80.0 + self.LUFT, delta=0.6)

    def test_gravur_bleibt_wo_sie_hingehoert(self):
        """Der Schnitt darf sich verschieben, die Gravur nicht.

        Verglichen werden die Zeilen, nicht die Kennzahlen des Jobs: die
        gelten fuer das Ganze, und das Ganze ist mit Schnitt groesser.
        """
        self.vorlage()
        self.app.v_mode.set("schwelle")
        self.app.v_job.set("gravur")
        self.app.generate()
        allein = list(self.app.lines)
        self.app.v_job.set("beides")
        self.app.generate()
        ab = self.app.elemente[0]["ergebnis"]["schnitt_ab"]
        self.assertIsNotNone(ab)
        self.assertEqual(self.app.lines[:ab], allein[:ab])

    def test_der_ganze_job_sagt_seine_ausdehnung(self):
        """Nur das erste Element zu melden hiess: ein Motiv weiter rechts
        kam in den Kennzahlen gar nicht vor."""
        self.vorlage(20.0, 20.0, job="schnitt")
        self.vorlage(120.0, 20.0, job="schnitt")
        self.app.generate()
        x0, x1, y0, y1 = J.extent(self.app.lines)
        self.assertAlmostEqual(self.app.info["xmax"], x1, delta=0.2)
        self.assertAlmostEqual(self.app.info["ymax"], y1, delta=0.2)
        # x0 ist die Rueckfahrt zum Nullpunkt, nicht das Motiv.
        self.assertAlmostEqual(self.app.info["breite"],
                               self.app.info["xmax"] - self.app.info["xmin"],
                               delta=0.01)

    def test_anlauf_wirft_die_anderen_elemente_nicht_weg(self):
        """Hebt der Anlauf den Versatz X an, zaehlte das als Benutzer-
        eingabe: alle schon gerechneten Elemente flogen weg, in der Anzeige
        stand nur noch das letzte Motiv, und generate() fiel ueber das
        fehlende Ergebnis.
        """
        self.vorlage(2.0, 5.0, job="gravur")       # Versatz kleiner als
        self.vorlage(2.0, 70.0, job="gravur")      # der Anlauf bei F1000
        self.app.v_mode.set("schwelle")
        self.app.generate()
        self.assertTrue(all("ergebnis" in e for e in self.app.elemente))
        self.assertEqual(self.app.info["befehle"], len(self.app.lines))
        for e in self.app.elemente:               # beide Motive sind drin
            self.assertLess(len(e["ergebnis"]["lines"]), len(self.app.lines))
        self.assertGreater(self.app.info["ymax"], 70.0)

    def test_ohne_platz_davor_wird_nicht_erzeugt(self):
        """Der Schnitt laege vor dem Nullpunkt - da faehrt nichts hin."""
        self.vorlage()
        self.app.v_xoff.set(0.0)
        self.app.v_yoff.set(0.0)
        self.assertIsNone(self.app._schnitt_polys(60.0, 60.0))
        self.assertTrue(any("Versatz" in m for _, m in self.gezeigt))

    def test_nur_schneiden_fuellt_die_groesse_weiter_aus(self):
        """Ohne Gravur gibt es nichts, woran sich der Schnitt ausrichten
        koennte - dann gilt wieder das eingetippte Mass."""
        self.vorlage()
        self.app.v_job.set("schnitt")
        polys = self.app._schnitt_polys(60.0, 60.0)
        x0, y0, x1, y1 = L_vector.bbox(polys)
        self.assertAlmostEqual(x1 - x0, 60.0, delta=0.2)
        self.assertAlmostEqual(y1 - y0, 60.0, delta=0.2)

    def test_jede_vorlage_wird_von_sich_aus_graviert_und_geschnitten(self):
        """Die Datei sagt selbst, was mit ihr geschehen soll."""
        self.app.v_job.set("gravur")
        self.vorlage(job=None)
        self.assertEqual(self.app.elemente[0]["v_job"], "beides")

    def test_mehrere_vorlagen_bekommen_jede_ihren_rahmen(self):
        """Die Betriebsart gilt je Element: wer zwei Dateien laedt und
        danach einmal 'beides' anklickt, stellte nur die letzte um - und
        bekam genau einen Rahmen in den Job."""
        self.vorlage(20.0, 20.0, job=None)
        self.vorlage(120.0, 20.0, job=None)
        self.app.v_mode.set("schwelle")
        self.app.generate()
        self.assertEqual(self.gezeigt, [])
        schnitte = [z for z in self.app.lines
                    if z.startswith("; Laserwerk Schnitt")]
        self.assertEqual(len(schnitte), 2)
        for e in self.app.elemente:
            self.assertTrue(e["ergebnis"]["cut_polys"])

    def test_erst_alle_gravuren_dann_alle_schnitte(self):
        """Zwei Vorlagen durften nicht Teil fuer Teil abgearbeitet werden:
        das erste Teil lag dann schon lose im Brett, waehrend das zweite
        noch graviert wurde - es kippt hoch, und der Kopf faehrt darueber."""
        self.vorlage(20.0, 20.0, job=None)
        self.vorlage(120.0, 20.0, job=None)
        self.app.v_mode.set("schwelle")
        self.app.generate()
        self.assertEqual(self.gezeigt, [])
        arten = [art for _, art, _, _ in self.app.info["marken"]]
        self.assertEqual(arten, sorted(arten, key="zeile kontur".split().index))
        # Auch im G-Code selbst: beide Schnittbloecke liegen hinten.
        schnitte = [k for k, z in enumerate(self.app.lines)
                    if z.startswith("; Laserwerk Schnitt")]
        self.assertEqual(len(schnitte), 2)
        letzte_zeile = max(idx for idx, art, _, _ in self.app.info["marken"]
                           if art == "zeile")
        self.assertLess(letzte_zeile, min(schnitte))

    def test_eine_vorlage_behaelt_ihre_reihenfolge(self):
        """Ein einzelnes Teil wird nach wie vor graviert und dann
        geschnitten - das Aufteilen darf daran nichts aendern."""
        self.vorlage(20.0, 20.0)
        self.app.v_mode.set("schwelle")
        self.app.generate()
        eins = list(self.app.lines)
        self.app.generate()
        self.assertEqual(self.app.lines, eins)
        arten = [art for _, art, _, _ in self.app.info["marken"]]
        self.assertEqual(arten, sorted(arten, key="zeile kontur".split().index))

    def test_marken_zeigen_auf_ihre_eigene_zeile(self):
        """Werden die Stuecke umsortiert, muessen die Marken mitwandern -
        sonst steht die Anzeige den halben Job auf der falschen Kontur."""
        self.vorlage(20.0, 20.0, job=None)
        self.vorlage(120.0, 20.0, job=None)
        self.app.v_mode.set("schwelle")
        self.app.generate()
        for idx, art, nr, _ in self.app.info["marken"]:
            if art == "kontur":
                # Die Marke steht auf der Anfahrt der Kontur, dahinter
                # beginnt der Schnitt selbst.
                self.assertTrue(self.app.lines[idx].startswith("G0 "),
                                self.app.lines[idx])
                self.assertTrue(self.app.lines[idx + 1].startswith("G1 "),
                                self.app.lines[idx + 1])

    def test_umschalten_nimmt_die_anderen_mit(self):
        """Wer mehrere Dateien laedt und danach einmal umschaltet, meint
        alle. Vorher wurde nur die zuletzt geladene umgestellt - der Rest
        lief in der falschen Betriebsart mit."""
        self.vorlage(20.0, 20.0)
        self.vorlage(120.0, 20.0)
        self.app.v_job.set("gravur")
        self.app._job_changed()
        self.assertEqual([e["v_job"] for e in self.app.elemente],
                         ["gravur", "gravur"])
        self.assertIn("gravieren", self.app.lb_el.get(0))

    def test_farbebenen_bleiben_wie_sie_sind(self):
        """Bei Ebenen ist die Mischung der Zweck: rot schneiden, der Rest
        gravieren. Die darf das Umschalten nicht einsammeln."""
        self.vorlage(20.0, 20.0)
        self.vorlage(120.0, 20.0)
        # Erst nach dem Laden: _element_sichern() schreibt die Felder des
        # gewaehlten Elements zurueck und wuerde die Ebene wieder loeschen.
        self.app.elemente[0]["ebene"] = "#ff0000"
        self.app.v_job.set("gravur")
        self.app._job_changed()
        self.assertEqual(self.app.elemente[0]["v_job"], "beides")

    def test_abgelehnt_bleibt_es_beim_gewaehlten(self):
        """Die Frage ist eine Frage - wer nein sagt, behaelt die Mischung,
        und die Liste sagt sie an."""
        self.vorlage(20.0, 20.0)
        self.vorlage(120.0, 20.0)
        self.L.messagebox.askyesno = lambda t, m: False
        self.app.v_job.set("gravur")
        self.app._job_changed()
        self.assertEqual([e["v_job"] for e in self.app.elemente],
                         ["beides", "gravur"])
        self.assertIn("beides", self.app.lb_el.get(0))
        self.assertIn("gravieren", self.app.lb_el.get(1))

    def test_platz_ueberlebt_den_elementwechsel(self):
        self.vorlage()
        bb = self.app.bild_bb
        self.app._element_sichern()
        self.app.bild_bb = None
        self.app._element_laden(0)
        self.assertEqual(self.app.bild_bb, bb)


def s_werte(zeilen):
    import re
    raus = []
    for z in zeilen:
        if z.startswith("G1"):
            m = re.search(r"S(\d+)", z)
            if m:
                raus.append(int(m.group(1)))
    return raus
