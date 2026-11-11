#!/usr/bin/env python3
"""
Bildschirmfotos fuers README erzeugen - auf einem unsichtbaren Bildschirm,
damit beim Aufnehmen kein Fenster vor der Arbeit aufspringt.

    xvfb-run -s "-screen 0 1280x880x24" python3 bilder/mach_bilder.py BILD.png [en] [KAMERA.png]

Das Motiv ist ein beliebiges Bild oder SVG; die Bilder im README zeigen eine
Tuschezeichnung, die nicht mit im Projekt liegt.

Das dritte Argument ist eine rohe Kameraaufnahme des Bettes in der Groesse,
in der geeicht wurde. Fehlt sie, entfaellt das Bild vom Kamerareiter - ohne
Aufnahme gibt es dort nichts zu zeigen, und ein leerer Reiter waere ein
schlechteres Bild als gar keines.

Die Maschine wird dabei nur vorgetaeuscht (keine serielle Verbindung, kein
Befehl geht raus). Was man sieht, ist echte Oberflaeche mit echtem G-Code.
"""
import os, subprocess, sys, time
import tkinter as tk

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))

import lw_style as S
import lw_job as J
import lw_text
import laserwerk as L

# Kein Telegram beim Bildermachen: sonst fragt der Bot gegen ein laufendes
# Laserwerk und beide bekommen 409 von Telegram.
L.TG.Fern.start = lambda self: "aus"

# Kein Dialog beim Bildermachen. Auf einem unsichtbaren Schirm wartet ein
# zenity-Fenster bis in alle Ewigkeit auf einen Menschen, der es nie sieht -
# das Skript sieht dann aus, als haenge es, und tut es auch.
L.messagebox.showinfo = lambda *a, **k: None
L.messagebox.showwarning = lambda *a, **k: None
L.messagebox.showerror = lambda *a, **k: None
L.messagebox.askokcancel = lambda *a, **k: True
L.messagebox.askyesno = lambda *a, **k: True
L.messagebox.askyesnocancel = lambda *a, **k: False



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
    sprache = sys.argv[2] if len(sys.argv) > 2 else "de"
    kamera = sys.argv[3] if len(sys.argv) > 3 else None
    lw_text.setze(sprache)
    vorsatz = "" if sprache == "de" else sprache + "-"
    root = tk.Tk()
    S.apply(root, "dunkel")
    root.geometry("1270x850+0+0")
    root.title("Laserwerk")
    app = L.App(root)
    app.grbl = Attrappe()
    # Die Attrappe meldet denselben Verfahrweg, der eingestellt ist -
    # sonst warnt der Maschinenreiter zu Recht, und auf dem Bild steht
    # eine Warnung statt der Maschine.
    app.grbl.settings["130"] = float(app.cfg["x_max"])
    app.grbl.settings["131"] = float(app.cfg["y_max"])
    app.btn_conn.configure(text="Trennen")      # die Attrappe gilt als verbunden
    root.update()

    if quelle and os.path.exists(quelle):
        # Seit dem Laden mehrerer Dateien fragt open_image ueber
        # askopenfilenames. Wer nur den alten Namen abfaengt, bekommt
        # einen echten zenity-Dialog auf einem unsichtbaren Schirm - und
        # das Skript wartet bis in alle Ewigkeit auf einen Menschen, der
        # ihn nie sieht. Beide Namen stillegen.
        L.filedialog.askopenfilename = lambda **k: quelle
        L.filedialog.askopenfilenames = lambda **k: (quelle,)
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
    schiess(root, vorsatz + "01-platzieren.png")

    app.generate()                      # echte Vorschau aus echtem G-Code
    app._draw()
    root.update()                       # erst die Rollflaeche neu berechnen
    runter(app.tab_motiv)               # dann ans Ende: Infotext mit Laufzeit
    root.update()
    schiess(root, vorsatz + "02-gcode.png")
    hoch(app.tab_motiv)

    app.nb.select(1)                    # Material
    app.v_preset.set("Holz / Schichtplatte")
    app.load_preset()
    root.update()
    schiess(root, vorsatz + "03-material.png")

    app.nb.select(2)                    # Maschine
    app._einstellungen_pruefen(app.grbl.settings)
    root.update()
    schiess(root, vorsatz + "04-maschine.png")

    app.nb.select(3)                    # Tests
    root.update()
    runter(app.tab_test)                # die Spalte ist laenger als das Fenster
    root.update()
    schiess(root, vorsatz + "05-tests.png")
    hoch(app.tab_test)

    if kamera and os.path.exists(kamera):
        kamerabild(app, root, kamera, vorsatz)
    root.destroy()


def kamerabild(app, root, pfad, vorsatz):
    """Den Kamerareiter zeigen: erkannte Werkstuecke mit Motiv darauf.

    Gezeigt wird, was die Erkennung wirklich liefert - kein gestelltes
    Bild. Die Eichung kommt aus dem Maschinenprofil dieses Rechners;
    ohne eine passende bleibt der Reiter leer, und dann wird auch kein
    Bild gemacht.
    """
    from PIL import Image
    if not app._kam_eichung().get("homographie"):
        print("  keine Eichung - kein Kamerabild")
        return
    app.cfg["x_max"] = app.cfg["y_max"] = 400.0
    app.v_bw.set(400.0)
    app.v_bh.set(400.0)
    app.v_board.set(False)
    app._kamera_uebernehmen(Image.open(pfad))
    app.v_stueck_min.set(40.0)
    app.stuecke_erkennen()
    runde = [i for i, s in enumerate(app.stuecke) if s["form"] == "rund"]
    for i in [k for k in range(len(app.stuecke)) if k not in runde][::-1]:
        app.stueck_aktiv = i            # alles wegraeumen, was kein Stueck ist
        app.stueck_entfernen()
    if app.stuecke:
        app.stueck_aktiv = 0
        app._stueck_stand()
        if app._box() is not None:
            app.v_w.set(72.0)
            app._keep_ratio("w")
            app.motiv_auf_stueck()
    # Ohne Erklaertexte passt der Reiter ins Bild. Nicht ueber
    # _hilfe_zeigen: das wuerde die Einstellung des Benutzers umstellen
    # und speichern, und ein Bildskript hat an fremden Einstellungen
    # nichts zu suchen.
    for w in app.hilfetexte:
        try:
            w.grid_remove()
        except Exception:
            pass
    app.nb.select(4)                    # Kamera
    root.update()
    runter(app.tab_kam)                 # die Werkstuecke stehen unten
    root.update()
    app._draw()
    schiess(root, vorsatz + "06-kamera.png")


if __name__ == "__main__":
    main()
