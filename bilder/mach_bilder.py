#!/usr/bin/env python3
"""
Bildschirmfotos fuers README erzeugen - auf einem unsichtbaren Bildschirm,
damit beim Aufnehmen kein Fenster vor der Arbeit aufspringt.

    xvfb-run -s "-screen 0 1280x880x24" python3 bilder/mach_bilder.py BILD.png

Das Motiv ist ein beliebiges Bild oder SVG; die Bilder im README zeigen eine
Tuschezeichnung, die nicht mit im Projekt liegt.

Die Maschine wird dabei nur vorgetaeuscht (keine serielle Verbindung, kein
Befehl geht raus). Was man sieht, ist echte Oberflaeche mit echtem G-Code.
"""
import os, subprocess, sys, time
import tkinter as tk

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))

import lw_style as S
import lw_job as J
import laserwerk as L


class Attrappe:
    """Sieht fuer die Oberflaeche aus wie ein verbundener Controller."""
    connected = True
    job_running = False
    alarm = None
    port = "/dev/ttyUSB0"

    def __init__(self, x=24.0, y=18.0):
        self.status = {"state": "Idle", "mpos": (x, y, 12.0), "wco": (0, 0, 0),
                       "wpos": (x, y, 12.0), "fs": (0, 0)}
        self.settings = {"30": 1000.0, "32": 1.0, "130": 200.0, "131": 200.0}

    def read_settings(self, timeout=3.0):
        return dict(self.settings)

    def cmd(self, c, timeout=10):
        return "ok"

    def jog(self, **k):
        pass

    def laser_off(self):
        pass

    def disconnect(self):
        pass


def runter(tab):
    """Die Reiterspalte ans untere Ende rollen."""
    tab.master.yview_moveto(1.0)


def hoch(tab):
    tab.master.yview_moveto(0.0)


def schiess(fenster, name):
    fenster.update_idletasks()
    fenster.update()
    time.sleep(0.6)
    ziel = os.path.join(HIER, name)
    subprocess.run(["import", "-window", "root", ziel], check=True)
    subprocess.run(["convert", ziel, "-strip", ziel], check=True)
    print(f"  {name}  {os.path.getsize(ziel)//1024} kB")


def main():
    quelle = sys.argv[1] if len(sys.argv) > 1 else None
    root = tk.Tk()
    S.apply(root, "dunkel")
    root.geometry("1270x850+0+0")
    root.title("Laserwerk")
    app = L.App(root)
    app.grbl = Attrappe()
    app.btn_conn.configure(text="Trennen")      # die Attrappe gilt als verbunden
    root.update()

    if quelle and os.path.exists(quelle):
        L.filedialog.askopenfilename = lambda **k: quelle
        app.open_image()

    # Werkstueck und Motiv so stellen, wie man es wirklich benutzt
    app.v_bw.set(120.0)
    app.v_bh.set(80.0)
    app.v_w.set(90.0)
    app._keep_ratio("w")
    app.center_motif()
    app.head = (24.0, 18.0)
    app._event("status", app.grbl.status)
    app._draw()
    schiess(root, "01-platzieren.png")

    app.generate()                      # echte Vorschau aus echtem G-Code
    app._draw()
    root.update()                       # erst die Rollflaeche neu berechnen
    runter(app.tab_motiv)               # dann ans Ende: Infotext mit Laufzeit
    root.update()
    schiess(root, "02-gcode.png")
    hoch(app.tab_motiv)

    app.nb.select(1)                    # Material
    app.v_preset.set("Holz / Schichtplatte")
    app.load_preset()
    root.update()
    schiess(root, "03-material.png")

    app.nb.select(2)                    # Maschine
    app._einstellungen_pruefen(app.grbl.settings)
    root.update()
    schiess(root, "04-maschine.png")

    app.nb.select(3)                    # Tests
    root.update()
    schiess(root, "05-tests.png")
    root.destroy()


if __name__ == "__main__":
    main()
