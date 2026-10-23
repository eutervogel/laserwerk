"""
Gemeinsame Vorbereitung fuer alle Tests.

Zwei Dinge sind hier wichtig und muessen VOR dem ersten Zugriff passieren:

  * Einstellungen und Presets zeigen auf ein Wegwerfverzeichnis. Sonst
    schreiben Tests in ~/.config/laserwerk und verstellen dem Benutzer die
    Maschine - das ist beim Bauen tatsaechlich passiert.
  * Der Telegram-Bot wird stillgelegt. Sonst fragt jeder Testlauf gegen den
    echten Bot und streitet sich mit einem laufenden Laserwerk um die
    Nachrichten.

Eine serielle Verbindung baut hier nichts auf; die Maschine wird, wo noetig,
durch eine Attrappe ersetzt.
"""
import os
import sys
import tempfile
import unittest

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WURZEL not in sys.path:
    sys.path.insert(0, WURZEL)

import lw_presets as P                                        # noqa: E402

WEGWERF = tempfile.mkdtemp(prefix="laserwerk-test-")
P.DIR = WEGWERF
P.PRESETS = os.path.join(WEGWERF, "presets.json")
P.CONFIG = os.path.join(WEGWERF, "config.json")

import lw_telegram as TG                                      # noqa: E402

TG.DATEI = os.path.join(WEGWERF, "telegram.json")
TG.Fern.start = lambda self: "test"       # kein Netzverkehr aus Tests


def bildschirm():
    """Gibt es eine Anzeige, auf der tkinter ein Fenster bauen kann?"""
    try:
        import tkinter as tk
    except ImportError:
        return False
    try:
        w = tk.Tk()
        w.destroy()
        return True
    except Exception:
        return False


HAT_BILDSCHIRM = bildschirm()
ohne_bildschirm = unittest.skipUnless(
    HAT_BILDSCHIRM, "keine Anzeige - Oberflaechentests uebersprungen")


class Attrappe:
    """Verhaelt sich wie ein verbundener GRBL-Controller, fuehrt aber nichts
    aus. Merkt sich alles in .protokoll, damit Tests nachsehen koennen."""

    connected = True
    job_running = False
    port = "/dev/attrappe"

    def __init__(self, mpos=(0.0, 0.0, 0.0), s30=1000.0, s32=1.0,
                 x130=200.0, y131=200.0, app=None):
        self.app = app            # fuer Ereignisse wie den Neustart
        self.alarm = None
        self.mpos = tuple(mpos)
        self.wco = (0.0, 0.0, 0.0)
        self.protokoll = []
        self.settings = {"30": s30, "32": s32, "20": 0.0, "110": 1000.0,
                         "120": 30.0, "130": x130, "131": y131}

    @property
    def status(self):
        return {"state": "Idle", "mpos": self.mpos, "wco": self.wco,
                "wpos": tuple(a - b for a, b in zip(self.mpos, self.wco)),
                "fs": (0, 0)}

    def read_settings(self, timeout=3.0):
        return dict(self.settings)

    def wait_idle(self, timeout=8.0):
        return True

    def cmd(self, zeile, timeout=10.0):
        self.protokoll.append(zeile)
        if zeile.startswith("G92") and not self.alarm:
            import re
            ziele = dict(re.findall(r"([XYZ])(-?[\d.]+)", zeile))
            self.wco = tuple(
                self.mpos[i] - float(ziele.get(a, self.mpos[i] - self.wco[i]))
                for i, a in enumerate("XYZ"))
        return "ok"

    def set_zero_xy(self):
        return self.cmd("G92 X0 Y0")

    def goto(self, x=None, y=None, z=None, feed=None):
        ziel = tuple(v if v is not None else self.mpos[i] - self.wco[i]
                     for i, v in enumerate((x, y, z)))
        self.mpos = tuple(a + b for a, b in zip(ziel, self.wco))
        self.protokoll.append("goto %.2f %.2f" % ziel[:2])

    def jog(self, dx=0.0, dy=0.0, dz=0.0, feed=1000):
        self.protokoll.append("jog %+g %+g %+g" % (dx, dy, dz))
        self.mpos = tuple(a + b for a, b in zip(self.mpos, (dx, dy, dz)))

    def unlock(self):
        self.alarm = None
        return "ok"

    def stop(self):
        """Wie GRBL: anhalten, Soft-Reset - der G92-Versatz ist weg, und der
        Controller meldet sich mit seiner Startzeile zurueck."""
        self.protokoll.append("STOPP")
        self.wco = (0.0, 0.0, 0.0)
        if self.app is not None:
            self.app.q.put(("reset", "Grbl 1.1f ['$' for help]"))

    def run_job(self, lines, on_progress, max_errors=50):
        """Streamt nichts, meldet aber wie das Original."""
        self.protokoll.append("JOB %d Zeilen" % len(lines))
        self.gesendet = list(lines)
        on_progress(len(lines), len(lines), 0.1, 0)
        return "fertig"

    def pause(self):
        self.protokoll.append("Pause")

    def resume(self):
        self.protokoll.append("Weiter")

    def realtime(self, b):
        self.protokoll.append("realtime %r" % b)

    def laser_off(self):
        self.protokoll.append("M5")

    def disconnect(self):
        pass


def app_bauen(breite=1270, hoehe=850):
    """Laserwerk mit unsichtbarem Fenster und Maschinenattrappe."""
    import tkinter as tk
    import lw_style as S
    import laserwerk as L
    wurzel = tk.Tk()
    wurzel.withdraw()
    S.apply(wurzel, "dunkel")
    wurzel.geometry("%dx%d" % (breite, hoehe))
    app = L.App(wurzel)
    app.grbl = Attrappe(app=app)
    wurzel.update_idletasks()
    return wurzel, app, L


def app_schliessen(wurzel, app=None):
    """Fenster zumachen wie der Benutzer - ohne haengende Abfrage."""
    try:
        if app is not None:
            app.beenden()
        else:
            wurzel.destroy()
    except Exception:
        try:
            wurzel.destroy()
        except Exception:
            pass
