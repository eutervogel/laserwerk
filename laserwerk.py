#!/usr/bin/env python3
"""
Laserwerk - Oberflaeche fuer GRBL-Diodenlaser.

Bild oder SVG laden, skalieren, Material waehlen, Achsen steuern,
Nullpunkt setzen, Fokus testen, gravieren.
"""
import base64, bisect, io, math, os, queue, re, sys, threading, time
import traceback
import urllib.parse
from PIL import Image
import tkinter as tk
from tkinter import ttk

import materialtest as MT
import lw_kamera as KAM
import lw_dialog as D                         # native GTK-Dialoge
from lw_dialog import filedialog, messagebox
import lw_style as S

import lw_grbl as G
import lw_job as J
import lw_presets as P
import lw_vector as V
import lw_projekt as PR
import lw_telegram as TG
import lw_text
from lw_text import T, Z

AREA = 200.0          # mm, Voreinstellung; wirklich gilt cfg["x_max"]/["y_max"]
CANVAS = 540          # px


class App:
    def __init__(self, root):
        self.root = root
        root.title("Laserwerk")
        self.cfg = P.load_config()
        self.presets = P.load_presets()
        self.test = None            # Parameter eines Materialtest-Elements
        self.kam_roh = self.kam_bett = self.kam_tk = None
        self.kam_dicke = None     # Hoehe, mit der kam_bett gerechnet wurde
        self._kam_groesse = None
        self.maschinen = P.load_maschinen()
        self._maschine_einrichten()
        # Erklaertexte helfen beim Lernen und stehen danach im Weg. Sie
        # sammeln sich hier und lassen sich in einem Zug ausblenden.
        self.hilfetexte = []
        self.v_hilfe = tk.BooleanVar(value=bool(self.cfg.get("hilfetexte", True)))
        self.q = queue.Queue()
        self.grbl = G.Grbl(lambda k, d: self.q.put((k, d)))
        self.src = None            # Graustufenbild (zugeschnitten)
        self.src_path = None
        self.bildlinien = False    # SVG mit eingebettetem Bild UND Linien
        self.src_nurbild = False   # und ob src davon nur das Bild zeigt
        self.lines = None          # erzeugter/geladener G-Code
        self.info = None
        self.preview_img = None
        self.preview_pil = None   # Quelle fuer beliebige Zoomstufen
        self.preview_pos = None
        self.zoom = 1.0
        self._prev_cache = None
        self._live_cache = None      # Motivbild in der aktuellen Zoomstufe
        self.drag = None             # laufende Maus-Aktion
        self._rot_alt = 0.0          # Winkel, zu dem die Masse gehoeren
        self.v_bw = tk.DoubleVar(value=self.cfg["brett_x"])   # Brettchen X
        self.v_bh = tk.DoubleVar(value=self.cfg["brett_y"])   # Brettchen Y
        self.v_board = tk.BooleanVar(value=self.cfg["brett_an"])
        self.v_snap = tk.BooleanVar(value=self.cfg["einrasten"])
        self.vec = None            # Konturen (nur bei SVG/DXF)
        self.vec_bb = None         # deren exakte Ausdehnung in mm
        self.bild_bb = None        # Platz des Bildes im selben Blatt
        self._vecdreh = None       # Ausdehnung der gedrehten Konturen
        self.cut_polys = None      # erzeugte Schnittkonturen
        self.schnitt_ab = None     # ab welcher Zeile der Schnitt beginnt
        self._am_erzeugen = False  # laeuft generate() gerade?
        self.zero_ok = False       # Nullpunkt XY in dieser Sitzung gesetzt
        self.zref_ok = False       # Z-Referenz gueltig
        self.fokus_zs = []
        self.fern = None               # Telegram-Fernsteuerung
        self._rettung = None           # Nullpunkt ueber einen Soft-Reset retten
        # Der Versatz des Nullpunkts in Maschinenkoordinaten. Er gilt die ganze
        # Sitzung: solange die Maschine ihre Position kennt, laesst sich der
        # Nullpunkt daraus jederzeit wieder setzen. Nur ein USB-Abriss macht
        # ihn wertlos - dann weiss niemand mehr, wo der Kopf steht.
        self.null_wco = None
        self._still = False            # Felder werden gerade umgeschaltet
        self.elemente = []             # mehrere Motive auf einem Werkstueck
        self.aktiv = -1                # welches davon die Felder bearbeiten
        self.projekt_pfad = None       # zuletzt gespeichertes Projekt
        self.quelle_pfad = None        # Vorlage, wie der Nutzer sie kennt
        self.s_max = float(self.cfg.get("s_max", J.S_MAX))   # $30 der Maschine
        # Beschleunigung, Eilgang, Kreuzungstoleranz und Leistung gehoeren
        # der Maschine. Ohne das rechnete jede Schaetzung mit den Werten des
        # Geraets, auf dem Laserwerk entstanden ist.
        J.setze_maschine(self.cfg)
        self.area = max(float(self.cfg["x_max"]), float(self.cfg["y_max"]), 10.0)
        self.v_zeig_s = tk.IntVar(value=J.zeig_s())   # Sichtkreuz/Rahmen
        self.v_zeig_a = tk.DoubleVar(value=3.0)  # Armlaenge des Kreuzes
        self.v_frame_laser = tk.BooleanVar(value=True)
        self.v_pause_ende = tk.BooleanVar(value=True)   # Pause am Zeilenende
        self.v_xoff = tk.DoubleVar(value=2.0)   # Platz links fuer den Anlauf
        # 0 heisst: aus Vorschub und $120 rechnen. Die frueheren 1,5 mm waren
        # der Wert, den man ueberall abschreibt - bei F1000 und 30 mm/s^2
        # braucht die Achse aber 4,6 mm, bis sie auf Tempo ist. Solange sie
        # beschleunigt, faehrt unter M4 die Leistung mit, und der Anfang jeder
        # Zeile brennt zu schwach. Wer es anders will, traegt es ein.
        self.v_over = tk.DoubleVar(value=0.0)   # Anlauf je Zeilenende
        self.v_yoff = tk.DoubleVar(value=0.0)
        self.v_spiegel = tk.StringVar(value='nein')   # Rueckseite
        self.v_achse = tk.DoubleVar(value=50.0)       # Wendeachse in mm
        self.job_t0 = None
        self.job_schaetzung = None  # Modellzeit des laufenden Jobs
        self._fokus_job = None      # verzoegertes Sichern von Dicke/Korrektur
        self.root.report_callback_exception = self._fehler_melden
        self._build()
        self._poll_id = self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.beenden)
        # Eine gemerkte Korrektur wirkt still weiter. Beim Start einmal
        # sagen, dass sie da ist - sonst sucht man den schiefen Fokus bei
        # der Maschine und nicht in einer Zahl von letzter Woche.
        if self.cfg.get("korrektur"):
            self._log(T("Fokuskorrektur {k:+.2f} mm von zuletzt, Dicke "
                        "{d:.2f} mm -> Z {z:.2f} mm").format(
                            k=self.v_korr.get(), d=self.v_dicke.get(),
                            z=self._z_target()))
        self._draw()

    # ================================================================ Aufbau
    def _build(self):
        r = self.root
        r.columnconfigure(0, weight=1)
        r.rowconfigure(0, weight=1)
        main = ttk.Frame(r, padding=10)
        main.grid(sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)

        # Arbeitsfeld
        self.lf_flaeche = lf = ttk.LabelFrame(main)
        self._flaeche_titel()
        lf.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.cv = tk.Canvas(lf, width=CANVAS, height=CANVAS, bg=S.CANVAS_BG,
                            highlightthickness=1, highlightbackground=S.LINE)
        self.cv.pack(padx=4, pady=4, fill="both", expand=True)
        self._cvsize = (CANVAS, CANVAS)
        self.cv.bind("<Configure>", self._resized)
        self.ox, self.oy = 10, CANVAS - 10          # Ursprung in Bildpunkten (wird beim
                                                    # ersten Zeichnen angepasst)
        for ev in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.cv.bind(ev, self._wheel)
        for b in (2, 3):
            self.cv.bind(f"<Button-{b}>", self._pan_start)
            self.cv.bind(f"<B{b}-Motion>", self._pan_move)
        self.cv.bind("<Double-Button-1>", lambda e: self.reset_view())
        self.cv.bind("<Button-1>", self._press)
        self.cv.bind("<B1-Motion>", self._drag_move)
        self.cv.bind("<ButtonRelease-1>", self._drag_ende)
        # Zeigerform folgt dem, was unter der Maus liegt
        self.cv.bind("<Motion>", self._zeiger)
        self.cv.bind("<Leave>", lambda e: self.cv.configure(cursor=""))
        ttk.Button(lf, text=T("Ansicht zurücksetzen (Doppelklick)"),
                   command=self.reset_view).pack(fill="x", padx=4, pady=(0, 4))

        # Reiter
        nb = self.nb = ttk.Notebook(main)
        nb.grid(row=0, column=1, sticky="nsew")
        self._rollflaechen = []
        self.tab_motiv = self._scrollbereich(nb, "Motiv")
        self.tab_mat = self._scrollbereich(nb, "Material")
        self.tab_masch = self._scrollbereich(nb, "Maschine")
        self.tab_test = self._scrollbereich(nb, "Tests")
        self.tab_kam = self._scrollbereich(nb, "Kamera")
        self._build_motiv()
        self._build_material()
        self._build_maschine()
        self._build_tests()
        self._build_kamera()
        for ev in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.root.bind_all(ev, self._rad, add="+")
        # jede Aenderung, die den G-Code beeinflusst, macht ihn ungueltig
        for v in (self.v_inv, self.v_mode, self.v_schw, self.v_rot,
                  self.v_raster, self.v_luft,
                  self.v_s, self.v_f, self.v_line, self.v_job, self.v_passes,
                  self.v_xoff, self.v_over, self.v_yoff, self.v_gamma,
                  self.v_cs, self.v_cf,
                  self.v_spiegel, self.v_achse,
                  self.v_hell, self.v_kontrast, self.v_schaerfe,
                  self.v_nurbild):
            v.trace_add("write", lambda *a: self._stale())
        for name in self.GEMEINSAM:
            getattr(self, name).trace_add(
                "write", lambda *a: self._werte_koppeln())
        for v in (self.v_f, self.v_over):
            v.trace_add("write", lambda *a: self._anlauf_zeigen())
        self._anlauf_zeigen()
        for v in (self.v_bw, self.v_bh, self.v_board, self.v_snap):
            v.trace_add("write", lambda *a: self._brett_geaendert())

        # Jobleiste: drei Gruppen mit Trennern statt einer Reihe aus sieben
        # Knoepfen. Vorbereiten ruehrt die Maschine nicht an, Zielen faehrt
        # sie mit schwachem Strahl, Fahren brennt - und STOPP steht fuer
        # sich, mit Abstand.
        jb = ttk.Frame(main, padding=(0, 6, 0, 0))
        jb.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.jobknoepfe = {}

        def gruppe(spalte, trenner=True):
            if trenner:
                ttk.Separator(jb, orient="vertical").grid(
                    row=0, column=spalte, sticky="ns", padx=10, pady=2)
            g = ttk.Frame(jb)
            g.grid(row=0, column=spalte + 1)
            return g

        vorbereiten = ttk.Frame(jb)
        vorbereiten.grid(row=0, column=0)
        self.btn_gen = ttk.Button(vorbereiten, text=T("Erzeugen"),
                                  command=self.generate)
        self.btn_gen.pack(side="left")

        zielen = gruppe(1)
        for name, titel, f in (("rahmen", "Rahmen", self.frame),
                               ("kontur", "Kontur", self.kontur)):
            k = ttk.Button(zielen, text=T(titel), command=f)
            k.pack(side="left", padx=2)
            self.jobknoepfe[name] = k
        ttk.Checkbutton(zielen, text=T("sichtbar"), variable=self.v_frame_laser
                        ).pack(side="left", padx=(6, 0))

        fahren = gruppe(3)
        for name, titel, f, st in (("start", "Start", self.start, "Accent.TButton"),
                                   ("pause", "Pause", self.pause, "TButton"),
                                   ("weiter", "Weiter", self.resume, "TButton")):
            k = ttk.Button(fahren, text=T(titel), command=f, style=st)
            k.pack(side="left", padx=2)
            self.jobknoepfe[name] = k
        # "am Zeilenende" reicht: der Knopf daneben heisst Pause.
        ttk.Checkbutton(fahren, text=T("am Zeilenende"),
                        variable=self.v_pause_ende).pack(side="left", padx=(6, 0))

        halt = gruppe(5)
        k = ttk.Button(halt, text=T("STOPP"), command=self.stop,
                       style="Danger.TButton")
        k.pack(side="left")
        self.jobknoepfe["stopp"] = k

        self.prog = ttk.Progressbar(jb, length=78, maximum=1000)
        self.prog.grid(row=0, column=8, padx=8, sticky="e")
        # Ein Etikett, zwei Rollen: solange kein Job laeuft, steht dort der
        # naechste Schritt - die einzige Stelle, die etwas von einem
        # verlangt, also auch die einzige in Akzentfarbe. Laeuft einer,
        # steht dort, wie weit er ist. Beides gleichzeitig braucht niemand,
        # und zwei Etiketten passen bei 1400 Punkten Breite nicht.
        self._jobtext = ""
        self.lbl_prog = ttk.Label(jb, text="", width=24, anchor="e")
        self.lbl_prog.grid(row=0, column=9, sticky="e")
        jb.columnconfigure(7, weight=1)

        if TG.lade().get("auto") and self.v_tg_token.get().strip():
            self.root.after(800, self.fern_start)

        # Eine Zeile, die sagt, woran man ist. Vorher stand das an vier
        # Stellen: Verbindung unten links, Position und Nullpunkt im Reiter
        # "Maschine", der Job unten rechts - und die Maschine nur im
        # Fenstertitel.
        self.lbl_status = ttk.Label(main, text="", anchor="w",
                                    style="Status.TLabel")
        self.lbl_status.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.lbl_marke = ttk.Label(main, text="", anchor="e",
                                   style="Pos.TLabel")
        self.lbl_marke.grid(row=2, column=1, sticky="ew", pady=(6, 0))
        if not self.v_hilfe.get():
            self._hilfe_zeigen()
        self._dnd_einrichten()
        self._status_zeigen()

    # ------------------------------------------------ Ziehen und fallenlassen
    def _dnd_einrichten(self):
        """Dateien aus dem Dateimanager ins Fenster ziehen koennen.

        Dafuer braucht Tk die Erweiterung tkdnd (Ubuntu: apt install
        tkdnd); das XDND-Protokoll selbst nachzubauen waere viel Arbeit
        fuer eine Bequemlichkeit. Fehlt sie, bleibt alles wie vorher - ein
        Programm, das wegen Drag & Drop nicht startet, waere schlimmer.

        Angemeldet wird das ganze Fenster, nicht nur die Flaeche: wer eine
        Datei auf den Reiter fallen laesst, meint dasselbe. Wo genau sie
        gelandet ist, entscheidet nachher der Platz.
        """
        self.dnd = False
        self._dnd_punkt = None
        for paket in ("tkdnd", "tkdnd2.8", "tkdnd1.0"):
            try:
                self.root.tk.call("package", "require", paket)
            except tk.TclError:
                continue
            break
        else:
            self._log(T("Drag & Drop braucht tkdnd - ohne die Erweiterung "
                        "geht es nur über 'Bild/SVG öffnen'."))
            return False
        try:
            # %D sind die Dateien, %X/%Y der Punkt auf dem Schirm. Beides
            # gibt es nur als Tcl-Ersetzung, also wird hier ein Stueck Tcl
            # gebunden statt einer Funktion.
            #
            # Die Lage kommt aus <<DropPosition>>, nicht aus <<Drop>>:
            # tkdnd_unix.tcl setzt in _HandleXdndDrop rootX und rootY fest
            # auf 0, dort ist %X/%Y also immer der linke obere Bildschirm-
            # rand. Waehrend des Ziehens stimmen sie.
            self._dnd_lage_tcl = self.root.register(self._dnd_lage) + " %X %Y"
            self._dnd_fall_tcl = self.root.register(self._dnd_fallen) + " %D"
            self._dnd_anmelden(self.root)
        except tk.TclError as e:
            self._log(T("Drag & Drop nicht eingerichtet: {0}").format(e))
            return False
        self.dnd = True
        self.lbl_maushilfe.configure(text=T(
            "Motiv mit der Maus schieben, an den Ecken ziehen zum "
            "Skalieren,\nam Griff über der Oberkante drehen. Dateien lassen "
            "sich aus dem\nDateimanager hierher ziehen. Der Nullpunkt ist "
            "die linke untere\nEcke des Werkstücks."))
        return True

    def _dnd_dateien(self, daten):
        """Die Liste aus dem Drop in Pfade uebersetzen.

        tkdnd liefert eine Tcl-Liste; Pfade mit Leerzeichen stehen darin in
        geschweiften Klammern. Manche Quellen schicken stattdessen URLs.
        """
        try:
            roh = self.root.tk.splitlist(daten)
        except tk.TclError:
            roh = str(daten).split()
        pfade = []
        for t in roh:
            t = str(t)
            if t.startswith("file://"):
                t = urllib.parse.unquote(t[7:])
                if not t.startswith("/") and "/" in t:
                    t = "/" + t.split("/", 1)[1]     # file://rechner/pfad
            if t:
                pfade.append(t)
        return pfade

    def _dnd_anmelden(self, w):
        """Jedes Fenster anmelden, nicht nur das aeussere.

        tkdnd fragt genau das Widget unter dem Zeiger, ob es Dateien nimmt
        (bind $w <<DropTargetTypes>>, tkdnd_unix.tcl in
        _HandleXdndPosition), und geht dafuer NICHT die Elternkette hoch.
        Nur das Fenster anzumelden hiess deshalb: ueber der Flaeche, ueber
        den Reitern, ueber jedem Feld kam 'refuse_drop' zurueck. Der Zug
        sah aus, als wuerde er angenommen, und beim Loslassen passierte
        nichts - das Fenster selbst liegt ja nirgends frei.
        """
        try:
            self.root.tk.call("tkdnd::drop_target", "register", w,
                              "DND_Files")
            w.bind("<<DropPosition>>", self._dnd_lage_tcl)
            w.bind("<<Drop:DND_Files>>", self._dnd_fall_tcl)
        except tk.TclError:
            pass          # eines, das nicht mag, haelt die anderen nicht auf
        for kind in w.winfo_children():
            self._dnd_anmelden(kind)

    def _dnd_lage(self, x=0, y=0):
        """Wo der Zeiger waehrend des Ziehens steht, in Millimetern.

        Nur solange er ueber der Flaeche ist - wer eine Datei auf den
        Reiter fallen laesst, meint keine Stelle, sondern nur "mach auf".
        Der Rueckgabewert sagt tkdnd, was ein Loslassen taete.
        """
        self._dnd_punkt = None
        try:
            px = int(x) - self.cv.winfo_rootx()
            py = int(y) - self.cv.winfo_rooty()
            if 0 <= px < self.cv.winfo_width() and \
                    0 <= py < self.cv.winfo_height():
                self._dnd_punkt = self._mm_zurueck(px, py)
        except (ValueError, TypeError, tk.TclError):
            pass
        return "copy"

    def _dnd_fallen(self, daten):
        """Dateien sind im Fenster gelandet.

        Geladen wird erst danach. Solange dieser Aufruf laeuft, wartet das
        abgebende Programm auf die Antwort und haelt den Zeiger fest -
        eine SVG zu lesen dauert, und die Rueckfrage nach den Farbebenen
        wartet auf einen Menschen. Mitten im Protokoll stehenzubleiben
        bekommt weder dem Dateimanager noch dem Fenster.
        """
        pfade = self._dnd_dateien(daten)
        spur("Drop: %d Datei(en) %s" % (len(pfade), pfade))
        if not pfade:
            return "refuse_drop"
        wunsch = self._dnd_punkt
        self._dnd_punkt = None
        # Nicht after_idle: Leerlaufarbeiten kann Tk auch noch waehrend des
        # Drops abarbeiten, wenn die C-Seite zwischendurch Ereignisse
        # verteilt. Ein Zeitgeber feuert nur aus der normalen Schleife, und
        # eine Fuenftelsekunde merkt niemand.
        self.root.after(200, lambda: self.dateien_laden(pfade, wunsch=wunsch))
        return "copy"

    def _scrollbereich(self, nb, titel):
        """Reiterinhalt in einen scrollbaren Bereich packen - die Spalte ist
        laenger als mancher Bildschirm."""
        aussen = ttk.Frame(nb)
        nb.add(aussen, text=T(titel))
        cv = tk.Canvas(aussen, highlightthickness=0, bg=S.BG, width=400)
        sb = ttk.Scrollbar(aussen, orient="vertical", command=cv.yview)
        innen = ttk.Frame(cv, padding=12)
        fen = cv.create_window((0, 0), window=innen, anchor="nw")
        # Ohne feste Schrittweite rollt Tk ein Zehntel der Fensterhoehe je
        # Einheit - das waere pro Rastung ein Drittel Seite.
        cv.configure(yscrollcommand=sb.set, yscrollincrement=20)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        def passend(e):
            # Breite mitwachsen lassen: sonst schneidet die Spalte Knoepfe
            # und Hinweise am rechten Rand ab.
            cv.configure(scrollregion=cv.bbox("all"),
                         width=max(400, innen.winfo_reqwidth()))
        innen.bind("<Configure>", passend)
        cv.bind("<Configure>", lambda e: cv.itemconfigure(fen, width=e.width))
        self._rollflaechen.append((str(innen), cv))
        return innen

    @staticmethod
    def _unterhalb(pfad, eltern):
        """Gehoert das Widget zu diesem Bereich? Reiner Praefixvergleich wuerde
        '.!frame' auch in '.!frame2' finden."""
        return pfad == eltern or pfad.startswith(eltern + ".")

    def _rad(self, e):
        """Mausrad in den Reiterspalten.

        Eine einzige Bindung fuer alle Bereiche: frueher rief jeder Reiter
        bind_all auf und ueberschrieb damit den vorherigen - nur der letzte
        liess sich rollen, und auch der nur ueber seinen Feldern.
        """
        pfad = str(e.widget)
        for innen, cv in self._rollflaechen:
            if not (self._unterhalb(pfad, innen) or pfad == str(cv)):
                continue
            bb = cv.bbox("all")
            if not bb or bb[3] - bb[1] <= cv.winfo_height():
                return None                     # passt ohnehin ins Fenster
            if e.num == 4:
                schritt = -1
            elif e.num == 5:
                schritt = 1
            else:
                schritt = -1 if getattr(e, "delta", 0) > 0 else 1
            cv.yview_scroll(schritt * 3, "units")
            return "break"
        return None

    def _row(self, parent, r, label, var, width=8, unit=""):
        """Eine Zeile: Beschriftung, Feld, Einheit.

        Feld und Einheit stehen zusammen in einer Zelle. In einer eigenen
        Gitterspalte wandert die Einheit dorthin, wo das breiteste Widget
        des ganzen Reiters endet - bei der Elementliste also an den rechten
        Rand, meterweit vom Feld entfernt, zu dem sie gehoert.
        """
        ttk.Label(parent, text=T(label)).grid(row=r, column=0, sticky="w", pady=2)
        zelle = ttk.Frame(parent)
        zelle.grid(row=r, column=1, columnspan=2, sticky="w")
        e = ttk.Entry(zelle, textvariable=var, width=width)
        e.pack(side="left")
        if unit:
            ttk.Label(zelle, text=T(unit)).pack(side="left", padx=(6, 0))
        return e

    # ---------------------------------------------------------------- Motiv
    def _build_motiv(self):
        f = self.tab_motiv
        # Breite Widgets ueber alle drei Spalten (Liste, Dateiname) verteilen
        # ihren Ueberschuss sonst gleichmaessig - die Beschriftungsspalte
        # wird dadurch dreimal so breit wie "Breite", und die Felder stehen
        # weit eingerueckt. Der Platz gehoert nach rechts.
        f.columnconfigure(2, weight=1)
        ob = ttk.Frame(f)
        ob.grid(row=0, column=0, columnspan=3, sticky="ew")
        o1 = ttk.Frame(ob)
        o1.pack(fill="x")
        ttk.Button(o1, text=T("Datei öffnen …"), command=self.open_image
                   ).pack(side="left", fill="x", expand=True)
        ttk.Button(o1, text=T("Entfernen"), command=self.element_entfernen
                   ).pack(side="left", padx=(4, 0))
        o2 = ttk.Frame(ob)
        o2.pack(fill="x", pady=(4, 0))
        ttk.Button(o2, text=T("Rechteck …"), command=self.form_dialog
                   ).pack(side="left", fill="x", expand=True)
        ttk.Button(o2, text=T("Rahmen …"), command=self.rahmen_dialog
                   ).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.lb_el = tk.Listbox(f, height=4, exportselection=False,
                                activestyle="none")
        self.lb_el.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 2))
        self.lb_el.bind("<<ListboxSelect>>", self._element_gewaehlt)
        self.lbl_src = ttk.Label(f, text="-", wraplength=260)
        self.lbl_src.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.v_w = tk.DoubleVar(value=100.0)
        self.v_h = tk.DoubleVar(value=100.0)
        self.v_lock = tk.BooleanVar(value=True)
        ew = self._row(f, 3, "Breite", self.v_w, unit="mm")
        eh = self._row(f, 4, "Höhe", self.v_h, unit="mm")
        ew.bind("<FocusOut>", lambda e: self._keep_ratio("w"))
        ew.bind("<Return>", lambda e: self._keep_ratio("w"))
        eh.bind("<FocusOut>", lambda e: self._keep_ratio("h"))
        eh.bind("<Return>", lambda e: self._keep_ratio("h"))
        ttk.Checkbutton(f, text=T("Seitenverhältnis halten"), variable=self.v_lock
                        ).grid(row=5, column=0, columnspan=3, sticky="w")

        wk = ttk.LabelFrame(f, text=T("Werkstück"), padding=4)
        wk.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(6, 2))
        ttk.Label(wk, text=T("Länge X")).grid(row=0, column=0, sticky="w")
        ttk.Spinbox(wk, from_=1, to=2000, increment=1, width=6,
                    textvariable=self.v_bw).grid(row=0, column=1, sticky="w")
        ttk.Label(wk, text=T("Breite Y")).grid(row=0, column=2, sticky="e", padx=(8, 2))
        ttk.Spinbox(wk, from_=1, to=2000, increment=1, width=6,
                    textvariable=self.v_bh).grid(row=0, column=3, sticky="w")
        ttk.Label(wk, text="mm").grid(row=0, column=4, sticky="w")
        ttk.Checkbutton(wk, text=T("anzeigen"), variable=self.v_board
                        ).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(wk, text=T("einrasten"), variable=self.v_snap
                        ).grid(row=1, column=2, columnspan=2, sticky="w")
        # Abstaende zu den vier Kanten: ablesbar und eintippbar. Sonst muss
        # man den Versatz von der Nullecke aus ausrechnen, nur um 5 mm vom
        # rechten Rand wegzubleiben.
        ttk.Label(wk, text=T("Rand")).grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.v_rand = {}
        self.e_rand = {}
        for sp, (seite, name) in enumerate((("l", "links"), ("r", "rechts"))):
            self.v_rand[seite] = tk.DoubleVar(value=0.0)
            ttk.Label(wk, text=T(name)).grid(row=2 + sp, column=1, sticky="e",
                                             padx=(0, 2), pady=(6 if not sp else 0, 0))
            e = ttk.Entry(wk, textvariable=self.v_rand[seite], width=6)
            self.e_rand[seite] = e
            e.grid(row=2 + sp, column=2, sticky="w", pady=(6 if not sp else 0, 0))
            e.bind("<Return>", lambda ev, s=seite: self._rand_setzen(s))
            e.bind("<FocusOut>", lambda ev, s=seite: self._rand_setzen(s))
        for sp, (seite, name) in enumerate((("u", "unten"), ("o", "oben"))):
            self.v_rand[seite] = tk.DoubleVar(value=0.0)
            ttk.Label(wk, text=T(name)).grid(row=2 + sp, column=3, sticky="e",
                                             padx=(8, 2), pady=(6 if not sp else 0, 0))
            e = ttk.Entry(wk, textvariable=self.v_rand[seite], width=6)
            self.e_rand[seite] = e
            e.grid(row=2 + sp, column=4, sticky="w", pady=(6 if not sp else 0, 0))
            e.bind("<Return>", lambda ev, s=seite: self._rand_setzen(s))
            e.bind("<FocusOut>", lambda ev, s=seite: self._rand_setzen(s))

        self._erklaerung(ttk.Label(wk, text=T(
            "Rand = Abstand zum Werkstück. Negativ heißt: das Motiv hängt "
            "darüber hinaus.\nVersatz unten = Abstand zum Nullpunkt der "
            "Maschine."), style="Muted.TLabel")).grid(
                row=4, column=0, columnspan=5, sticky="w", pady=(4, 0))
        ttk.Button(wk, text=T("Motiv mittig setzen"), command=self.center_motif
                   ).grid(row=5, column=0, columnspan=5, sticky="ew", pady=(6, 0))
        self.lbl_maushilfe = self._erklaerung(ttk.Label(wk, text=T(
            "Motiv mit der Maus schieben, an den Ecken ziehen zum "
            "Skalieren,\nam Griff über der Oberkante drehen. Der Nullpunkt "
            "ist die linke\nuntere Ecke des Werkstücks."),
            style="Muted.TLabel"))
        self.lbl_maushilfe.grid(row=6, column=0, columnspan=5, sticky="w")

        box = ttk.LabelFrame(f, text=T("Größe und Lage"), padding=4)
        box.grid(row=7, column=0, columnspan=3, sticky="ew", pady=6)
        self.v_maxw = tk.DoubleVar(value=190.0)
        self.v_maxh = tk.DoubleVar(value=110.0)
        ttk.Label(box, text=T("max.")).grid(row=0, column=0)
        ttk.Entry(box, textvariable=self.v_maxw, width=6).grid(row=0, column=1)
        ttk.Label(box, text="x").grid(row=0, column=2)
        ttk.Entry(box, textvariable=self.v_maxh, width=6).grid(row=0, column=3)
        ttk.Label(box, text="mm").grid(row=0, column=4)
        ttk.Button(box, text=T("Einpassen"), command=self.fit).grid(row=0, column=5, padx=4)
        ttk.Button(box, text=T("Originalgröße 1:1 (SVG/DXF)"), command=self.original_size
                   ).grid(row=1, column=0, columnspan=6, sticky="ew", pady=(4, 6))
        ttk.Label(box, text=T("Anlauf")).grid(row=2, column=0, sticky="w")
        ttk.Spinbox(box, from_=0, to=25, increment=0.5, width=5,
                    textvariable=self.v_over).grid(row=2, column=1, sticky="w")
        ttk.Label(box, text=T("Versatz X")).grid(row=2, column=2, columnspan=2, sticky="e")
        ttk.Spinbox(box, from_=0, to=50, increment=0.5, width=5,
                    textvariable=self.v_xoff).grid(row=2, column=4, sticky="w")
        ttk.Label(box, text="mm").grid(row=2, column=5, sticky="w")
        ttk.Label(box, text=T("Versatz Y")).grid(row=3, column=2, columnspan=2, sticky="e")
        ttk.Spinbox(box, from_=0, to=200, increment=0.5, width=5,
                    textvariable=self.v_yoff).grid(row=3, column=4, sticky="w")
        ttk.Label(box, text="mm").grid(row=3, column=5, sticky="w")
        self.lbl_anlauf = ttk.Label(box, text="", style="Muted.TLabel")
        self.lbl_anlauf.grid(row=4, column=0, columnspan=6, sticky="w", pady=(4, 0))
        self._erklaerung(ttk.Label(box, text=T("0 = aus Vorschub und Beschleunigung gerechnet.\n"
                              "Zu kurz heißt: der Zeilenanfang brennt zu schwach."),
                  style="Muted.TLabel")).grid(row=5, column=0, columnspan=6,
                                             sticky="w")

        rs = ttk.LabelFrame(f, text=T("Rückseite (zweiseitig gravieren)"), padding=4)
        rs.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        for i, (t, v) in enumerate((("Vorderseite", "nein"),
                                    ("Rückseite, Wenden links/rechts", "x"),
                                    ("Rückseite, Wenden oben/unten", "y"))):
            ttk.Radiobutton(rs, text=T(t), value=v, variable=self.v_spiegel
                            ).grid(row=i, column=0, columnspan=3, sticky="w")
        ttk.Label(rs, text=T("Wendeachse bei")).grid(row=3, column=0, sticky="w")
        ttk.Spinbox(rs, from_=0, to=200, increment=0.5, width=6,
                    textvariable=self.v_achse).grid(row=3, column=1, sticky="w")
        ttk.Label(rs, text="mm").grid(row=3, column=2, sticky="w")
        self._erklaerung(ttk.Label(rs, text=T("Mittellinie der Aufspannung, nicht des Motivs."),
                  style="Muted.TLabel")).grid(row=4, column=0, columnspan=3, sticky="w")

        self.v_rot = tk.DoubleVar(value=0.0)
        ttk.Label(f, text=T("Drehen")).grid(row=9, column=0, sticky="w")
        dr = ttk.Frame(f)
        dr.grid(row=9, column=1, columnspan=2, sticky="w")
        sb = ttk.Spinbox(dr, from_=0, to=359.9, increment=5, width=6, wrap=True,
                         textvariable=self.v_rot, command=self._rotated)
        sb.pack(side="left")
        sb.bind("<Return>", lambda e: self._rotated())
        sb.bind("<FocusOut>", lambda e: self._rotated())
        ttk.Label(dr, text="°").pack(side="left", padx=(2, 6))
        for grad in (90, 180, 270, 0):
            ttk.Button(dr, text=f"{grad}°" if grad else "0",
                       width=4 if grad else 3,
                       command=lambda g=grad: self._dreh_setzen(g)).pack(side="left")

        iv = ttk.Frame(f)
        iv.grid(row=10, column=0, columnspan=3, sticky="w")
        self.v_inv = tk.BooleanVar(value=False)
        ttk.Checkbutton(iv, text=T("Invertieren (Hell und Dunkel tauschen)"),
                        variable=self.v_inv).pack(anchor="w")
        # Nur sichtbar, wenn die SVG beides enthaelt: ein eingebettetes Bild
        # und Linien drumherum. Sonst gibt es nichts auszublenden.
        self.v_nurbild = tk.BooleanVar(value=True)
        self.chk_nurbild = ttk.Checkbutton(
            iv, text=T("Nur das eingebettete Bild gravieren"),
            variable=self.v_nurbild, command=self._nurbild_anwenden)
        self.lbl_nurbild = ttk.Label(
            iv, text=T("Die Schnittlinien der Vorlage bleiben dann aus dem\n"
                       "Motiv heraus - sonst brennt das Puzzlemuster mit."),
            style="Muted.TLabel")
        self.v_mode = tk.StringVar(value="schwelle")
        ttk.Radiobutton(f, text=T("Schwarzweiß (Strichgrafik)"), value="schwelle",
                        variable=self.v_mode).grid(row=13, column=0, columnspan=3, sticky="w")
        # Radio und Verfahren in einer Zeile: das eine gilt nur mit dem
        # anderen, und so bleibt die Zeilennummerierung darunter in Ruhe.
        rz = ttk.Frame(f)
        rz.grid(row=12, column=0, columnspan=3, sticky="ew")
        ttk.Radiobutton(rz, text=T("Rasterung (Punktdichte, für Fotos)"), value="raster",
                        variable=self.v_mode).pack(side="left")
        self.v_raster = tk.StringVar(value="floyd")
        self.v_rastername = tk.StringVar(value=self.RASTERNAMEN[0][1])
        self.cb_raster = ttk.Combobox(
            rz, textvariable=self.v_rastername, width=14, state="readonly",
            values=[T(n) for _, n in self.RASTERNAMEN])
        self.cb_raster.pack(side="left", padx=(6, 0))
        self.cb_raster.bind("<<ComboboxSelected>>",
                            lambda e: self._rasterart_gewaehlt())
        self.v_raster.trace_add("write", lambda *a: self._rasterart_zeigen())
        ttk.Radiobutton(f, text=T("Graustufen (Leistung variiert)"), value="grau",
                        variable=self.v_mode).grid(row=11, column=0, columnspan=3, sticky="w")
        self.v_schw = tk.DoubleVar(value=0.5)
        ttk.Label(f, text=T("Schwelle")).grid(row=15, column=0, sticky="w")
        ttk.Scale(f, from_=0.1, to=0.9, variable=self.v_schw, length=140
                  ).grid(row=15, column=1, columnspan=2, sticky="w")

        # Tonwertkurve: hebt oder senkt nur die Mitten. Schwarz bleibt schwarz,
        # Weiss bleibt aus - das Mittel gegen "laeuft alles zu".
        self.v_gamma = tk.DoubleVar(value=1.0)
        ttk.Label(f, text=T("Mitten")).grid(row=16, column=0, sticky="w")
        sg = ttk.Frame(f)
        sg.grid(row=16, column=1, columnspan=2, sticky="w")
        ttk.Scale(sg, from_=0.4, to=2.5, variable=self.v_gamma, length=110,
                  command=lambda v: self._gamma_zeigen()).pack(side="left")
        self.lbl_gamma = ttk.Label(sg, width=4)
        self.lbl_gamma.pack(side="left", padx=(4, 0))
        ttk.Button(sg, text="1:1", width=3,
                   command=lambda: self.v_gamma.set(1.0)).pack(side="left", padx=(2, 0))
        self._erklaerung(ttk.Label(f, style="Muted.TLabel", wraplength=360,
            text=T("Das Verfahren gilt nur für die Rasterung. Atkinson gibt\n"
                   "ein Viertel des Fehlers nicht weiter: kontrastreicher,\n"
                   "und die Mitten laufen nicht zu. Jarvis und Stucki\n"
                   "streuen weiter und wirken feiner. Halbton setzt\n"
                   "gewachsene Punkte statt gestreute - für Schiefer\n"
                   "und Glas, wo ein einzelner Punkt nichts hinterlässt."))).grid(
            row=14, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self.lbl_gammahilfe = ttk.Label(
            f, text=T("größer = Mitten heller (nur Graustufen)"), style="Muted.TLabel")
        self.lbl_gammahilfe.grid(row=17, column=0, columnspan=3, sticky="w")
        self._gamma_zeigen()

        bk = ttk.LabelFrame(f, text=T("Bildkorrektur"), padding=4)
        bk.grid(row=18, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.v_hell = tk.DoubleVar(value=0.0)
        self.v_kontrast = tk.DoubleVar(value=0.0)
        self.v_schaerfe = tk.DoubleVar(value=0.0)
        self.lbl_bk = {}
        for r, (name, var, von, bis) in enumerate((
                ("Helligkeit", self.v_hell, -100, 100),
                ("Kontrast", self.v_kontrast, -100, 100),
                ("Schärfen", self.v_schaerfe, 0, 100))):
            ttk.Label(bk, text=T(name)).grid(row=r, column=0, sticky="w")
            ttk.Scale(bk, from_=von, to=bis, variable=var, length=130,
                      command=lambda v, k=name: self._bk_zeigen()
                      ).grid(row=r, column=1, sticky="w", padx=(4, 0))
            self.lbl_bk[name] = ttk.Label(bk, width=5, anchor="e")
            self.lbl_bk[name].grid(row=r, column=2, sticky="w")
        kb = ttk.Frame(bk)
        kb.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        ttk.Button(kb, text=T("Auto"), command=self.auto_tonwerte
                   ).pack(side="left", fill="x", expand=True)
        ttk.Button(kb, text=T("Zurücksetzen"), command=self.bk_zuruecksetzen
                   ).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self._erklaerung(ttk.Label(bk, text=T("Fotos brauchen das fast immer: ohne Korrektur\n"
                             "brennt ein hellgrauer Hintergrund als dünner\n"
                             "Punkteteppich mit. 'Auto' zieht ihn auf Weiß."),
                  style="Muted.TLabel")).grid(row=4, column=0, columnspan=3, sticky="w")
        self._bk_zeigen()

        jb = ttk.LabelFrame(f, text=T("Bearbeitung"), padding=4)
        jb.grid(row=19, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.v_job = tk.StringVar(value="gravur")
        ttk.Radiobutton(jb, text=T("Gravieren (Flächen, zeilenweise)"), value="gravur",
                        variable=self.v_job, command=self._job_changed).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(jb, text=T("Schneiden (Konturen, SVG/DXF)"), value="schnitt",
                        variable=self.v_job, command=self._job_changed).grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(jb, text=T("Erst gravieren, dann schneiden"), value="beides",
                        variable=self.v_job, command=self._job_changed
                        ).grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Label(jb, text=T("Durchgänge")).grid(row=3, column=0, sticky="w")
        self.v_passes = tk.IntVar(value=1)
        ttk.Spinbox(jb, from_=1, to=10, textvariable=self.v_passes, width=4
                    ).grid(row=3, column=1, sticky="w")
        self.v_luft = tk.BooleanVar(value=bool(self.cfg.get("luft", False)))
        ttk.Checkbutton(jb, text=T("Luft (M8)"), variable=self.v_luft).grid(
            row=3, column=2, columnspan=2, sticky="w", padx=(8, 0))
        self.v_cs = tk.IntVar(value=0)
        self.v_cf = tk.IntVar(value=0)
        ttk.Label(jb, text=T("Schnitt S")).grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(jb, from_=0, to=1000, increment=10, width=6,
                    textvariable=self.v_cs).grid(row=4, column=1, sticky="w", pady=(6, 0))
        ttk.Label(jb, text=T("F")).grid(row=4, column=2, sticky="e", padx=(8, 2),
                                        pady=(6, 0))
        ttk.Spinbox(jb, from_=0, to=5000, increment=50, width=6,
                    textvariable=self.v_cf).grid(row=4, column=3, sticky="w", pady=(6, 0))
        self._erklaerung(ttk.Label(jb, text=T("0 = Werte aus dem Reiter Material.\n"
                             "Schneiden braucht meist mehr Leistung und\n"
                             "weniger Vorschub als Gravieren.\n"
                             "'Luft' schaltet die Düse für den ganzen Job ein\n"
                             "(M8 am Anfang, M9 am Ende) - nur wenn die\n"
                             "Maschine sie über den Controller schaltet."),
                  style="Muted.TLabel")).grid(row=5, column=0, columnspan=4, sticky="w")
        self.v_eigen = tk.BooleanVar(value=False)
        self.chk_eigen = ttk.Checkbutton(
            jb, text=T("Eigene Werte für dieses Element"),
            variable=self.v_eigen, command=self._eigen_geaendert)
        self.chk_eigen.grid(row=6, column=0, columnspan=4, sticky="w",
                            pady=(8, 0))
        self._erklaerung(ttk.Label(jb, text=T(
            "Ohne Haken gelten Leistung, Vorschub, Zeilenabstand und\n"
            "Durchgänge für alle Elemente gemeinsam - ein Werkstück ist\n"
            "aus einem Stück Holz. Egal, an welchem Element man sie\n"
            "einstellt."), style="Muted.TLabel")).grid(
                row=7, column=0, columnspan=4, sticky="w")

        ttk.Button(f, text=T("Vorschau + G-Code erzeugen"), command=self.generate, style="Accent.TButton"
                   ).grid(row=20, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        self.lbl_info = ttk.Label(f, text="", justify="left")
        self.lbl_info.grid(row=21, column=0, columnspan=3, sticky="w")
        bb = ttk.Frame(f)
        bb.grid(row=22, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Button(bb, text=T("G-Code speichern"), command=self.save_gcode).pack(side="left")
        ttk.Button(bb, text=T("G-Code laden"), command=self.load_gcode).pack(side="left", padx=4)
        self.btn_weg = ttk.Button(bb, text=T("Verwerfen"), command=self.verwerfen)
        self.btn_weg.pack(side="left")
        pb = ttk.Frame(f)
        pb.grid(row=23, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Button(pb, text=T("Projekt speichern"), command=self.save_project
                   ).pack(side="left", fill="x", expand=True)
        ttk.Button(pb, text=T("Projekt öffnen"), command=self.open_project
                   ).pack(side="left", fill="x", expand=True, padx=(4, 0))

    # ---------------------------------------------------------------- Material
    def _build_material(self):
        f = self.tab_mat
        self.v_preset = tk.StringVar()
        ttk.Label(f, text=T("Material")).grid(row=0, column=0, sticky="w")
        self.cb_preset = ttk.Combobox(f, textvariable=self.v_preset, width=24,
                                      values=sorted(self.presets), state="readonly")
        self.cb_preset.grid(row=0, column=1, columnspan=2, sticky="ew")
        self.cb_preset.bind("<<ComboboxSelected>>", lambda e: self.load_preset())

        self.v_dicke = tk.DoubleVar(value=self.cfg.get("dicke", 12.0))
        self.v_korr = tk.DoubleVar(value=self.cfg.get("korrektur", 0.0))
        self.v_s = tk.IntVar(value=830)
        self.v_f = tk.IntVar(value=1000)
        self.v_line = tk.DoubleVar(value=0.10)
        self._row(f, 1, "Materialdicke", self.v_dicke, unit="mm")
        # Die Fokuskorrektur stand bis hierher mitten zwischen den Werten,
        # die 'Speichern' ins Preset schreibt - sie gehoert aber zur Maschine
        # und nicht zum Material. Sie steht jetzt beim Fokustest, der sie
        # misst; hier erscheint nur noch die Z-Hoehe, die daraus wird.
        self.v_smin = tk.IntVar(value=0)
        self._row(f, 2, "Leistung S", self.v_s, unit="von 1000")
        self._row(f, 3, "Leistung ab", self.v_smin, unit="0 = automatisch")
        self._row(f, 4, "Vorschub F", self.v_f, unit="mm/min")
        self._row(f, 5, "Zeilenabstand", self.v_line, unit="mm")
        self._erklaerung(ttk.Label(f, text=T("'Leistung ab' ist die kleinste Leistung, bei der das\n"
                            "Material überhaupt zeichnet. Graustufen werden dann\n"
                            "zwischen diesen beiden Werten verteilt statt zwischen\n"
                            "30 % und S. Für Strichgrafik ohne Bedeutung."),
                  style="Muted.TLabel")).grid(row=6, column=0, columnspan=3, sticky="w")
        # Die Werte hier gelten fuer das Material, nicht fuer das Motiv -
        # und damit fuer alle Elemente, die kein eigenes Material haben.
        # Ohne diese Zeile sieht man im Reiter Material nicht, wen man
        # gerade mitverstellt.
        self.lbl_gemeinsam = ttk.Label(f, text="", style="Muted.TLabel",
                                       wraplength=240, justify="left")
        self.lbl_gemeinsam.grid(row=7, column=0, columnspan=3, sticky="w",
                                pady=(4, 0))
        self.lbl_sf = ttk.Label(f, text="")
        self.lbl_sf.grid(row=8, column=0, columnspan=3, sticky="w", pady=4)
        for v in (self.v_s, self.v_f, self.v_smin):
            v.trace_add("write", lambda *a: self._show_sf())
        self.v_notiz = tk.StringVar()
        ttk.Label(f, text=T("Notiz")).grid(row=9, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.v_notiz, width=32).grid(row=10, column=0, columnspan=3, sticky="ew")

        ttk.Button(f, text=T("Übernehmen + Z-Höhe anfahren"),
                   command=self.apply_preset
                   ).grid(row=11, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        ttk.Separator(f).grid(row=12, column=0, columnspan=3, sticky="ew", pady=8)
        self.v_pname = tk.StringVar()
        ttk.Label(f, text=T("Speichern als")).grid(row=13, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.v_pname, width=20).grid(row=13, column=1, columnspan=2, sticky="w")
        bb = ttk.Frame(f)
        bb.grid(row=14, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Button(bb, text=T("Speichern"), command=self.save_preset).pack(side="left")
        ttk.Button(bb, text=T("Löschen"), command=self.delete_preset).pack(side="left", padx=4)
        # Die Hoehe ist ein Wert, der Rest ist eine Erklaerung - und nur
        # der Rest verschwindet, wenn man sie abschaltet.
        self.lbl_zhoehe = ttk.Label(f, text="", style="Muted.TLabel")
        self.lbl_zhoehe.grid(row=15, column=0, columnspan=3, sticky="w",
                             pady=(8, 0))
        self._erklaerung(ttk.Label(f, text=T(
            "Die Korrektur steht im Reiter Tests und gilt für jedes\n"
            "Material. Dafür muss unter 'Maschine' eine Z-Referenz\n"
            "gesetzt sein."), style="Muted.TLabel")).grid(
                row=16, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self._show_sf()

    # ---------------------------------------------------------------- Maschine
    def _build_kamera(self):
        """Die Kamera im Deckel: Bild holen, entzerren, unterlegen.

        Die Eichung gehoert zur Maschine, nicht zum Werkstueck - die
        Kamera ist festgeschraubt. Sie liegt deshalb im Maschinenprofil
        und wechselt mit.
        """
        f = self.tab_kam
        kf = ttk.LabelFrame(f, text=T("Kamera"), padding=4)
        kf.grid(row=0, column=0, columnspan=3, sticky="ew")
        kf.columnconfigure(0, weight=1)
        self.v_kamera = tk.StringVar(value=self._kam_eichung().get("geraet", ""))
        self.cb_kamera = ttk.Combobox(kf, textvariable=self.v_kamera, width=18,
                                      values=[g for g, _ in self._kameras()])
        self.cb_kamera.grid(row=0, column=0, sticky="ew")
        ttk.Button(kf, text=T("neu suchen"), width=11,
                   command=self._kameras_suchen).grid(row=0, column=1, padx=4)
        ttk.Button(kf, text=T("Bild holen"), width=11, style="Accent.TButton",
                   command=self.kamera_holen).grid(row=0, column=2)
        self.lbl_kam = ttk.Label(kf, text="", style="Muted.TLabel", wraplength=360)
        self.lbl_kam.grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 0))

        self.v_kam_an = tk.BooleanVar(value=False)
        ttk.Checkbutton(kf, text=T("Bild unter die Zeichenfläche legen"),
                        variable=self.v_kam_an,
                        command=self._kamera_zeigen).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._erklaerung(ttk.Label(kf, style="Muted.TLabel", wraplength=360,
            text=T("Das Bild ist dann in Maschinenkoordinaten entzerrt: was\n"
                   "darauf an einer Stelle liegt, liegt dort auch wirklich.")
            )).grid(row=3, column=0, columnspan=3, sticky="w")

        hf = ttk.LabelFrame(f, text=T("Höhe"), padding=4)
        hf.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Label(hf, text=T("Kamera über dem Bett")).grid(row=0, column=0, sticky="w")
        self.v_kam_hoehe = tk.DoubleVar(value=self._kam_eichung().get("hoehe", 0.0))
        # command= allein reicht nicht: das loest nur beim Klick auf die
        # Pfeilchen aus. Wer die Zahl hineintippt und weiterklickt, haette
        # sie sonst nirgends gespeichert - und saehe nur, dass sich nichts
        # aendert.
        sp_hoehe = ttk.Spinbox(hf, from_=0.0, to=1000.0, increment=5.0, width=6,
                               textvariable=self.v_kam_hoehe,
                               command=self._kam_hoehe_sichern)
        sp_hoehe.grid(row=0, column=1, padx=4)
        sp_hoehe.bind("<Return>", lambda e: self._kam_hoehe_sichern())
        sp_hoehe.bind("<FocusOut>", lambda e: self._kam_hoehe_sichern())
        ttk.Label(hf, text="mm").grid(row=0, column=2, sticky="w")
        self._erklaerung(ttk.Label(hf, style="Muted.TLabel", wraplength=360,
            text=T("Die Eichung gilt für eine Höhe. Ein dickes Brett liegt\n"
                   "näher an der Kamera und erscheint nach außen verschoben.\n"
                   "Mit diesem Maß rechnet Laserwerk die Materialstärke heraus.\n"
                   "0 heißt: nicht herausrechnen."))).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(3, 0))

        ttk.Label(hf, text=T("Unterlage über dem Bett")).grid(
            row=2, column=0, sticky="w", pady=(4, 0))
        self.v_kam_unterlage = tk.DoubleVar(
            value=float(self.cfg.get("kam_unterlage", 0.0) or 0.0))
        sp_unter = ttk.Spinbox(hf, from_=0.0, to=200.0, increment=1.0, width=6,
                               textvariable=self.v_kam_unterlage,
                               command=self._kam_unterlage_sichern)
        sp_unter.grid(row=2, column=1, padx=4, pady=(4, 0))
        sp_unter.bind("<Return>", lambda e: self._kam_unterlage_sichern())
        sp_unter.bind("<FocusOut>", lambda e: self._kam_unterlage_sichern())
        ttk.Label(hf, text="mm").grid(row=2, column=2, sticky="w", pady=(4, 0))
        self._erklaerung(ttk.Label(hf, style="Muted.TLabel", wraplength=360,
            text=T("Wabenplatte oder Opferbrett: was darauf liegt, liegt um\n"
                   "so viel höher. Die Materialstärke kommt aus dem Reiter\n"
                   "Material und zählt dazu."))).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(3, 0))
        self._kam_zeigen()

    def _kameras(self):
        try:
            return KAM.kameras()
        except Exception:
            return []

    def _kameras_suchen(self):
        self.cb_kamera.configure(values=[g for g, _ in self._kameras()])

    def _kam_eichung(self):
        d = self.cfg.get("kamera")
        return d if isinstance(d, dict) else {}

    MINDESTHOEHE = 50.0        # mm - darunter ist es keine Kamerahoehe

    def _kam_hoehe_sichern(self):
        """Die Kamerahoehe uebernehmen - oder sagen, dass sie keine ist.

        Das Feld will den Abstand Bett bis Linse, also einige hundert
        Millimeter. Wer dort die Materialstaerke eintraegt, bekommt einen
        Korrekturfaktor H/(H-d) nahe unendlich - und sieht nur, dass das
        Bild wegrutscht, nicht warum.
        """
        d = self._kam_eichung()
        if not d:
            return
        try:
            wert = float(self.v_kam_hoehe.get())
        except (tk.TclError, ValueError):
            return
        if 0 < wert < self.MINDESTHOEHE:
            messagebox.showwarning(T("Kamera"), T(
                "{w:.0f} mm ist keine Kamerahöhe - gemeint ist der Abstand "
                "vom Bett bis zur Linse, bei dieser Maschine ein paar "
                "hundert Millimeter.\n\nDie Materialstärke steht im Reiter "
                "Material und wird davon getrennt gerechnet.").format(w=wert))
            self.v_kam_hoehe.set(d.get("hoehe", 0.0))
            return
        d["hoehe"] = wert
        self.cfg["kamera"] = d
        P.save_config(self.cfg)
        self._maschine_sichern()
        self._kamera_neu_rechnen(zwingen=True)
        self._kamera_zeigen()

    def _kam_zeigen(self):
        if not hasattr(self, "lbl_kam"):
            return
        d = self._kam_eichung()
        self.lbl_kam.configure(text=KAM.eichung_lesbar(d) if d
                               else T("Noch keine Eichung für diese Maschine."))

    def kamera_holen(self):
        """Ein Bild holen und, wenn eine Eichung da ist, entzerren."""
        geraet = self.v_kamera.get().strip()
        if not geraet:
            messagebox.showinfo(T("Kamera"), T("Erst eine Kamera wählen."))
            return
        # In der Groesse, in der geeicht wurde. Die Eichung steht in
        # Bildpunkten: holt man kleiner, zeigt jeder Koeffizient daneben.
        b, h = self._kam_eichung().get("bild", (2592, 1944))
        def arbeit():
            roh = KAM.bild_holen(geraet, int(b), int(h))
            self.q.put(("kamerabild", roh))
        self._bg(arbeit, T("hole ein Bild von {g}").format(g=geraet))

    def _kam_zahl(self, name, vorgabe=0.0):
        var = getattr(self, name, None)
        try:
            return float(var.get())
        except (tk.TclError, ValueError, AttributeError):
            return vorgabe

    def _kam_dicke(self):
        """Wie hoch die sichtbare Oberseite ueber der Eichebene liegt.

        Geeicht wurde in einer Ebene - hier dem nackten Bett. Darauf liegt
        die Unterlage, darauf das Material, und gesehen wird die Oberseite:
        beide Maße zaehlen zusammen. Lag beim Eichen selbst schon etwas
        unter der Karte, steht das in der Eichung und wird abgezogen,
        sonst zaehlte es doppelt.
        """
        return (self._kam_zahl("v_dicke") + self._kam_zahl("v_kam_unterlage")
                - float(self._kam_eichung().get("dicke", 0.0) or 0.0))

    def _kam_bett_rechnen(self):
        """Aus dem rohen Bild die Draufsicht fuer die jetzige Hoehe."""
        dicke = self._kam_dicke()
        self.kam_bett = KAM.bett_bild(
            self.kam_roh, self._kam_eichung(),
            0.0, 0.0, float(self.cfg["x_max"]), float(self.cfg["y_max"]),
            px_je_mm=2.0, dicke=dicke)
        self.kam_dicke = dicke
        return dicke

    def _kamera_neu_rechnen(self, zwingen=False):
        """Den Untergrund auf die jetzige Hoehe umrechnen.

        Das entzerrte Bild gilt fuer eine Hoehe. Wer nach dem Bildholen
        die Materialstaerke aendert oder ein Preset laedt, sah bisher
        weiter das Bild der alten Staerke - um ein paar Millimeter
        versetzt, und nichts sagte es ihm. Neu geholt werden muss dafuer
        nichts: das rohe Bild liegt noch da.
        """
        if getattr(self, "kam_roh", None) is None or self.kam_bett is None:
            return False
        if not zwingen and abs(self._kam_dicke() - (self.kam_dicke or 0.0)) < 0.05:
            return False
        self._log(T("Untergrund neu gerechnet: {d:.1f} mm über der Eichebene.")
                  .format(d=self._kam_bett_rechnen()))
        return True

    def _kam_unterlage_sichern(self):
        """Die Unterlage uebernehmen und das Bild darauf umrechnen."""
        self.cfg["kam_unterlage"] = max(0.0, self._kam_zahl("v_kam_unterlage"))
        if self.v_kam_unterlage.get() != self.cfg["kam_unterlage"]:
            self.v_kam_unterlage.set(self.cfg["kam_unterlage"])
        P.save_config(self.cfg)
        self._maschine_sichern()
        self._kamera_neu_rechnen()
        self._kamera_zeigen()

    def _kamera_uebernehmen(self, roh):
        """Das frische Bild entzerren und merken."""
        self.kam_roh = roh
        self.kam_bett = self.kam_dicke = None
        d = self._kam_eichung()
        if not d:
            self._log(T("Bild geholt ({b}x{h}) - ohne Eichung nur ein Bild.")
                      .format(b=roh.size[0], h=roh.size[1]))
            return
        soll = tuple(d.get("bild", (0, 0)))
        if soll and tuple(roh.size) != soll:
            # Nicht stillschweigend weiterrechnen: eine 16:9-Aufloesung ist
            # aus einem 4:3-Sensor ein Ausschnitt, kein verkleinertes Bild.
            # Umrechnen waere geraten, und man saehe es dem Ergebnis nicht an.
            messagebox.showwarning(T("Kamera"), T(
                "Die Eichung gilt für {sb}x{sh} Bildpunkte, die Kamera "
                "liefert {ib}x{ih}.\n\nDas Bild wird nicht entzerrt - die "
                "Kamera kann die geeichte Auflösung gerade nicht.").format(
                    sb=soll[0], sh=soll[1], ib=roh.size[0], ih=roh.size[1]))
            self._log(T("Bild {ib}x{ih} passt nicht zur Eichung ({sb}x{sh}).")
                      .format(ib=roh.size[0], ih=roh.size[1],
                              sb=soll[0], sh=soll[1]))
            return
        dicke = self._kam_bett_rechnen()
        self._log(T("Bild {rb}x{rh} entzerrt auf {bb}x{bh} für {x:.0f} x {y:.0f} mm, "
                    "Materialstärke {d:.1f} mm.").format(
            rb=roh.size[0], rh=roh.size[1],
            bb=self.kam_bett.size[0], bh=self.kam_bett.size[1],
            x=float(self.cfg["x_max"]), y=float(self.cfg["y_max"]), d=dicke))
        if not self.v_kam_an.get():
            self.v_kam_an.set(True)
        self._kamera_zeigen()

    def _kamera_zeigen(self):
        self.kam_tk = None
        self._draw()

    def _kamera_unterlegen(self, x0, y0, x1, y1):
        """Das entzerrte Bild unter das Raster legen.

        Tk haelt kein Bild, auf das niemand mehr zeigt - deshalb bleibt
        die PhotoImage in self.kam_tk stehen, sonst ist die Flaeche nach
        dem naechsten Durchlauf wieder leer.
        """
        if not (getattr(self, "v_kam_an", None) and self.v_kam_an.get()):
            return
        bett = getattr(self, "kam_bett", None)
        if bett is None:
            return
        b, h = max(1, int(round(x1 - x0))), max(1, int(round(y0 - y1)))
        if self.kam_tk is None or self._kam_groesse != (b, h):
            # Ueber PNG und base64 statt ueber ImageTk: das steckt in einem
            # eigenen Paket (python3-pil.imagetk), das nicht ueberall
            # mitkommt. Tk liest PNG seit 8.6 selbst, und der Rest von
            # Laserwerk macht es schon genauso.
            puffer = io.BytesIO()
            bett.resize((b, h), Image.LANCZOS).save(puffer, format="PNG")
            self.kam_tk = tk.PhotoImage(
                data=base64.b64encode(puffer.getvalue()))
            self._kam_groesse = (b, h)
        self.cv.create_image(x0, y1, image=self.kam_tk, anchor="nw",
                             tags="kamera")

    def _build_maschine(self):
        f = self.tab_masch
        # Maschine und Anschluss gehoeren zusammen: beide beantworten die
        # Frage, mit wem Laserwerk gleich redet.
        mf = ttk.LabelFrame(f, text=T("Maschine"), padding=4)
        mf.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        mf.columnconfigure(0, weight=1)
        self.v_maschine = tk.StringVar(value=self._maschine_name())
        self.cb_maschine = ttk.Combobox(mf, textvariable=self.v_maschine,
                                        width=15, state="readonly",
                                        values=self._maschinen_namen())
        self.cb_maschine.grid(row=0, column=0, sticky="ew")
        self.cb_maschine.bind("<<ComboboxSelected>>",
                              lambda e: self.maschine_wechseln(self.v_maschine.get()))
        # Daneben der Name einer neuen: frei eintippen oder eine bekannte
        # Maschine aus der Liste nehmen, die bringt ihre Werte mit.
        self.v_mneu = tk.StringVar()
        ttk.Combobox(mf, textvariable=self.v_mneu, width=9,
                     values=sorted(P.VORLAGEN)).grid(row=0, column=1, padx=4)
        ttk.Button(mf, text=T("anlegen"), command=self.maschine_anlegen,
                   width=11).grid(row=0, column=2)
        self.v_port = tk.StringVar(value=self.cfg.get("port", ""))
        self.cb_port = ttk.Combobox(mf, textvariable=self.v_port, width=15,
                                    values=G.ports())
        self.cb_port.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(3, 0))
        ttk.Button(mf, text=T("neu suchen"), command=lambda: self.cb_port.configure(
            values=G.ports()), width=11).grid(row=1, column=2, pady=(3, 0))
        # Die Leistung gehoert zur Maschine, nicht zum Verfahrweg: sie
        # entscheidet, was dieselbe Energie je Millimeter kostet.
        self.v_watt = tk.DoubleVar(value=float(self.cfg.get("watt", J.WATT)))
        lw = ttk.Frame(mf)
        lw.grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))
        ttk.Label(lw, text=T("Leistung")).pack(side="left")
        ttk.Spinbox(lw, from_=0.5, to=200.0, increment=0.5, width=5,
                    textvariable=self.v_watt, command=self.set_watt
                    ).pack(side="left", padx=3)
        ttk.Label(lw, text=T("W optisch")).pack(side="left")
        ttk.Button(mf, text=T("übernehmen"), command=self.set_watt, width=11
                   ).grid(row=2, column=2, pady=(3, 0))
        self.lbl_maschine = ttk.Label(mf, text="", style="Muted.TLabel")
        self.lbl_maschine.grid(row=3, column=0, columnspan=3, sticky="w")
        self.lbl_watt = ttk.Label(mf, text="", style="Muted.TLabel")
        self.lbl_watt.grid(row=4, column=0, columnspan=3, sticky="w")
        self._maschine_zeigen()
        self._watt_zeigen()
        self.btn_conn = ttk.Button(f, text=T("Verbinden"),
                                   command=self.toggle_connect,
                                   style="Accent.TButton")
        self.btn_conn.grid(row=1, column=0, columnspan=3, sticky="ew", pady=4)


        jg = ttk.LabelFrame(f, text=T("Verfahren"), padding=4)
        jg.grid(row=4, column=0, columnspan=3, sticky="ew", pady=6)
        self.v_step = tk.DoubleVar(value=1.0)
        sr = ttk.Frame(jg)
        sr.grid(row=0, column=0, columnspan=5)
        for s in (0.1, 1.0, 10.0, 50.0):
            ttk.Radiobutton(sr, text=T('{0:g} mm').format(s), value=s, variable=self.v_step
                            ).pack(side="left")
        B = lambda t, c, r, col: ttk.Button(jg, text=T(t), width=9 if "Z" in t else 5,
                                            command=c).grid(row=r, column=col, padx=1, pady=1)
        B("Y+", lambda: self.jog(0, 1, 0), 1, 1)
        B("X-", lambda: self.jog(-1, 0, 0), 2, 0)
        B("X+", lambda: self.jog(1, 0, 0), 2, 2)
        B("Y-", lambda: self.jog(0, -1, 0), 3, 1)
        B("Z hoch", lambda: self.jog(0, 0, 1), 1, 4)
        B("Z runter", lambda: self.jog(0, 0, -1), 3, 4)
        self.v_zinv = tk.BooleanVar(value=self.cfg.get("z_invert", False))
        ttk.Checkbutton(jg, text=T("Z-Richtung umkehren"), variable=self.v_zinv,
                        command=self._save_cfg).grid(row=4, column=0, columnspan=5, sticky="w")

        vw = ttk.LabelFrame(f, text=T("Verfahrweg der Maschine"), padding=4)
        vw.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(6, 2))
        self.v_xmax = tk.DoubleVar(value=self.cfg["x_max"])
        self.v_ymax = tk.DoubleVar(value=self.cfg["y_max"])
        ttk.Label(vw, text="X").grid(row=0, column=0, sticky="w")
        ttk.Entry(vw, textvariable=self.v_xmax, width=6).grid(row=0, column=1)
        ttk.Label(vw, text=T("x  Y")).grid(row=0, column=2)
        ttk.Entry(vw, textvariable=self.v_ymax, width=6).grid(row=0, column=3)
        ttk.Label(vw, text="mm").grid(row=0, column=4, sticky="w")
        ttk.Button(vw, text=T("übernehmen"), command=self.set_area
                   ).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        ttk.Button(vw, text=T("aus der Maschine ($130/$131)"), command=self.area_von_maschine
                   ).grid(row=1, column=3, columnspan=2, sticky="ew", padx=(4, 0), pady=(4, 0))
        self._erklaerung(ttk.Label(vw, text=T("Bestimmt die gezeichnete Arbeitsfläche und die\n"
                             "Warnung, wenn ein Job nicht hineinpasst."),
                  style="Muted.TLabel")).grid(row=2, column=0, columnspan=5, sticky="w")


        # Beide Nullpunktknoepfe nebeneinander in eine Zelle - eine neue
        # Gitterzeile waere die Gelegenheit fuer genau die Ueberdeckung,
        # die in der Jobleiste jahrelang den STOPP zugedeckt hat.
        nb = ttk.Frame(f)
        nb.grid(row=6, column=0, columnspan=3, sticky="ew", pady=2)
        ttk.Button(nb, text=T("Nullpunkt XY = hier"), command=self.set_zero
                   ).pack(side="left", fill="x", expand=True)
        self.btn_null_zurueck = ttk.Button(
            nb, text=T("Nullpunkt zurück"), command=self.null_zurueck_knopf)
        self.btn_null_zurueck.pack(side="left", fill="x", expand=True, padx=(4, 0))
        zr = ttk.Frame(f)
        zr.grid(row=7, column=0, columnspan=3, sticky="ew", pady=2)
        ttk.Label(zr, text=T("Fokus sitzt auf Material")).pack(side="left")
        self.v_zref = tk.DoubleVar(value=12.0)
        ttk.Entry(zr, textvariable=self.v_zref, width=5).pack(side="left", padx=2)
        ttk.Label(zr, text="mm").pack(side="left")
        ttk.Button(zr, text=T("Z-Referenz"), command=self.set_zref).pack(side="left", padx=4)
        ttk.Button(f, text=T("Zum Nullpunkt fahren"), command=self.goto_zero
                   ).grid(row=8, column=0, columnspan=3, sticky="ew", pady=2)
        zg = ttk.LabelFrame(f, text=T("Position zeigen"), padding=4)
        zg.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        ttk.Label(zg, text=T("Leistung S")).grid(row=0, column=0, sticky="w")
        ttk.Spinbox(zg, from_=5, to=120, increment=5, width=5,
                    textvariable=self.v_zeig_s).grid(row=0, column=1, sticky="w")
        ttk.Label(zg, text=T("Kreuz +/- mm")).grid(row=1, column=0, sticky="w")
        ttk.Spinbox(zg, from_=0.5, to=8, increment=0.5, width=5,
                    textvariable=self.v_zeig_a).grid(row=1, column=1, sticky="w")
        ttk.Button(zg, text=T("Kreuz fahren"), command=self.zeigen
                   ).grid(row=0, column=2, rowspan=2, padx=(8, 0), sticky="nsew")
        self._erklaerung(ttk.Label(zg, text=T("Kurzes Kreuz mit schwacher Leistung, danach\n"
                             "exakt zurück. Gilt auch für 'Rahmen sichtbar'."),
                  style="Muted.TLabel")).grid(row=2, column=0, columnspan=3, sticky="w")
        bb = ttk.Frame(f)
        bb.grid(row=9, column=0, columnspan=3, sticky="ew", pady=2)
        ttk.Button(bb, text=T("Entsperren ($X)"), command=self.unlock).pack(side="left")
        ttk.Button(bb, text=T("Laser aus (M5)"), command=self.laser_off).pack(side="left", padx=4)

        ttk.Label(f, text=T("Befehl:")).grid(row=11, column=0, sticky="w", pady=(8, 0))
        self.v_cmd = tk.StringVar()
        ec = ttk.Entry(f, textvariable=self.v_cmd, width=22)
        ec.grid(row=12, column=0, columnspan=2, sticky="ew")
        ec.bind("<Return>", lambda e: self.send_cmd())
        ttk.Button(f, text=T("senden"), command=self.send_cmd).grid(row=12, column=2)
        sp = ttk.LabelFrame(f, text=T("Darstellung"), padding=4)
        sp.grid(row=15, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        self.v_sprache = tk.StringVar(
            value=lw_text.SPRACHEN.get(self.cfg.get("sprache", "de"), "Deutsch"))
        cbs = ttk.Combobox(sp, textvariable=self.v_sprache, state="readonly",
                           width=12, values=list(lw_text.SPRACHEN.values()))
        cbs.grid(row=0, column=0, sticky="w")
        cbs.bind("<<ComboboxSelected>>", lambda e: self.set_sprache())
        self.btn_theme = ttk.Button(sp, command=self.toggle_theme, width=8)
        self.btn_theme.grid(row=0, column=1, padx=(8, 0), sticky="w")
        self._theme_label()
        ttk.Checkbutton(sp, text=T("Erklärungen anzeigen"),
                        variable=self.v_hilfe, command=self._hilfe_zeigen
                        ).grid(row=1, column=0, columnspan=2, sticky="w",
                               pady=(4, 0))
        self._erklaerung(ttk.Label(sp, text=T("Die Sprache gilt nach einem Neustart."),
                  style="Muted.TLabel")).grid(row=2, column=0, columnspan=2,
                                             sticky="w", pady=(4, 0))

        tg = ttk.LabelFrame(f, text=T("Fernsteuerung über Telegram"), padding=4)
        tg.grid(row=13, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        d = TG.lade()
        self.v_tg_token = tk.StringVar(value=d.get("token", ""))
        self.v_tg_auto = tk.BooleanVar(value=d.get("auto", False))
        ttk.Label(tg, text=T("Token")).grid(row=0, column=0, sticky="w")
        ttk.Entry(tg, textvariable=self.v_tg_token, width=22, show="•"
                  ).grid(row=0, column=1, columnspan=2, sticky="ew")
        self.btn_tg = ttk.Button(tg, text=T("Bot starten"), command=self.fern_start)
        self.btn_tg.grid(row=1, column=0, columnspan=2, sticky="ew", pady=3)
        ttk.Button(tg, text=T("Chat lösen"), command=self.fern_loesen
                   ).grid(row=1, column=2, padx=(4, 0))
        self.lbl_tg = ttk.Label(tg, text=T("aus"))
        self.lbl_tg.grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(tg, text=T("beim Programmstart mitstarten"),
                        variable=self.v_tg_auto, command=self._tg_auto
                        ).grid(row=3, column=0, columnspan=3, sticky="w")
        self._erklaerung(ttk.Label(tg, text=T("Achsen und Sichtkreuz vom Handy. Gravur und\n"
                             "Schnitt starten absichtlich nur hier."),
                  style="Muted.TLabel")).grid(row=4, column=0, columnspan=3, sticky="w")
        tg.columnconfigure(1, weight=1)

        self.log = tk.Text(f, width=36, height=6, font=("DejaVu Sans Mono", 8),
                           bg=S.PANEL, fg=S.TEXT, relief="flat", highlightthickness=1,
                           highlightbackground=S.LINE, padx=6, pady=4)
        self.log.grid(row=16, column=0, columnspan=3, sticky="ew", pady=4)

    # ---------------------------------------------------------------- Tests
    def _build_tests(self):
        f = self.tab_test
        fb = ttk.LabelFrame(f, text=T("Fokustest über Z"), padding=6)
        fb.grid(row=0, column=0, sticky="ew")
        self.v_ft_span = tk.DoubleVar(value=4.0)
        self.v_ft_step = tk.DoubleVar(value=0.5)
        self.v_ft_s = tk.IntVar(value=300)
        self.v_ft_f = tk.IntVar(value=600)
        self._row(fb, 0, "Spanne", self.v_ft_span, unit="mm")
        self._row(fb, 1, "Schritt", self.v_ft_step, unit="mm")
        self._row(fb, 2, "Leistung S", self.v_ft_s)
        self._row(fb, 3, "Vorschub F", self.v_ft_f)
        self._erklaerung(ttk.Label(fb, text=T("Striche von links nach rechts\n"
                             "= Z aufsteigend."), style="Muted.TLabel")).grid(
                                 row=4, column=0, columnspan=3, sticky="w")
        # Die gemessene Korrektur ueberlebt den Neustart, stand aber nur als
        # nackte Zahl im Reiter Material. Hier, wo sie herkommt, gehoert sie
        # hin - samt der Hoehe, die daraus wird, und von Hand nachstellbar.
        # Sonst bleibt als einziger Weg zu einem anderen Wert ein neuer Test.
        kr = ttk.Frame(fb)
        kr.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Label(kr, text=T("Fokuskorrektur")).pack(side="left")
        ttk.Spinbox(kr, from_=-50.0, to=50.0, increment=0.05, width=7,
                    textvariable=self.v_korr).pack(side="left", padx=4)
        ttk.Label(kr, text="mm").pack(side="left")
        self.lbl_fokus = ttk.Label(fb, text="", style="Muted.TLabel")
        self.lbl_fokus.grid(row=6, column=0, columnspan=3, sticky="w")
        ttk.Button(fb, text=T("Fokustest starten"), command=self.fokustest
                   ).grid(row=7, column=0, columnspan=3, sticky="ew", pady=4)
        # Eine Liste ohne Ueberschrift ist eine Liste, bei der man raten
        # muss, was darin steht.
        self.lbl_fzliste = ttk.Label(fb, text=T("Striche des letzten Tests"))
        self.lbl_fzliste.grid(row=8, column=0, columnspan=3, sticky="w",
                              pady=(6, 2))
        self.lb_fz = tk.Listbox(fb, height=6, width=28)
        self.lb_fz.grid(row=9, column=0, columnspan=3, sticky="ew")
        ttk.Button(fb, text=T("Gewählten Strich ins Material übernehmen"),
                   command=self.take_focus).grid(row=10, column=0, columnspan=3,
                                                 sticky="ew", pady=4)
        for v in (self.v_dicke, self.v_korr):
            v.trace_add("write", self._fokus_geaendert)
        self._fokus_zeigen()

        mb = ttk.LabelFrame(f, text=T("Materialtest"), padding=6)
        mb.grid(row=1, column=0, sticky="ew", pady=8)
        self.v_mt_s = tk.StringVar(value="200,400,600,830,1000")
        self.v_mt_f = tk.StringVar(value="600,1000")
        self.v_mt_b = tk.DoubleVar(value=80.0)
        self.v_mt_h = tk.DoubleVar(value=40.0)
        self._row(mb, 0, "Leistungen", self.v_mt_s, width=20)
        self._row(mb, 1, "Vorschübe", self.v_mt_f, width=20)
        self._row(mb, 2, "Breite", self.v_mt_b, unit="mm")
        self._row(mb, 3, "Höhe", self.v_mt_h, unit="mm")
        ttk.Button(mb, text=T("Materialtest anlegen"),
                   command=self.materialtest_anlegen).grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=4)
        # Frueher fuhr der Knopf sofort los, ab dem Nullpunkt, mit festen
        # 6-mm-Feldern. Einen Test will man aber auf das Reststueck legen,
        # das man gerade in der Hand hat - deshalb kommt er jetzt als
        # Element auf die Flaeche und laesst sich schieben wie ein Motiv.
        self._erklaerung(ttk.Label(mb, style="Muted.TLabel", wraplength=360,
            text=T("Kommt als Element auf die Fläche - schieb es dorthin,\n"
                   "wo dein Reststück liegt, dann Erzeugen und Start.\n"
                   "Links die Leistung, unten der Vorschub, beide werden\n"
                   "mitgraviert."))).grid(row=5, column=0, columnspan=3,
                                          sticky="w")

        gb = ttk.LabelFrame(f, text=T("Graustufentest"), padding=6)
        gb.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.v_gt_s = tk.StringVar(value="200,400,600,830")
        self.v_gt_f = tk.IntVar(value=1000)
        self.v_gt_n = tk.IntVar(value=6)
        self.v_gt_feld = tk.DoubleVar(value=7.0)
        self._row(gb, 0, "Leistungen", self.v_gt_s, width=20)
        self._row(gb, 1, "Vorschub F", self.v_gt_f)
        self._row(gb, 2, "Stufen", self.v_gt_n)
        self._row(gb, 3, "Feldgröße", self.v_gt_feld, unit="mm")
        self._erklaerung(ttk.Label(gb, text=T("Eine Zeile je Leistung, darin ein Tonwertkeil\n"
                             "von hell nach dunkel. Unten die kleinste\n"
                             "Leistung, links der hellste Ton. Jedes Feld\n"
                             "bekommt genau die Leistung, die eine Gravur\n"
                             "an dieser Stelle auch bekäme."),
                  style="Muted.TLabel")).grid(row=4, column=0, columnspan=3, sticky="w")
        self.lbl_gt = ttk.Label(gb, text="", style="Muted.TLabel")
        self.lbl_gt.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(gb, text=T("Graustufentest starten"), command=self.graustufentest
                   ).grid(row=6, column=0, columnspan=3, sticky="ew", pady=4)
        for v in (self.v_gt_s, self.v_gt_f, self.v_gt_n, self.v_gt_feld):
            v.trace_add("write", lambda *a: self._gt_vorschau())
        self._gt_vorschau()

    # ================================================================ Motiv
    def open_image(self):
        pfade = filedialog.askopenfilenames(
            title=T("Bilder, SVG oder DXF"),
            initialdir=os.path.expanduser("~/Downloads"),
            filetypes=[(T("Bilder, SVG, DXF"),
                        "*.png *.jpg *.jpeg *.webp *.bmp *.svg *.dxf"),
                       (T("alle"), "*")])
        if pfade:
            self.dateien_laden(pfade)

    def dateien_laden(self, pfade, wunsch=None):
        """Mehrere Dateien hintereinander als Elemente laden.

        Ein Werkstueck besteht selten aus einer Datei - fuenf Bagger sind
        fuenf SVGs, und die einzeln zu oeffnen heisst fuenfmal denselben
        Dialog. Sie legen sich von selbst nebeneinander (_platz_daneben).

        Geht eine davon nicht, laeuft der Rest trotzdem durch: fuenf
        Fehlerdialoge hintereinander wegzuklicken hilft niemandem, eine
        Meldung am Ende sagt dasselbe.
        """
        pfade = [p for p in pfade if p]
        if not pfade:
            return 0
        schief = []
        for i, p in enumerate(pfade):
            spur("lade %s" % p)
            if not self.lade_motiv(p, melden=len(pfade) == 1,
                                   wunsch=wunsch if i == 0 else None):
                schief.append(os.path.basename(p))
            spur("fertig mit %s" % os.path.basename(p))
        geladen = len(pfade) - len(schief)
        if len(pfade) > 1:
            self._log(T("{n} von {m} Dateien geladen.").format(
                n=geladen, m=len(pfade)))
        if schief and len(pfade) > 1:
            messagebox.showerror(T("Laden fehlgeschlagen"), T(
                "Diese Dateien gingen nicht:\n\n{liste}").format(
                    liste="\n".join(schief)))
        return geladen

    def lade_motiv(self, p, anzeige=None, fragen=True, melden=True,
                   wunsch=None):
        """Datei einlesen und als Motiv setzen. 'anzeige' ueberschreibt den
        Namen im Fenster - ein Projekt zeigt den urspruenglichen, nicht den
        der ausgepackten Kopie."""
        ext = os.path.splitext(p)[1].lower()
        vec = None
        im = None
        # Eine Schnittvorlage traegt beides: das Motiv als eingebettetes Bild
        # und die Schnittlinien als Pfade. Gerastert wird dann nur das Bild.
        bildlinien = False
        bild_bb = None
        if ext == ".svg":
            try:
                nb, nv = J.svg_anteile(p)
                bildlinien = bool(nb and nv)
                # Eine Vorlage, die noch einmal eingerahmt wurde, traegt die
                # alte komplett als Bild in sich. Deren Rahmen liegt damit
                # ausserhalb jeder Reichweite - weder zu gravieren noch zu
                # schneiden. Besser gesagt als stillschweigend verloren.
                alt = J.svg_innenlinien(p)
                if alt:
                    self._log(T("Diese Vorlage enthält eine ältere als Bild: "
                                "deren {n} Schnittlinie(n) werden weder "
                                "graviert noch geschnitten.").format(n=alt))
            except Exception:
                pass
        try:
            if ext in (".svg", ".dxf"):
                try:
                    vec = V.load_vector(p) or None
                except Exception as e:
                    if ext == ".dxf":
                        raise
                    self._log(T('SVG-Konturen nicht lesbar: {0}').format(e))
            if ext == ".dxf":
                if not vec:
                    raise ValueError(T("keine Konturen in der DXF gefunden"))
                # DXF hat keine Flaechen - Vorschau aus den Konturen zeichnen
                im = V.render_preview(V.flatten(vec, 1.0))
            else:
                roh = J.load_source(p, 3000 if ext == ".svg" else None,
                                    nur_bild=bildlinien)
                kasten = J.inhalt_bb(roh, 245)
                im = roh.crop(kasten) if kasten else roh
                # Der Zuschnitt wirft den weissen Rand weg - und damit die
                # Lage des Motivs im Blatt. Bei einer Schnittvorlage liegen
                # die Schnittlinien aber gerade NEBEN dem Motiv: ohne diesen
                # Merker haette der Rahmen nachher nichts mehr, woran er
                # sich ausrichten koennte, und wuerde auf das Motiv selbst
                # eingepasst - also genau um die Luft dazwischen zu klein.
                if bildlinien and kasten:
                    bild_bb = V.bild_in_blatt(p, roh.size, kasten)
        except Exception as e:
            if melden:
                messagebox.showerror(T("Laden fehlgeschlagen"), str(e))
            self._log(T("{name}: {fehler}").format(
                name=os.path.basename(p), fehler=e))
            return False
        if self.grbl.job_running:
            messagebox.showinfo(T("Motiv"), T("Während eines Jobs nicht möglich."))
            return False
        self._element_sichern()
        self._verwerfen()
        self.src, self.src_path, self.vec = im, p, vec
        self.quelle_pfad = p
        self.vec_bb = V.bbox(V.flatten(vec, 1.0)) if vec else None
        self.bild_bb = bild_bb
        self.vec_voll = vec
        self.ebene = None
        self._vecdreh = self._live_cache = None
        self.bildlinien = bildlinien
        self.src_nurbild = bildlinien
        self.v_nurbild.set(True)
        self._nurbild_zeigen()
        if bildlinien:
            self._log(T("{n} Vektorelemente neben dem eingebetteten Bild - "
                        "graviert wird nur das Bild.").format(n=nv))
        if ext == ".dxf":
            self.v_job.set("schnitt")       # DXF = nur Konturen
        elif bildlinien:
            # Eine Schnittvorlage sagt selbst, was mit ihr geschehen soll:
            # das Bild gravieren, die Pfade drumherum schneiden. Die
            # Betriebsart gilt je Element - wer mehrere Dateien laedt und
            # danach einmal "beides" anklickt, stellt sonst nur die letzte
            # um und wundert sich, dass nur ein Rahmen geschnitten wird.
            self.v_job.set("beides")
        elif not vec and self.v_job.get() in ("schnitt", "beides"):
            self.v_job.set("gravur")
        self.v_rot.set(0)
        self._rot_alt = 0.0
        name = anzeige or os.path.basename(p)
        self.lbl_src.configure(text=T('{0}\n{1} x {2} px').format(
            name, im.width, im.height))
        self.elemente.append({"anzeige": name, "src": im, "vec": vec,
                              "vec_voll": vec, "vec_bb": self.vec_bb,
                              "bild_bb": bild_bb,
                              "pfad": p, "quelle": p})
        self.aktiv = len(self.elemente) - 1
        self._neu_gekoppelt()
        self.fit()                       # setzt Groesse, sichert gleich mit
        self._platz_daneben(wunsch)
        self._element_sichern()
        self._liste_auffrischen()
        self._gen_knopf()
        # fit() hat zuletzt gezeichnet - danach hat _platz_daneben Groesse
        # und Lage nochmal angefasst. Ohne diesen Strich stand das Motiv in
        # der eingepassten Groesse auf dem Schirm, waehrend die Felder schon
        # das Originalmass trugen: es sah zu gross aus, liess sich nicht
        # anfassen (der Griff sucht am richtigen Kasten), und erst ein Klick
        # in Breite oder Hoehe rueckte es zurecht.
        self._draw()
        if vec and fragen:
            self._ebenen_anbieten()
        return True

    # ------------------------------------------- Bild statt Strichzeichnung
    def _nurbild_zeigen(self):
        """Den Schalter nur zeigen, wenn es etwas auszublenden gibt."""
        if not hasattr(self, "chk_nurbild"):
            return
        if getattr(self, "bildlinien", False):
            self.chk_nurbild.pack(anchor="w")
            self.lbl_nurbild.pack(anchor="w")
        else:
            self.chk_nurbild.pack_forget()
            self.lbl_nurbild.pack_forget()

    def _nurbild_anwenden(self):
        """Schalter umgelegt: die Quelle neu rendern.

        Ohne das zeigte die Vorschau weiter das zuletzt gerenderte Bild -
        und der G-Code enthielte die Linien, die gerade abgeschaltet wurden.
        """
        soll = bool(getattr(self, "bildlinien", False) and self.v_nurbild.get())
        if soll == getattr(self, "src_nurbild", False):
            return
        if not (self.src_path and self.src_path.lower().endswith(".svg")):
            return
        try:
            im = J.autocrop(J.load_source(self.src_path, 3000, nur_bild=soll), 245)
        except Exception as e:
            messagebox.showerror(T("Laden fehlgeschlagen"), str(e))
            self.v_nurbild.set(not self.v_nurbild.get())
            return
        self.src, self.src_nurbild = im, soll
        self._vecdreh = self._live_cache = None
        anzeige = self._quellname()
        if 0 <= self.aktiv < len(self.elemente):
            anzeige = self.elemente[self.aktiv].get("anzeige") or anzeige
        self.lbl_src.configure(text=T('{0}\n{1} x {2} px').format(
            anzeige, im.width, im.height))
        self._element_sichern()
        self._draw()

    # ----------------------------------------------------------- Formen
    # Eine gezeichnete Form ist ein ganz normales Element, nur ohne Datei:
    # Konturen im selben Format wie aus einer SVG. Gespeichert werden ihre
    # Parameter, nicht ein eingebettetes Bild - das ist kleiner, exakt und
    # altert nicht.
    def _form_anlegen(self, form, anzeige):
        if self.grbl.job_running:
            messagebox.showinfo(T("Motiv"), T("Während eines Jobs nicht möglich."))
            return False
        try:
            polys = V.form(form)
        except (ValueError, KeyError) as e:
            messagebox.showerror(T("Form"), str(e))
            return False
        self._element_sichern()
        self._verwerfen()
        im = V.render_preview(polys)
        self.src, self.src_path, self.vec = im, None, polys
        self.quelle_pfad = None
        self.vec_bb = V.bbox(polys)
        self.bild_bb = None
        self.vec_voll = polys
        self.ebene = None
        self._vecdreh = self._live_cache = None
        self.v_rot.set(0)
        self._rot_alt = 0.0
        self.v_job.set("schnitt")          # eine Form ist zum Schneiden da
        self.lbl_src.configure(text=anzeige)
        self.elemente.append({"anzeige": anzeige, "src": im, "vec": polys,
                              "vec_voll": polys, "vec_bb": self.vec_bb,
                              "pfad": None, "quelle": None, "form": dict(form)})
        self.aktiv = len(self.elemente) - 1
        self._neu_gekoppelt()
        # 1:1, nicht einpassen: ein Rechteck von 80 x 50 soll 80 x 50 sein.
        self.v_w.set(round(float(form["b"]), 2))
        self.v_h.set(round(float(form["h"]), 2))
        self._element_sichern()
        self._liste_auffrischen()
        self._gen_knopf()
        self._draw()
        return True

    def form_rechteck(self, b, h, radius=0.0):
        return self._form_anlegen({"art": "rechteck", "b": b, "h": h, "r": radius},
                                  T("Rechteck {b:g} × {h:g} mm").format(b=b, h=h))

    def rahmen_um_motiv(self, abstand, radius=0.0):
        """Rechteck um das gewaehlte Element, mit Abstand ringsum."""
        kasten = self._box()
        if kasten is None:
            messagebox.showinfo(T("Rahmen"), T("Erst ein Motiv wählen."))
            return False
        name = self.elemente[self.aktiv]["anzeige"] if self.elemente else ""
        x, y, b, h = kasten
        nb, nh = b + 2 * abstand, h + 2 * abstand
        if nb <= 0 or nh <= 0:
            messagebox.showinfo(T("Rahmen"),
                T("Der Abstand ist so negativ, dass nichts übrig bleibt."))
            return False
        if not self._form_anlegen({"art": "rechteck", "b": nb, "h": nh, "r": radius},
                                  T("Rahmen um {name}").format(name=name)):
            return False
        self._set_box(x - abstand, y - abstand)
        if x - abstand < -0.005 or y - abstand < -0.005:
            self._log(T("Der Rahmen ragt über den Werkstückrand hinaus - "
                        "er wurde an die Kante gesetzt."))
        self._element_sichern()
        self._raender_zeigen()
        self._draw()
        return True

    def _masse_fragen(self, titel, felder):
        """Kleiner Dialog mit Zahlenfeldern. Gibt die Werte oder None.

        Der Dialog haelt den Tk-Griff (grab_set). Solange der liegt, darf
        von hier aus kein zweiter Dialog aufgehen: die Meldungen laufen
        ueber zenity, also einen eigenen Prozess, der dann keine Eingabe
        bekommt - und das ganze Programm steht. Falsche Eingaben werden
        deshalb im Dialog selbst gemeldet, und der Griff wird in jedem
        Fall wieder abgegeben.
        """
        dlg = tk.Toplevel(self.root)
        dlg.title(titel)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        vars_ = {}
        for i, (schluessel, beschriftung, vorgabe) in enumerate(felder):
            ttk.Label(dlg, text=T(beschriftung)).grid(
                row=i, column=0, sticky="w", padx=8, pady=4)
            v = tk.DoubleVar(value=vorgabe)
            vars_[schluessel] = v
            e = ttk.Entry(dlg, textvariable=v, width=8)
            e.grid(row=i, column=1, padx=4, pady=4)
            ttk.Label(dlg, text="mm").grid(row=i, column=2, sticky="w", padx=(0, 8))
            if i == 0:
                e.focus_set()
                e.select_range(0, "end")
        aus = {}
        hinweis = ttk.Label(dlg, text="", style="Muted.TLabel")
        hinweis.grid(row=len(felder), column=0, columnspan=3, sticky="w", padx=8)

        def ok(*_):
            try:
                aus.update({k: float(v.get()) for k, v in vars_.items()})
            except tk.TclError:
                hinweis.configure(text=T("Zahlenfeld ungültig."))
                return
            dlg.destroy()

        kn = ttk.Frame(dlg)
        kn.grid(row=len(felder) + 1, column=0, columnspan=3, sticky="e",
                padx=8, pady=8)
        ttk.Button(kn, text=T("Abbrechen"), command=dlg.destroy).pack(side="right")
        ttk.Button(kn, text=T("OK"), command=ok).pack(side="right", padx=(0, 6))
        dlg.bind("<Return>", ok)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        # Neben das Hauptfenster setzen, nicht irgendwohin: ein Dialog, der
        # hinter dem Fenster oder ausserhalb des Bildschirms aufgeht, sieht
        # aus wie ein Absturz - anklicken laesst sich dann nichts mehr.
        dlg.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width()
                                              - dlg.winfo_reqwidth()) // 2)
        y = self.root.winfo_rooty() + 120
        dlg.geometry("+%d+%d" % (max(0, x), max(0, y)))
        try:
            dlg.grab_set()
            dlg.lift()
            dlg.focus_force()
            self.root.wait_window(dlg)
        finally:
            try:
                dlg.grab_release()
            except tk.TclError:
                pass                      # schon zerstoert - Griff ist weg
        return aus or None

    def form_dialog(self):
        w = self._masse_fragen(T("Rechteck"),
                               [("b", "Breite", 80.0), ("h", "Höhe", 50.0),
                                ("r", "Eckradius", 0.0)])
        if w:
            self.form_rechteck(w["b"], w["h"], w["r"])

    def rahmen_dialog(self):
        if self._box() is None:
            messagebox.showinfo(T("Rahmen"), T("Erst ein Motiv wählen."))
            return
        w = self._masse_fragen(T("Rahmen ums Motiv"),
                               [("a", "Abstand ringsum", 5.0),
                                ("r", "Eckradius", 0.0)])
        if w:
            self.rahmen_um_motiv(w["a"], w["r"])

    def _ebenen_anbieten(self):
        """Mehrfarbige Zeichnung in Ebenen aufteilen.

        Gewohnheit aus anderen Programmen: rot wird geschnitten, der Rest
        graviert. Alle Ebenen behalten Massstab und Lage der ganzen
        Zeichnung, sonst wuerde jede fuer sich eingepasst und sie laegen
        nicht mehr uebereinander.
        """
        e = self.elemente[self.aktiv]
        farben = V.farben(e["vec"])
        if len(farben) < 2:
            return
        if not messagebox.askyesno(T("Farben als Ebenen"),
                T("Die Zeichnung hat {n} Strichfarben.\n\n"
                  "Als getrennte Ebenen laden? Rot wird geschnitten, der Rest "
                  "graviert - die Zuordnung lässt sich danach je Element "
                  "ändern.\n\nGraviert wird dann die Strichzeichnung der "
                  "Ebene, nicht das gefüllte Original.").format(n=len(farben))):
            return
        vorlage = dict(e)
        del self.elemente[self.aktiv]
        alle = e["vec"]
        for farbe, anzahl in farben:
            teil = V.nur_farbe(alle, farbe)
            neu = dict(vorlage)
            neu["vec"] = teil
            neu["vec_voll"] = alle
            neu["src"] = V.render_preview(V.flatten(teil, 1.0), bezug=V.flatten(alle, 1.0))
            neu["anzeige"] = "%s  %s" % (vorlage["anzeige"], farbe)
            neu["ebene"] = farbe
            # Die Ebene zeigt ihre eigene Strichzeichnung, nicht mehr das
            # eingebettete Bild - der gemerkte Platz im Blatt gilt dafuer
            # nicht und wuerde die Ebene gegen sich selbst ausrichten.
            neu["bild_bb"] = None
            neu["v_job"] = "schnitt" if self._ist_rot(farbe) else "gravur"
            neu.pop("_lcache", None)
            neu.pop("ergebnis", None)
            self.elemente.append(neu)
        self.aktiv = len(self.elemente) - 1
        self._element_laden(self.aktiv)
        self._log(T("{n} Ebenen aus {d}: {f}").format(
            n=len(farben), d=vorlage["anzeige"],
            f=", ".join("%s (%d)" % (f, a) for f, a in farben)))

    @staticmethod
    def _ist_rot(farbe):
        try:
            r = int(farbe[1:3], 16); g = int(farbe[3:5], 16); b = int(farbe[5:7], 16)
        except (ValueError, IndexError):
            return False
        return r > 120 and r > g * 2 and r > b * 2

    # --------------------------------------------------------- Elemente
    # Alles, was zu einem einzelnen Motiv gehoert. Werkstueck, Material-
    # dicke und Maschine gelten fuer alle gemeinsam.
    ELEMENTFELDER = (
        "v_w", "v_h", "v_lock", "v_rot", "v_inv", "v_nurbild", "v_mode", "v_schw",
        "v_raster",
        "v_gamma", "v_hell", "v_kontrast", "v_schaerfe",
        "v_xoff", "v_yoff", "v_over", "v_spiegel", "v_achse",
        "v_job", "v_passes", "v_cs", "v_cf",
        "v_s", "v_smin", "v_f", "v_line",
        "v_eigen",
    )

    # Werte, die zum MATERIAL gehoeren und nicht zum Motiv. Ein Werkstueck
    # ist aus einem Stueck Holz: Leistung, Vorschub, Zeilenabstand und
    # Durchgaenge sind fuer alle Motive darauf dieselben. Sie stehen
    # trotzdem je Element, damit ein einzelnes abweichen kann - der Haken
    # "Eigene Werte" nimmt es aus der Gruppe.
    GEMEINSAM = ("v_s", "v_smin", "v_f", "v_line",
                 "v_passes", "v_cs", "v_cf")

    # Die Verfahren der Rasterung: Schluessel fuer Presets und Projekte,
    # Name fuer die Anzeige. Die vier Fehlerdiffusionen heissen nach ihren
    # Erfindern und bleiben in jeder Sprache gleich.
    RASTERNAMEN = (("floyd", "Floyd-Steinberg"), ("atkinson", "Atkinson"),
                   ("jarvis", "Jarvis"), ("stucki", "Stucki"),
                   ("halbton", "Halbton"))

    def _rasterart_gewaehlt(self):
        """Aus dem angezeigten Namen den Schluessel machen."""
        gewaehlt = self.v_rastername.get()
        for schluessel, name in self.RASTERNAMEN:
            if T(name) == gewaehlt:
                self.v_raster.set(schluessel)
                return

    def _rasterart_zeigen(self):
        """Und zurueck - fuer Preset, Projekt und Elementwechsel."""
        if not hasattr(self, "v_rastername"):
            return
        schluessel = self.v_raster.get()
        for s, name in self.RASTERNAMEN:
            if s == schluessel:
                self.v_rastername.set(T(name))
                return
        self.v_rastername.set(T(self.RASTERNAMEN[0][1]))

    def _luft_an(self):
        """Ob dieser Job die Duese einschalten soll."""
        try:
            return bool(self.v_luft.get())
        except (tk.TclError, AttributeError):
            return False

    def _element_sichern(self):
        """Die Eingabefelder in das gerade gewaehlte Element zurueckschreiben."""
        if not (0 <= self.aktiv < len(self.elemente)):
            return
        e = self.elemente[self.aktiv]
        for name in self.ELEMENTFELDER:
            try:
                e[name] = getattr(self, name).get()
            except tk.TclError:
                pass
        e.update(src=self.src, vec=self.vec, vec_bb=self.vec_bb,
                 bild_bb=getattr(self, "bild_bb", None),
                 vec_voll=getattr(self, "vec_voll", None) or self.vec,
                 ebene=getattr(self, "ebene", None),
                 bildlinien=getattr(self, "bildlinien", False),
                 src_nurbild=getattr(self, "src_nurbild", False),
                 pfad=self.src_path, quelle=self.quelle_pfad)

    def _element_laden(self, i, zeichnen=True):
        """Ein Element in die Eingabefelder holen."""
        if not (0 <= i < len(self.elemente)):
            return
        e = self.elemente[i]
        self.aktiv = i
        self.src, self.vec = e["src"], e["vec"]
        self.vec_bb, self.src_path = e["vec_bb"], e["pfad"]
        self.bild_bb = e.get("bild_bb")
        self.vec_voll = e.get("vec_voll") or e["vec"]
        self.ebene = e.get("ebene")
        self.test = e.get("test")
        self.bildlinien = e.get("bildlinien", False)
        self.src_nurbild = e.get("src_nurbild", False)
        self.quelle_pfad = e.get("quelle") or e["pfad"]
        self._vecdreh = self._live_cache = None
        self._still = True
        try:
            for name in self.ELEMENTFELDER:
                if name in e:
                    try:
                        getattr(self, name).set(e[name])
                    except tk.TclError:
                        pass
        finally:
            self._still = False
        # Die Masse dieses Elements gehoeren zu SEINEM Winkel.
        self._rot_alt = float(self.v_rot.get() or 0.0)
        self.lbl_src.configure(text=T('{0}\n{1} x {2} px').format(
            e["anzeige"], e["src"].width, e["src"].height))
        self._bk_zeigen(); self._gamma_zeigen(); self._show_sf()
        self._anlauf_zeigen()
        self._nurbild_zeigen()
        self._liste_auffrischen()
        if zeichnen:
            self._draw()

    @staticmethod
    def _artname(art):
        return {"gravur": T("gravieren"), "schnitt": T("schneiden"),
                "beides": T("beides")}.get(art, "")

    def _liste_auffrischen(self):
        self.lb_el.delete(0, "end")
        for i, e in enumerate(self.elemente):
            art = self._artname(e.get("v_job", "gravur"))
            if e.get("v_eigen"):
                art += ", " + T("eigene Werte")
            self.lb_el.insert("end", "%d. %s  (%s)" % (i + 1, e["anzeige"], art))
        if 0 <= self.aktiv < len(self.elemente):
            self.lb_el.selection_clear(0, "end")
            self.lb_el.selection_set(self.aktiv)
        self._koppel_zeigen()

    def _element_gewaehlt(self, _=None):
        wahl = self.lb_el.curselection()
        if not wahl or wahl[0] == self.aktiv:
            return
        self._element_sichern()
        self._element_laden(wahl[0])

    def element_entfernen(self):
        if not self.elemente or self.grbl.job_running:
            return
        del self.elemente[self.aktiv]
        self._verwerfen()
        if self.elemente:
            self._element_laden(min(self.aktiv, len(self.elemente) - 1))
        else:
            self.aktiv = -1
            self.src = self.src_path = self.vec = self.vec_bb = None
            self.vec_voll = self.bild_bb = None
            self.lbl_src.configure(text="-")
            self._liste_auffrischen()
            self._gen_knopf()
            self._draw()

    def _verwerfen(self):
        """Erzeugten G-Code und alle Vorschauen aller Elemente wegwerfen."""
        self.lines = self.info = self.preview_img = None
        self.preview_pil = self._prev_cache = self.cut_polys = None
        self.preview_pos = None
        for e in self.elemente:
            e.pop("ergebnis", None)
        self.lbl_info.configure(text="")
        self._gen_knopf()

    # --------------------------------------------------------- Projekt
    # Alles, was ein Projekt ausmacht: Variable -> Name in der Datei.
    # Gilt fuer das ganze Projekt, nicht fuer ein einzelnes Element
    PROJEKTFELDER = (
        ("v_bw", "brett_x"), ("v_bh", "brett_y"),
        ("v_board", "brett_zeigen"), ("v_snap", "einrasten"),
        ("v_maxw", "max_breite"), ("v_maxh", "max_hoehe"),
        ("v_dicke", "dicke"), ("v_korr", "fokuskorrektur"),
        ("v_luft", "luft"),
        ("v_notiz", "notiz"),
        ("v_preset", "preset"),
    )

    def save_project(self):
        if not self.elemente:
            messagebox.showinfo(T("Projekt"), T("Erst ein Bild oder SVG öffnen."))
            return
        vor = os.path.splitext(os.path.basename(self.src_path or "projekt"))[0]
        p = filedialog.asksaveasfilename(
            title=T("Projekt speichern"), defaultextension=PR.ENDUNG,
            initialfile=vor + PR.ENDUNG,
            initialdir=os.path.expanduser("~/Downloads"),
            filetypes=[(T("Laserwerk-Projekt"), "*" + PR.ENDUNG), (T("alle"), "*")])
        if not p:
            return
        self._element_sichern()
        werte = {}
        for name, schluessel in self.PROJEKTFELDER:
            try:
                werte[schluessel] = getattr(self, name).get()
            except tk.TclError:
                pass
        werte["gewaehlt"] = self.aktiv
        elemente = [{"anzeige": e["anzeige"],
                     "quelle": e.get("quelle") or e["pfad"],
                     # Gezeichnete Formen haben keine Vorlage, nur Zahlen
                     "form": e.get("form"),
                     "werte": {k: e[k] for k in self.ELEMENTFELDER if k in e}}
                    for e in self.elemente]
        try:
            d = PR.speichern(p, werte, elemente=elemente)
        except OSError as e:
            messagebox.showerror(T("Projekt"), str(e))
            return
        self._projekt_titel(p)
        self._log(T("Projekt gespeichert: {name} ({kb} kB{mit})").format(
            name=os.path.basename(p), kb=os.path.getsize(p) // 1024,
            mit=T(", mit Vorlage") if d.get("vorlage") else ""))

    def open_project(self):
        p = filedialog.askopenfilename(
            title=T("Projekt öffnen"), initialdir=os.path.expanduser("~/Downloads"),
            filetypes=[(T("Laserwerk-Projekt"), "*" + PR.ENDUNG), (T("alle"), "*")])
        if not p:
            return
        try:
            d = PR.laden(p)
        except Exception as e:
            messagebox.showerror(T("Projekt"), str(e))
            return
        ordner = os.path.join(P.DIR, "vorlagen")
        liste = d.get("elemente")
        if liste is None:
            # Projekt aus der Zeit vor der Elementliste: ein einziges Motiv,
            # seine Werte stehen noch unter den Projektwerten.
            alt = {"v_w": "breite", "v_h": "hoehe", "v_lock": "verhaeltnis",
                   "v_rot": "drehung", "v_inv": "invertiert", "v_mode": "modus",
                   "v_schw": "schwelle", "v_gamma": "mitten",
                   "v_hell": "helligkeit", "v_kontrast": "kontrast",
                   "v_schaerfe": "schaerfe", "v_xoff": "versatz_x",
                   "v_yoff": "versatz_y", "v_over": "anlauf",
                   "v_spiegel": "spiegel", "v_achse": "wendeachse",
                   "v_job": "bearbeitung", "v_passes": "durchgaenge",
                   "v_cs": "schnitt_leistung", "v_cf": "schnitt_vorschub",
                   "v_s": "leistung", "v_smin": "leistung_ab",
                   "v_f": "vorschub", "v_line": "zeilenabstand"}
            liste = [{"anzeige": d.get("quelle_name") or "", "quelle": d.get("quelle"),
                      "quelle_name": d.get("quelle_name"), "vorlage": d.get("vorlage"),
                      "werte": {k: d["werte"][s] for k, s in alt.items()
                                if s in d["werte"]}}]
        self.clear_motif()
        for nr, el in enumerate(liste):
            if el.get("form"):
                if not self._form_anlegen(el["form"],
                                          el.get("anzeige") or T("Rechteck")):
                    return
            else:
                quelle, name = PR.vorlage_auspacken(el, ordner, nr)
                if not quelle:
                    messagebox.showerror(T("Projekt"),
                        T("Die Vorlage '{name}' steckt nicht in der Datei und liegt "
                          "nicht mehr am gemerkten Ort.").format(name=name))
                    return
                if not self.lade_motiv(quelle, anzeige=el.get("anzeige") or name,
                                       fragen=False):
                    return
            self._still = True
            try:
                for feld, wert in (el.get("werte") or {}).items():
                    if feld in self.ELEMENTFELDER:
                        try:
                            getattr(self, feld).set(wert)
                        except tk.TclError:
                            pass
            finally:
                self._still = False
            # Der Schalter kam aus der Datei, das Bild ist aber schon
            # gerendert - stimmt beides nicht ueberein, noch einmal.
            self._nurbild_anwenden()
            self._element_sichern()
        for feld, schluessel in self.PROJEKTFELDER:
            if schluessel in d["werte"]:
                try:
                    getattr(self, feld).set(d["werte"][schluessel])
                except tk.TclError:
                    pass
        self._koppelung_pruefen()
        gewaehlt = d["werte"].get("gewaehlt", 0)
        if self.elemente:
            self._element_laden(min(max(0, gewaehlt), len(self.elemente) - 1),
                                zeichnen=False)
        self._gamma_zeigen(); self._show_sf(); self._verwerfen(); self._draw()
        self._projekt_titel(p)
        self._log(T("Projekt geladen: {name} (gespeichert {wann})").format(
            name=os.path.basename(p), wann=d.get("gespeichert", "?")))

    def _projekt_titel(self, pfad):
        self.projekt_pfad = pfad
        self.root.title("Laserwerk" + (" – " + os.path.basename(pfad) if pfad else ""))

    def verwerfen(self):
        """Den Knopf dazu. clear_motif konnte das immer schon, aber aufgerufen
        hat es nur das Laden selbst - eine geladene .nc wurde man dadurch gar
        nicht mehr los, ausser indem man eine andere lud."""
        if self.lines is None and self.src is None and not self.elemente:
            return
        # Ein geladener G-Code ist mit einem Griff wieder da. Gesetzte Motive
        # sind Arbeit - danach wird gefragt.
        if self.elemente and not messagebox.askyesno(
                T("Verwerfen"),
                T("{n} Element(e) und den erzeugten G-Code wegwerfen?").format(
                    n=len(self.elemente))):
            return
        self.clear_motif()
        self._log(T("verworfen"))

    def clear_motif(self):
        """Alle Elemente und den erzeugten G-Code verwerfen."""
        if self.grbl.job_running:
            messagebox.showinfo(T("Motiv"), T("Während eines Jobs nicht möglich."))
            return
        self.elemente = []
        self.aktiv = -1
        self.src = self.src_path = None
        self.vec = self.vec_bb = self.vec_voll = self._vecdreh = None
        self._live_cache = self.bild_bb = None
        self.bildlinien = self.src_nurbild = False
        self._nurbild_zeigen()
        self.drag = None
        self._verwerfen()
        self.lbl_src.configure(text="-")
        if hasattr(self, "lb_el"):
            self._liste_auffrischen()
        self._draw()

    def _quellname(self):
        """Name fuer die Kommentarzeile im G-Code. Eine gezeichnete Form hat
        keine Datei - dann steht dort ihr Name aus der Liste."""
        if self.src_path:
            return os.path.basename(self.src_path)
        if 0 <= self.aktiv < len(self.elemente):
            return self.elemente[self.aktiv].get("anzeige", "")
        return ""

    def _vec_bbox(self):
        """Exakte Ausdehnung der Konturen in mm (aus der Datei, nicht geschätzt)."""
        return self.vec_bb

    def original_size(self):
        """Größe 1:1 aus SVG/DXF übernehmen - für Schablonen."""
        if not self.vec:
            messagebox.showinfo(T("Originalgröße"),
                T("Nur bei SVG und DXF möglich - Pixelbilder haben keine\n"
                  "verlässliche Größe in Millimetern."))
            return
        w, h = self._vec_dreh_bb()               # 1:1 heisst: so, wie gedreht
        self.v_w.set(round(w, 3)); self.v_h.set(round(h, 3))
        self._log(T('Originalgröße 1:1: {0:.3f} x {1:.3f} mm').format(w, h))
        self._stale(); self._draw()

    def _job_changed(self):
        if self.v_job.get() == "gravur" and self.src_path and self.src_path.lower().endswith(".dxf"):
            messagebox.showinfo(T("DXF"), T("DXF-Dateien enthalten nur Konturen.\n"
                                "Zum Nachzeichnen 'Schneiden' mit wenig Leistung nehmen."))
            self.v_job.set("schnitt")
            return
        if self.v_job.get() in ("schnitt", "beides") and not self.vec:
            messagebox.showinfo(T("Schneiden"), T("Schneiden geht nur mit SVG- oder DXF-Dateien,\n"
                                  "weil dafür Konturen nötig sind."))
            self.v_job.set("gravur")
            return
        if self.v_job.get() == "schnitt":
            self._log(T("Schnittmodus: passendes Material-Preset wählen "
                        "(z.B. Papier S500/F600)"))
        # Hier stand fit(): das Umschalten hat die eingetippte Groesse jedes
        # Mal auf das Maximum zurueckgesetzt. Die Masse bleiben jetzt stehen;
        # dass der Schnitt ein anderes Seitenverhaeltnis hat als das
        # gerenderte Bild, rechnet _box() beim Zeichnen heraus.
        # Die Liste gleich mitschreiben: die Betriebsart gilt nur fuer das
        # gewaehlte Element, und das sieht man sonst erst am fehlenden
        # Schnitt im fertigen Job.
        self._element_sichern()
        self._auch_die_anderen()
        self._liste_auffrischen()
        self._stale()
        self._raender_zeigen()
        self._draw()

    def _auch_die_anderen(self):
        """Die Betriebsart auf die anderen Elemente uebertragen, wenn gewollt.

        Sie gilt je Element. Wer mehrere Schnittdateien laedt und danach
        einmal "Schneiden" anklickt, stellt damit nur die zuletzt geladene
        um - die anderen wurden graviert. In der Liste stand es, aber gesehen
        hat man es erst am Werkstueck.
        """
        art = self.v_job.get()
        andere = [e for k, e in enumerate(self.elemente)
                  if k != self.aktiv and e.get("v_job", "gravur") != art]
        # Ohne Konturen laesst sich nicht schneiden - solche Elemente bleiben,
        # wie sie sind, und das sagt das Protokoll. Farbebenen bleiben
        # ebenfalls: bei ihnen ist die Mischung der Zweck, rot schneiden und
        # der Rest gravieren.
        geht = [e for e in andere
                if not e.get("ebene") and (e.get("vec") or art == "gravur")]
        if not geht:
            return
        if not messagebox.askyesno(T("Betriebsart"), T(
                "{n} weitere Element(e) sind anders eingestellt.\n\n"
                "'{art}' auch für sie übernehmen?\n\n"
                "Leistung, Vorschub und Durchgänge gelten dann ebenfalls "
                "für alle - es ist dasselbe Material.").format(
                    n=len(geht), art=self._artname(art))):
            return
        # Dieselbe Betriebsart und dann verschiedene Werte: genau das war der
        # Fall mit den fuenf Baggern. Vier wurden angeritzt, einer
        # geschnitten. Wer hier "ja" sagt, meint denselben Auftrag.
        aktiv = self.elemente[self.aktiv] if 0 <= self.aktiv < len(
            self.elemente) else {}
        werte = {k: aktiv[k] for k in self.GEMEINSAM if k in aktiv}
        for e in geht:
            e["v_job"] = art
            e["v_eigen"] = False
            e.update(werte)
            e.pop("ergebnis", None)
        if len(andere) > len(geht):
            self._log(T("{n} Element(e) ohne Konturen bleiben beim "
                        "Gravieren.").format(n=len(andere) - len(geht)))
        self._log(T("{n} Element(e) auf '{art}' umgestellt.").format(
            n=len(geht), art=self._artname(art)))

    # ------------------------------------------------ Gemeinsame Werte
    # Leistung, Vorschub, Zeilenabstand und Durchgaenge gehoeren zum
    # Material, nicht zum Motiv. Sie stehen je Element, weil ein einzelnes
    # abweichen darf - aber der Normalfall ist ein Werkstueck aus einem
    # Stueck Holz, auf dem alles gleich geschnitten wird. Vorher musste man
    # sie an jedem Element einzeln eintragen, und wer eines vergass, ritzte
    # es nur an.
    def _gruppe(self):
        """Die anderen Elemente mit gemeinsamen Werten."""
        return [e for k, e in enumerate(self.elemente)
                if k != self.aktiv and not e.get("v_eigen")]

    def _werte_koppeln(self, *_):
        """Die Werte des gewaehlten Elements auf die Gruppe uebertragen.

        Haengt an einer Spur auf jedem der Felder: egal, an welchem Element
        man etwas einstellt, die anderen haben es dann auch.
        """
        if getattr(self, "_still", False) or self._am_erzeugen:
            return
        if self.v_eigen.get() or not (0 <= self.aktiv < len(self.elemente)):
            return
        werte = {}
        for name in self.GEMEINSAM:
            try:
                werte[name] = getattr(self, name).get()
            except tk.TclError:
                return            # halb getippte Zahl - beim naechsten Mal
        for e in self._gruppe():
            if all(e.get(k) == v for k, v in werte.items()):
                continue
            e.update(werte)
            e.pop("ergebnis", None)

    def _gruppe_lesen(self):
        """Die Werte der Gruppe in die Felder holen.

        Wer den Haken wegnimmt, will dieselben Werte wie der Rest - nicht
        die abweichenden, die er gerade hatte. Sonst heisst "gemeinsam" nur,
        dass die naechste Aenderung alle anderen ueberschreibt.
        """
        gruppe = self._gruppe()
        if not gruppe:
            return False
        self._still = True
        try:
            for name in self.GEMEINSAM:
                if name in gruppe[0]:
                    try:
                        getattr(self, name).set(gruppe[0][name])
                    except tk.TclError:
                        pass
        finally:
            self._still = False
        self._show_sf()
        return True

    def _eigen_geaendert(self):
        """Haken umgelegt: raus aus der Gruppe oder zurueck hinein."""
        if not (0 <= self.aktiv < len(self.elemente)):
            return
        name = self.elemente[self.aktiv].get("anzeige", "?")
        if self.v_eigen.get():
            self._log(T("'{name}' hat jetzt eigene Werte.").format(name=name))
        else:
            if self._gruppe_lesen():
                self._log(T("'{name}' nimmt wieder die gemeinsamen "
                            "Werte.").format(name=name))
            self._werte_koppeln()
        self._element_sichern()
        self._stale()
        self._liste_auffrischen()

    def _neu_gekoppelt(self):
        """Ein neues Element gehoert zur Gruppe.

        Sonst erbte es Haken und Werte des Elements, das gerade davor
        gewaehlt war - also davon, was man zuletzt angeklickt hat.
        """
        if self.v_eigen.get():
            self.v_eigen.set(False)
        self._gruppe_lesen()

    def _koppelung_pruefen(self):
        """Nach dem Laden: wer von der Gruppe abweicht, bekommt den Haken.

        Projekte aus der Zeit vor den gemeinsamen Werten haben je Element
        eigene Zahlen. Sie stillschweigend als gemeinsam zu fuehren hiesse,
        dass die erste Aenderung irgendwo alle anderen ueberschreibt - mit
        den Werten des Elements, das man zufaellig angeklickt hat.
        """
        offen = [e for e in self.elemente if not e.get("v_eigen")]
        if len(offen) < 2:
            return
        erste = offen[0]
        anders = [e for e in offen[1:]
                  if any(e.get(k) != erste.get(k) for k in self.GEMEINSAM)]
        for e in anders:
            e["v_eigen"] = True
        if anders:
            self._log(T("{n} Element(e) haben abweichende Werte und behalten "
                        "sie - der Haken 'Eigene Werte' sagt, welche.").format(
                            n=len(anders)))

    def _koppel_zeigen(self):
        """Am Material sagen, fuer wie viele Elemente seine Werte gelten."""
        if not hasattr(self, "lbl_gemeinsam"):
            return
        if not self.elemente:
            text = ""
        elif self.v_eigen.get():
            text = T("Nur für dieses Element - im Reiter Motiv steht der "
                     "Haken 'Eigene Werte'.")
        else:
            n = len(self._gruppe()) + 1
            text = (T("Gilt für alle {n} Elemente.").format(n=n) if n > 1
                    else "")
        self.lbl_gemeinsam.configure(text=text)

    def _vec_dreh_bb(self, grad=None):
        """Ausdehnung der GEDREHTEN Konturen. Das gedrehte Rechteck um eine
        Kontur ist meist groesser als das Rechteck um die gedrehte Kontur -
        wer damit rechnet, setzt das Motiv nicht wirklich mittig."""
        if not self.vec:
            return None
        try:
            grad = round(float(self.v_rot.get() if grad is None else grad), 1)
        except tk.TclError:
            grad = 0.0
        if self._vecdreh and self._vecdreh[0] == grad:
            return self._vecdreh[1]
        bezug = getattr(self, "vec_voll", None) or self.vec
        x0, y0, x1, y1 = V.bbox(V.rotate(V.flatten(bezug, 1.0), grad))
        self._vecdreh = (grad, (x1 - x0, y1 - y0))
        return self._vecdreh[1]

    def _dreh_bb(self, w, h, grad=None):
        """Umschliessendes Rechteck nach dem Drehen - fuer jeden Winkel, nicht
        nur fuer Vielfache von 90 Grad."""
        try:
            a = math.radians(float(self.v_rot.get() if grad is None else grad))
        except tk.TclError:
            return w, h
        c, s = abs(math.cos(a)), abs(math.sin(a))
        return w * c + h * s, w * s + h * c

    def _bild_dreh_bb(self, grad):
        """Ausdehnung des gedrehten BILDINHALTS - nicht des gedrehten
        Rechtecks darum.

        Ein rundes Motiv wird beim Drehen nicht groesser. Das Rechteck um
        sein Bild schon, um bis zu 41 Prozent: bei einem 60-mm-Anhaenger
        stand bei 301 Grad ein Kasten von 80 x 78 mm um eine Scheibe von
        56 x 55 mm. Gerechnet wird an einer kleinen Kopie - auf ein
        Zehntel Millimeter genau reicht das, und es kostet nichts.
        """
        if self.src is None:
            return 0.0, 0.0
        grad = round(float(grad or 0.0), 1) % 360
        merker = getattr(self, "_bilddreh", None)
        if merker and merker[0] is self.src and merker[1] == grad:
            return merker[2]
        klein = self.src.convert("L")
        klein.thumbnail((400, 400), Image.NEAREST)
        gedreht = klein.rotate(grad, expand=True, resample=Image.NEAREST,
                               fillcolor=255)
        kasten = gedreht.point(lambda v: 255 if v < 245 else 0).getbbox()
        if kasten and klein.size[0]:
            f = self.src.size[0] / float(klein.size[0])
            masse = ((kasten[2] - kasten[0]) * f, (kasten[3] - kasten[1]) * f)
        else:                        # leeres Bild: dann eben das Rechteck
            masse = self._dreh_bb(*self.src.size, grad=grad)
        self._bilddreh = (self.src, grad, masse)
        return masse

    def _bezug_bb(self, grad=None):
        """Ausdehnung der Vorlage, auf die sich Breite und Hoehe beziehen.

        Beim Schneiden die echte Kontur. Beim Gravieren der Inhalt des
        Bildes - frueher stand hier sein Rechteck, und das waechst beim
        Drehen, auch wenn das Motiv darin rund ist. Eine Zeichnung bringt
        ihre Kontur selbst mit, die ist genauer als jedes gerenderte Bild;
        nur eine Schnittvorlage nicht, denn deren Pfade liegen NEBEN dem
        Motiv, das graviert wird.

        Mit 'grad' auch fuer einen anderen als den eingestellten Winkel:
        nur so laesst sich nach dem Drehen ausrechnen, wie gross das Motiv
        vorher war.
        """
        if self.src is None:
            return 0.0, 0.0
        if self.vec and (self.v_job.get() == "schnitt"
                         or not getattr(self, "bildlinien", False)):
            return self._vec_dreh_bb(grad)
        return self._bild_dreh_bb(self.v_rot.get() if grad is None else grad)

    def _aspect(self):
        """Seitenverhaeltnis der Vorlage, oder None, wenn es keines gibt.

        Eine gerade Linie als SVG hat im Schnittmodus in einer Richtung die
        Ausdehnung null. Das frueher zurueckgegebene 1.0 bzw. 0.0 hat die
        Masse zerstoert: ein Strich wurde zum Quadrat, eine senkrechte Linie
        setzte die Breite auf 0 oder brach mit Division durch null ab.
        """
        w, h = self._bezug_bb()
        return w / h if w > 0 and h > 0 else None

    def _keep_ratio(self, which):
        """Das jeweils andere Mass nachziehen - nur wenn es eines gibt.

        Ohne Seitenverhaeltnis (gerade Linie) bleiben beide Felder so, wie
        sie eingetippt wurden. V.fit skaliert dann ueber die Richtung mit
        Ausdehnung, das andere Mass spielt keine Rolle.
        """
        if not self.v_lock.get() or self.src is None:
            return
        a = self._aspect()
        if a:
            try:
                if which == "w":
                    self.v_h.set(round(self.v_w.get() / a, 2))
                else:
                    self.v_w.set(round(self.v_h.get() * a, 2))
            except tk.TclError:
                pass
        self._stale()
        self._draw()

    def _bk_zeigen(self, *_):
        for name, var in (("Helligkeit", self.v_hell),
                          ("Kontrast", self.v_kontrast),
                          ("Schärfen", self.v_schaerfe)):
            try:
                self.lbl_bk[name].configure(text="%+.0f" % var.get()
                                            if name != "Schärfen"
                                            else "%.0f" % var.get())
            except tk.TclError:
                pass

    def auto_tonwerte(self):
        """Schwarz- und Weisspunkt aus dem Bild holen und als Regler setzen."""
        if self.src is None:
            messagebox.showinfo(T("Bildkorrektur"), T("Erst ein Bild oder SVG öffnen."))
            return
        h, k = J.auto_tonwerte(self.src)
        self.v_hell.set(h)
        self.v_kontrast.set(k)
        self._bk_zeigen()
        self._log(T("Auto-Tonwerte: Helligkeit {h:+.0f}, Kontrast {k:+.0f}").format(
            h=h, k=k))
        self._stale()
        self._draw()

    def bk_zuruecksetzen(self):
        self.v_hell.set(0.0)
        self.v_kontrast.set(0.0)
        self.v_schaerfe.set(0.0)
        self._bk_zeigen()
        self._stale()
        self._draw()

    def _gamma_zeigen(self):
        try:
            g = float(self.v_gamma.get())
        except tk.TclError:
            return
        self.lbl_gamma.configure(text=f"{g:.1f}")

    def _dreh_setzen(self, grad):
        self.v_rot.set(float(grad))
        self._rotated()

    def _rotated(self):
        """Nach dem Drehen: Winkel normieren, Kasten nachziehen.

        Gedreht wird das MOTIV, nicht sein Kasten. Hier stand
        _keep_ratio("w"): die Breite blieb stehen und die Hoehe folgte dem
        neuen Seitenverhaeltnis - aus 90 x 52,5 wurde beim Vierteldreh
        90 x 154, das Motiv wuchs also beim Drehen um zwei Drittel. Will
        aber niemand: man dreht ein Schild, man vergroessert es nicht.

        Der Massstab kommt aus dem Winkel, bei dem die jetzigen Masse
        entstanden sind (_rot_alt). Ihn vorher zu merken hiesse, sich auf
        jeden Weg einzeln zu verlassen - Knopf, Zahlenfeld, Mausgriff,
        Preset, Projekt. So rechnet ihn jeder Weg selbst aus.
        """
        alt = self._box()
        alt_grad = getattr(self, "_rot_alt", 0.0)
        try:                         # 370 -> 10, -5 -> 355
            self.v_rot.set(round(float(self.v_rot.get()) % 360, 1))
        except tk.TclError:
            return
        vorher = self._bezug_bb(alt_grad)[0]
        self._rot_alt = float(self.v_rot.get())
        try:
            skala = float(self.v_w.get()) / vorher if vorher > 0 else None
        except (tk.TclError, ValueError):
            skala = None
        nb, nh = self._bezug_bb()
        if skala and alt and nb > 0 and nh > 0:
            x, y, b, h = alt
            neu_b, neu_h = nb * skala, nh * skala
            self._set_box(x + b / 2 - neu_b / 2, y + h / 2 - neu_h / 2,
                          neu_b, neu_h)
        else:
            self._keep_ratio("w")
        self._raender_zeigen()

    def _gen_knopf(self):
        """Hervorheben, solange kein gueltiger G-Code vorliegt."""
        if not hasattr(self, "btn_gen"):
            return
        fehlt = self.src is not None and self.lines is None
        self.btn_gen.configure(style="Accent.TButton" if fehlt else "TButton")
        self._status_zeigen()

    def _status_zeigen(self):
        """Die eine Zeile, die sagt, woran man gerade ist.

        Maschine, Verbindung, Zustand, Nullpunkt, Z-Referenz - vorher an
        vier Stellen verteilt, zwei davon im Reiter "Maschine", den man
        beim Platzieren gar nicht offen hat.
        """
        if not hasattr(self, "lbl_status"):
            return
        teile = [self._maschine_name() or T("keine Maschine")]
        if self.grbl.connected:
            teile.append(self.grbl.port or T("verbunden"))
            if getattr(self, "zustand", ""):
                teile.append(self.zustand)
            if self.grbl.job_running:
                v, s = getattr(self, "kopf_fs", (0, 0))
                teile.append(T("F{v:.0f}  S{s:.0f}").format(v=v, s=s))
        else:
            teile.append(T("nicht verbunden"))
        teile.append(T("Nullpunkt steht") if self.zero_ok
                     else T("kein Nullpunkt"))
        if self.zref_ok:
            teile.append(T("Z-Referenz steht"))
        self.lbl_status.configure(text="   ·   ".join(teile))
        if hasattr(self, "lbl_prog") and not self._jobtext:
            self.lbl_prog.configure(text=self._naechster_schritt(),
                                    style="Schritt.TLabel")
        if not self.grbl.job_running:
            x, y, z = getattr(self, "kopf_pos", (0.0, 0.0, 0.0))
            self.lbl_marke.configure(
                text=T("X {x}   Y {y}   Z {z}").format(
                    x=Z(x, 2).rjust(8), y=Z(y, 2).rjust(8),
                    z=Z(z, 2).rjust(7)) if self.grbl.connected else "")
        self._knoepfe_zeigen()

    def _erklaerung(self, w):
        """Ein Erklaertext. Gibt das Etikett zurueck, damit der Aufrufer es
        wie bisher gleich setzen kann."""
        self.hilfetexte.append(w)
        return w

    def _hilfe_zeigen(self):
        """Alle Erklaertexte ein- oder ausblenden.

        grid_remove() merkt sich den Platz - beim Einblenden steht alles
        wieder da, wo es war.
        """
        an = bool(self.v_hilfe.get())
        for w in self.hilfetexte:
            try:
                w.grid() if an else w.grid_remove()
            except tk.TclError:
                pass
        self.cfg["hilfetexte"] = an
        P.save_config(self.cfg)

    def _naechster_schritt(self):
        """Was jetzt dran ist - aus dem Zustand, nicht aus einer Liste.

        Die Reiter sagen, WO etwas steht, nicht WANN es dran ist. Wer das
        Programm zum ersten Mal oeffnet, sieht vier Hauptwoerter und keinen
        Weg.
        """
        if self.grbl.job_running:
            return ""
        if not self.elemente:
            return T("→ Motiv öffnen")
        if not self.lines:
            return T("→ G-Code erzeugen")
        if not self.grbl.connected:
            return T("→ Maschine verbinden")
        if not self.zero_ok:
            return T("→ Nullpunkt setzen")
        return T("→ bereit")

    def _knoepfe_zeigen(self):
        """Nur anbieten, was gerade geht.

        Ein Knopf, der immer gleich aussieht und beim Druecken eine Meldung
        zeigt, beschaeftigt nur. Abgeblendet sagt er dasselbe, ohne dass man
        ihn druecken muss.
        """
        if not hasattr(self, "jobknoepfe"):
            return
        verbunden = bool(self.grbl.connected)
        laeuft = bool(self.grbl.job_running)
        pausiert = bool(getattr(self.grbl, "pausiert", False))
        fertig = bool(self.lines)
        an = lambda b: "normal" if b else "disabled"
        self.btn_gen.configure(state=an(bool(self.elemente) and not laeuft))
        self.jobknoepfe["start"].configure(
            state=an(fertig and verbunden and not laeuft))
        self.jobknoepfe["pause"].configure(state=an(laeuft and not pausiert))
        self.jobknoepfe["weiter"].configure(state=an(laeuft and pausiert))
        self.jobknoepfe["stopp"].configure(state=an(verbunden))
        # Der Rahmen faehrt um den fertigen G-Code herum, nicht um die
        # Motivliste - frame() nimmt sich die Ausmasse aus self.lines. Hier
        # stand aber self.elemente, und geladener G-Code leert die Liste:
        # Datei geladen, Start ging, Rahmen blieb abgeblendet. Ausgerechnet
        # bei fremdem G-Code will man vorher sehen, wohin er faehrt.
        self.jobknoepfe["rahmen"].configure(
            state=an(verbunden and not laeuft and fertig))
        self.jobknoepfe["kontur"].configure(
            state=an(verbunden and not laeuft and self._schneidet()))

    def _stale(self):
        """Größe/Drehung geändert: erzeugter G-Code passt nicht mehr.

        Beim Umschalten zwischen Elementen aendern sich die Felder ebenfalls -
        das ist keine Benutzereingabe und darf das Ergebnis nicht verwerfen.
        """
        if getattr(self, "_still", False):
            return
        # Waehrend des Erzeugens aendert das Programm selbst Felder - der
        # Anlauf hebt den Versatz X an. Das darf die schon berechneten
        # Elemente nicht wegwerfen: sonst stand am Ende nur noch das letzte
        # Motiv da, und generate() fiel ueber das fehlende Ergebnis.
        if self._am_erzeugen:
            return
        if self.src is None:
            return
        # Auch die Ergebnisse der einzelnen Elemente wegwerfen: sonst bleibt
        # das erzeugte Vorschaubild an seiner alten Stelle stehen, waehrend
        # der Rahmen schon verschoben ist.
        if self.lines is None and not any("ergebnis" in e for e in self.elemente):
            return
        self._verwerfen()
        self.lbl_info.configure(text=T("Einstellung geändert -\nVorschau neu erzeugen."))
        self._gen_knopf()

    def fit(self):
        if self.src is None:
            return
        a = self._aspect()
        mw, mh = self.v_maxw.get(), self.v_maxh.get()
        if a:
            w, h = mw, mw / a
            if h > mh:
                h, w = mh, mh * a
        else:
            # Gerade Linie: nur die Richtung mit Ausdehnung zaehlt, genau wie
            # V.fit rechnet. Die andere bleibt null statt irgendetwas.
            bw, bh = self._bezug_bb()
            w, h = (mw, 0.0) if bw > 0 else (0.0, mh)
        self.v_w.set(round(w, 2))
        self.v_h.set(round(h, 2))
        self._stale()
        self._draw()

    # ============================================================ Maschinen
    # Zwei Maschinen abwechselnd: Verfahrweg, Beschleunigung, Eilgang,
    # Leistung, Fokuskorrektur, Laufzeitmessungen UND Presets gehoeren zu
    # je einer. config.json und presets.json bleiben der Stand der gerade
    # gewaehlten; maschinen.json legt die anderen daneben.

    def _maschine_name(self):
        return self.cfg.get("maschine") or self.maschinen.get("aktiv") or ""

    def _maschinen_namen(self):
        return sorted(self.maschinen.get("maschinen") or {})

    def _maschine_einrichten(self):
        """Beim ersten Start aus dem vorhandenen Stand eine Maschine machen.

        Wer Laserwerk bisher benutzt hat, hat genau eine - die steht in
        config.json und presets.json. Sie bekommt einen Namen, und ab dann
        laesst sich eine zweite daneben legen.
        """
        if not (self.maschinen.get("maschinen") or {}):
            name = self.cfg.get("maschine") or T("Diodenlaser {w} W").format(
                w=Z(self.cfg.get("watt", J.WATT), 1))
            self.cfg["maschine"] = name
            P.maschine_sichern(self.maschinen, name, self.cfg, self.presets)
            P.save_maschinen(self.maschinen)
            P.save_config(self.cfg)
        elif not self.cfg.get("maschine"):
            self.cfg["maschine"] = self.maschinen.get("aktiv") or ""
        self.root.title("Laserwerk - %s" % self._maschine_name())

    def _maschine_zeigen(self):
        """Die Kennwerte der gewaehlten Maschine unter ihrem Namen.

        Steht da 22 W und 400 x 415, waehrend die kleine angeschlossen ist,
        faellt das auf, bevor das erste Brett brennt.
        """
        if not hasattr(self, "lbl_maschine"):
            return
        self.lbl_maschine.configure(text=T(
            "{x} x {y} mm, {w} W, {b} mm/s², Eilgang {e} mm/min, "
            "{n} Presets").format(
                x=Z(self.cfg["x_max"], 0), y=Z(self.cfg["y_max"], 0),
                w=Z(self._watt(), 1), b=Z(self.cfg.get("accel", J.ACCEL), 0),
                e=Z(self.cfg.get("eilgang", J.EILGANG), 0),
                n=len(self.presets)))
        self.cb_maschine.configure(values=self._maschinen_namen())
        self.v_maschine.set(self._maschine_name())

    def _maschine_sichern(self):
        """Den laufenden Stand in die gewaehlte Maschine zurueckschreiben."""
        name = self._maschine_name()
        if not name:
            return
        P.maschine_sichern(self.maschinen, name, self.cfg, self.presets)
        P.save_maschinen(self.maschinen)

    def maschine_wechseln(self, name, fragen=True):
        """Auf eine andere Maschine umschalten."""
        if name == self._maschine_name():
            return True
        if self.grbl.job_running:
            messagebox.showinfo(T("Maschine"), T("Während eines Jobs nicht möglich."))
            self.v_maschine.set(self._maschine_name())
            return False
        werte, presets = P.maschine_holen(self.maschinen, name)
        if werte is None:
            self.v_maschine.set(self._maschine_name())
            return False
        if fragen and not messagebox.askokcancel(T("Maschine"), T(
                "Auf '{n}' umschalten?\n\n"
                "Verfahrweg, Beschleunigung, Eilgang, Leistung, "
                "Fokuskorrektur, Laufzeitmessungen und die Presets wechseln "
                "mit. "
                "Der Stand von '{a}' wird vorher gesichert.").format(
                    n=name, a=self._maschine_name())):
            self.v_maschine.set(self._maschine_name())
            return False
        self._element_sichern()
        self._maschine_sichern()          # erst die alte festhalten
        self.cfg.update(werte)
        self.cfg["maschine"] = name
        self.presets = presets
        self.maschinen["aktiv"] = name
        P.save_config(self.cfg)
        P.save_presets(self.presets)
        P.save_maschinen(self.maschinen)
        self._maschine_uebernehmen()
        self._log(T("Maschine: {n} ({x:.0f} x {y:.0f} mm, {w:.1f} W)").format(
            n=name, x=float(self.cfg["x_max"]), y=float(self.cfg["y_max"]),
            w=self._watt()))
        return True

    def _maschine_uebernehmen(self):
        """Die Oberflaeche an die gewaehlte Maschine nachziehen.

        Alles, was eine Zahl aus der Konfiguration zeigt oder damit rechnet -
        sonst stehen nach dem Wechsel die Felder der anderen Maschine da.
        """
        J.setze_maschine(self.cfg)
        self.s_max = float(self.cfg.get("s_max", J.S_MAX))
        self.area = max(float(self.cfg["x_max"]), float(self.cfg["y_max"]), 10.0)
        self._still = True
        try:
            self.v_xmax.set(self.cfg["x_max"])
            self.v_ymax.set(self.cfg["y_max"])
            self.v_watt.set(float(self.cfg.get("watt", J.WATT)))
            self.v_zinv.set(bool(self.cfg.get("z_invert", False)))
            self.v_port.set(self.cfg.get("port", ""))
            self.v_dicke.set(float(self.cfg.get("dicke", 12.0)))
            self.v_korr.set(float(self.cfg.get("korrektur", 0.0)))
            # Zeigen heisst an jeder Maschine etwas anderes: dieselbe S/F
            # bringt an 22 W das Vierfache. Also mitziehen, sonst steht im
            # Feld die Zahl der vorigen Maschine.
            self.v_zeig_s.set(J.zeig_s(self._watt()))
        finally:
            self._still = False
        self.cb_preset.configure(values=sorted(self.presets))
        self.v_preset.set("")
        self.root.title("Laserwerk - %s" % self._maschine_name())
        self._flaeche_titel()
        self._anlauf_zeigen()
        self._watt_zeigen()
        self._fokus_zeigen()
        self._maschine_zeigen()
        self._verwerfen()
        self._draw()

    def maschine_anlegen(self):
        """Eine zweite Maschine daneben legen - leer oder aus einer Vorlage."""
        if self.grbl.job_running:
            messagebox.showinfo(T("Maschine"), T("Während eines Jobs nicht möglich."))
            return
        name = self.v_mneu.get().strip()
        if not name:
            messagebox.showinfo(T("Maschine"), T(
                "Erst einen Namen eintragen - oder eine bekannte Maschine "
                "aus der Liste nehmen, die bringt ihre Werte mit."))
            return
        if not name or name in (self.maschinen.get("maschinen") or {}):
            messagebox.showinfo(T("Maschine"),
                                T("Diesen Namen gibt es schon."))
            return
        vorlage = P.VORLAGEN.get(name)
        werte = dict({k: self.cfg[k] for k in P.MASCHINENWERTE if k in self.cfg})
        werte.update(zeitmessungen=[])     # gemessen wird je Maschine
        if vorlage:
            werte.update(vorlage)
        presets = P.kopie(self.presets)
        alt, neu = self._watt(), float(werte.get("watt", self._watt()))
        if abs(alt - neu) > 0.1 and messagebox.askyesno(T("Presets"), T(
                "Die Presets sind an {a:.1f} W gemessen, die neue Maschine "
                "hat {n:.1f} W.\n\nUmrechnen? Übertragbar ist die Energie je "
                "Millimeter, also S mal {f:.2f}. Das ist ein Startpunkt für "
                "einen eigenen Materialtest, kein Rezept - jeder "
                "umgerechnete Wert bekommt den Vermerk.").format(
                    a=alt, n=neu, f=alt / max(0.1, neu))):
            presets = P.maschine_umrechnen(presets, alt, neu)
        self._maschine_sichern()
        P.maschine_sichern(self.maschinen, name,
                           dict(self.cfg, **werte), presets)
        P.save_maschinen(self.maschinen)
        self._log(T("Maschine angelegt: {n}{v}").format(
            n=name, v=T(" (aus der Vorlage)") if vorlage else ""))
        self.v_mneu.set("")
        self.maschine_wechseln(name, fragen=False)

    def _watt(self):
        """Optische Leistung der Maschine - fuer die Energie je Millimeter."""
        try:
            return max(0.1, float(self.cfg.get("watt", J.WATT)))
        except (TypeError, ValueError):
            return J.WATT

    def _schnittwerte_pruefen(self):
        """Schneidende Elemente mit grob verschiedener Energie je Millimeter.

        Leistung, Vorschub und Durchgaenge fuers Schneiden gelten je
        Element, und 0 heisst dort "nimm die Gravurwerte". Wer sie an einem
        Element einstellt und an den anderen nicht, schneidet eines durch
        und ritzt die anderen nur an: S830/F1000 mit einem Durchgang sind
        0,27 J/mm, sechs Durchgaenge S1000/F330 sind 6,0 - der Faktor 22.
        In der Elementliste steht die Betriebsart, die Werte dahinter nicht,
        und zu sehen war der Unterschied erst am Werkstueck.
        """
        liste = []
        for i, e in enumerate(self.elemente):
            if e.get("v_job") not in ("schnitt", "beides"):
                continue
            s = int(e.get("v_cs") or 0) or int(e.get("v_s") or 0)
            f = int(e.get("v_cf") or 0) or int(e.get("v_f") or 0)
            n = max(1, int(e.get("v_passes") or 1))
            if s > 0 and f > 0:
                liste.append((i, J.energie(s, f, n, self._watt()), s, f, n))
        if len(liste) < 2:
            return True
        stark = max(liste, key=lambda d: d[1])
        schwach = min(liste, key=lambda d: d[1])
        if schwach[1] <= 0 or stark[1] / schwach[1] < 2:
            return True
        zeilen = "\n".join(
            T("{n}. {name}: S{s}/F{f} x {p} = {j:.2f} J/mm").format(
                n=i + 1, name=self.elemente[i]["anzeige"][:30],
                s=s, f=f, p=k, j=j)
            for i, j, s, f, k in liste)
        antwort = messagebox.askyesnocancel(T("Schnittwerte"), T(
            "Die Schnittwerte gelten je Element, und sie liegen weit "
            "auseinander:\n\n{zeilen}\n\nWo Leistung oder Vorschub fürs "
            "Schneiden auf 0 stehen, gelten die Gravurwerte - damit wird "
            "die Linie nur angeritzt, nicht geschnitten.\n\n"
            "JA: die stärksten Werte (S{s}/F{f} x {p}) für alle "
            "schneidenden Elemente übernehmen.\n"
            "NEIN: so erzeugen, wie es dasteht.").format(
                zeilen=zeilen, s=stark[2], f=stark[3], p=stark[4]))
        if antwort is None:
            return False
        if antwort:
            for i, _j, _s, _f, _n in liste:
                self.elemente[i].update(v_cs=stark[2], v_cf=stark[3],
                                        v_passes=stark[4], v_eigen=False)
                self.elemente[i].pop("ergebnis", None)
            self._element_laden(self.aktiv, zeichnen=False)
            self._log(T("{n} schneidende Elemente auf S{s}/F{f} x {p} = "
                        "{j:.2f} J/mm umgestellt.").format(
                            n=len(liste), s=stark[2], f=stark[3],
                            p=stark[4], j=stark[1]))
        return True

    LUECKE = 5.0        # mm Luft zwischen zwei Motiven

    @staticmethod
    def _platz_frei(x, y, b, h, belegt):
        """Liegt dieser Kasten auf keinem der anderen?"""
        return all(x + b <= bx or bx + bb <= x or y + h <= by or by + bh <= y
                   for bx, by, bb, bh in belegt)

    def _platz_daneben(self, wunsch=None):
        """Ein neu geladenes Motiv neben die vorhandenen legen statt darauf.

        Jedes neue Element bekam denselben Versatz und wurde auf das
        Hoechstmass eingepasst: fuenf Dateien hintereinander lagen also
        deckungsgleich uebereinander, und wer es nicht merkte, schnitt
        fuenfmal dieselbe Stelle.

        Eine Zeichnung bringt ihr Mass selbst mit - die kommt 1:1 herein,
        und zwar auch als erste: ein Schnitt, der auf den Verfahrweg
        aufgeblasen wird, ist nie gemeint, und der Platz fuer die naechsten
        waere weg. Ein Bild hat kein Mass in Millimetern; es behaelt sein
        eingepasstes und wird nur verkleinert, wenn der Platz sonst nicht
        reicht. Von Hand eingetippte Masse fasst niemand mehr an.

        'wunsch' ist die Stelle, an der die Datei fallen gelassen wurde.
        Dort soll sie auch liegen - aber nicht auf einem anderen Motiv.
        Ist die Stelle besetzt, gilt wieder die Reihe: lieber daneben als
        doppelt auf derselben Stelle geschnitten.
        """
        xm, ym = float(self.cfg["x_max"]), float(self.cfg["y_max"])
        if self.vec:
            bw, bh = self._vec_dreh_bb()
            if 0 < bw <= xm and 0 < bh <= ym:
                self.v_w.set(round(bw, 2))
                self.v_h.set(round(bh, 2))
                if len(self.elemente) < 2:
                    self._log(T("Originalmaß der Zeichnung: {b:.1f} x "
                                "{h:.1f} mm.").format(b=bw, h=bh))
        belegt = [k for k in (self._box_von(e)
                              for i, e in enumerate(self.elemente)
                              if i != self.aktiv) if k]
        try:
            b, h = float(self.v_w.get()), float(self.v_h.get())
        except tk.TclError:
            return
        x0 = self._xmin()
        if wunsch and b <= xm and h <= ym:
            # Die Mitte des Motivs kommt unter den Zeiger, aber nicht ueber
            # den Rand hinaus.
            wx = min(max(x0, wunsch[0] - b / 2), xm - b)
            wy = min(max(0.0, wunsch[1] - h / 2), ym - h)
            if self._platz_frei(wx, wy, b, h, belegt):
                self.v_xoff.set(round(wx, 2))
                self.v_yoff.set(round(wy, 2))
                self._log(T("{n}. Motiv: {b:.1f} x {h:.1f} mm bei X {x:.1f} / "
                            "Y {y:.1f} mm abgelegt.").format(
                                n=self.aktiv + 1, b=b, h=h, x=wx, y=wy))
                return
        if not belegt:
            return                          # das erste Motiv liegt schon gut
        # Erst rechts daneben, in der Reihe des untersten Motivs.
        x = max(xx + bb for xx, _, bb, _ in belegt) + self.LUECKE
        y = min(yy for _, yy, _, _ in belegt)
        if x + b > xm:                      # Reihe voll: eine neue darueber
            x = x0
            y = max(yy + hh for _, yy, _, hh in belegt) + self.LUECKE
        x = max(x0, x)
        if x + b > xm or y + h > ym:
            # Immer noch zu gross: so weit verkleinern, wie der Platz reicht.
            sc = min((xm - x) / b if b > 0 else 1.0,
                     (ym - y) / h if h > 0 else 1.0)
            if sc < 0.25:
                self._log(T("Kein Platz mehr auf der Fläche - das neue Motiv "
                            "liegt auf den anderen. Größe und Versatz von "
                            "Hand setzen."))
                return
            b, h = b * sc, h * sc
            self.v_w.set(round(b, 2))
            self.v_h.set(round(h, 2))
        self.v_xoff.set(round(x, 2))
        self.v_yoff.set(round(y, 2))
        self._log(T("{n}. Motiv: {b:.1f} x {h:.1f} mm bei X {x:.1f} / "
                    "Y {y:.1f} mm abgelegt.").format(
                        n=self.aktiv + 1, b=b, h=h, x=x, y=y))

    def generate(self):
        """G-Code fuer alle Elemente: erst alles Gravieren, dann alles
        Schneiden. Umgekehrt faellt ein Teil heraus, bevor der Rest
        graviert ist."""
        if not self.elemente:
            messagebox.showinfo(T("Kein Motiv"), T("Erst ein Bild oder SVG öffnen."))
            return
        self._element_sichern()
        self._jobtext = ""
        if not self._schnittwerte_pruefen():
            return
        merke = self.aktiv
        gravur, schnitt = [], []
        infos = []
        sekunden = brennweg = 0.0
        self._am_erzeugen = True
        try:
            for i in range(len(self.elemente)):
                self._element_laden(i, zeichnen=False)
                self.lines = self.info = None
                self.preview_pil = self.cut_polys = None
                self.schnitt_ab = None
                self._erzeuge_eines()
                if self.lines is None:
                    return
                self._element_sichern()     # z.B. angehobener Versatz X
                e = self.elemente[i]
                e["ergebnis"] = dict(lines=self.lines, info=self.info,
                                     preview_pil=self.preview_pil,
                                     preview_pos=self.preview_pos,
                                     cut_polys=self.cut_polys,
                                     schnitt_ab=self.schnitt_ab,
                                     text=self.lbl_info.cget("text"))
                infos.append(self.info)
                sekunden += self.info.get("sekunden", 0)
                brennweg += self.info.get("cut_m", 0)
                # "beides" bringt Gravur und Schnitt in einem Stueck mit.
                # Die beiden gehoeren in verschiedene Haelften des Jobs:
                # sonst liegt das erste Teil schon lose im Brett, waehrend
                # das zweite noch graviert wird - es kippt hoch, und der Kopf
                # faehrt darueber.
                ab = self.schnitt_ab
                if ab is not None:
                    gravur.append(self._stueck(i, 0, ab))
                    schnitt.append(self._stueck(i, ab, None))
                elif self.v_job.get() == "schnitt":
                    schnitt.append(self._stueck(i, 0, None))
                else:
                    gravur.append(self._stueck(i, 0, None))
        finally:
            self._am_erzeugen = False
            self._element_laden(merke, zeichnen=False)
        folge = gravur + schnitt
        zeilen, marken = [], []
        for teil, teilmarken, _ in folge:
            if zeilen and zeilen[-1].startswith("G0 X0 Y0"):
                zeilen = zeilen[:-1]        # Rueckfahrt zwischen Teilen sparen
            marken += [(idx + len(zeilen), art, nr, gesamt)
                       for idx, art, nr, gesamt in teilmarken]
            zeilen += teil
        # Die Luft gilt fuer den ganzen Job, nicht je Element: ein M8 davor,
        # ein M9 danach. Die Marken zeigen auf Zeilennummern - sie ruecken
        # mit, sonst stuende die Anzeige den ganzen Job um eine Zeile falsch.
        if self._luft_an():
            zeilen = ["M8"] + zeilen + ["M9"]
            marken = [(k + 1, art, nr, ges) for k, art, nr, ges in marken]
        self.lines = zeilen
        # Die Ausdehnung ist die des ganzen Jobs. Nur die des ersten Elements
        # zu nehmen hiess: ein Motiv rechts ausserhalb des Verfahrwegs kam
        # ohne Warnung durch.
        self.info = dict(infos[0])
        self.info.update(befehle=len(zeilen), sekunden=sekunden, cut_m=brennweg,
                         marken=marken,
                         konturen=sum(i.get("konturen", 0) for i in infos),
                         xmin=min(i["xmin"] for i in infos),
                         xmax=max(i["xmax"] for i in infos),
                         ymin=min(i["ymin"] for i in infos),
                         ymax=max(i["ymax"] for i in infos),
                         breite=max(i["xmax"] for i in infos)
                                - min(i["xmin"] for i in infos),
                         hoehe=max(i["ymax"] for i in infos)
                               - min(i["ymin"] for i in infos))
        if len(self.elemente) > 1:
            # Jedes Element einmal, in der Reihenfolge, in der es zuerst
            # drankommt - ein Teil mit Gravur und Schnitt steckt in zwei
            # Stuecken, soll aber nicht zweimal in der Liste stehen.
            reihe = list(dict.fromkeys(i for _, _, i in folge))
            self.lbl_info.configure(text=T(
                "{n} Elemente\n{b} Befehle, Brennweg {m} m\n"
                "Laufzeit ca. {min} min").format(
                    n=len(self.elemente), b=len(zeilen), m=Z(brennweg, 1),
                    min=Z(self._min(sekunden), 0)) + "\n\n" + "\n\n".join(
                "%d. %s\n%s" % (i + 1, self.elemente[i]["anzeige"],
                                 self.elemente[i]["ergebnis"]["text"])
                for i in reihe))
        self._gen_knopf()
        self._draw()

    def _stueck(self, i, von, bis):
        """Ein Teilstueck aus dem G-Code eines Elements: die Zeilen und die
        Marken darin, wieder ab Null gezaehlt."""
        r = self.elemente[i]["ergebnis"]
        zeilen = r["lines"][von:] if bis is None else r["lines"][von:bis]
        ende = len(r["lines"]) if bis is None else bis
        marken = [(idx - von, art, nr, gesamt)
                  for idx, art, nr, gesamt in r["info"].get("marken", ())
                  if von <= idx < ende]
        return zeilen, marken, i

    def _erzeuge_eines(self):
        if self.test:
            return self._erzeuge_materialtest()
        if self.src is None:
            return
        try:
            w, h, line = self.v_w.get(), self.v_h.get(), self.v_line.get()
            s, f = self.v_s.get(), self.v_f.get()
        except tk.TclError:
            messagebox.showerror(T("Eingabe"), T("Zahlenfeld ungültig."))
            return
        if self.v_job.get() == "schnitt":
            cs, cf = self._schnittwerte()
            return self._generate_cut(w, h, cs, cf)
        if w <= 0 or h <= 0:
            messagebox.showinfo(T("Größe"),
                T("Breite und Höhe müssen größer als 0 sein.\n\n"
                  "Eine gerade Linie hat keine Fläche - die lässt sich "
                  "nur schneiden, nicht gravieren."))
            return
        self.cut_polys = None
        src = self.src
        need = int(w / line * 3)
        if getattr(self, "ebene", None) and self.vec:
            # Nur diese Farbebene neu zeichnen. Die ganze Datei zu rendern
            # wuerde die Schnittlinien mitgravieren - genau das, was die
            # Trennung verhindern soll.
            if need > src.width * 1.2:
                src = V.render_preview(V.flatten(self.vec, 1.0),
                                       px=min(need, 6000),
                                       bezug=V.flatten(self.vec_voll, 1.0))
        elif self.src_path and self.src_path.lower().endswith(".svg"):
            # SVG in passender Aufloesung neu rendern: scharfe Kanten
            if need > src.width * 1.2:
                src = J.autocrop(J.load_source(
                    self.src_path, need,
                    nur_bild=getattr(self, "src_nurbild", False)), 245)
        p = J.prepare(src, w, h, line, invert=self.v_inv.get(),
                      gamma=max(0.2, float(self.v_gamma.get())),
                      helligkeit=self.v_hell.get(),
                      kontrast=self.v_kontrast.get(),
                      schaerfe=self.v_schaerfe.get(),
                      rotate=self.v_rot.get(), mode=self.v_mode.get(),
                      schwelle=self.v_schw.get(), art=self.v_raster.get())
        over = self._anlauf(f)
        xoff = max(0.0, float(self.v_xoff.get()))
        yoff = max(0.0, float(self.v_yoff.get()))
        # Der Anlauf liegt links vom Motiv. Passt er nicht zwischen Nullpunkt
        # und Motiv, muesste der Kopf ins Negative - deshalb das Motiv
        # nachruecken statt einen Job zu erzeugen, der nicht laufen kann.
        if xoff < over - 0.001:
            self._log(T("Versatz X von {alt:.1f} auf {neu:.1f} mm angehoben - "
                        "sonst passt der Anlauf nicht vor den Nullpunkt.").format(
                            alt=xoff, neu=over))
            xoff = over
            self.v_xoff.set(round(over, 2))
        # Rueckseite: Bild spiegeln UND an der Wendeachse gegenueber platzieren
        sp, achse = self.v_spiegel.get(), float(self.v_achse.get())
        bw, bh = p.shape[1] * line, p.shape[0] * line
        if sp == "x":
            p = p[:, ::-1]
            xoff = 2 * achse - xoff - bw
        elif sp == "y":
            p = p[::-1, :]
            yoff = 2 * achse - yoff - bh
        if xoff < 0 or yoff < 0:
            messagebox.showerror(T("Rückseite"),
                T("Gespiegelt landet das Motiv bei X {x:.1f} / Y {y:.1f} mm,\n"
                  "also links bzw. unter dem Nullpunkt.\n\n"
                  "Wendeachse groesser waehlen oder Nullpunkt weiter links "
                  "setzen.").format(x=xoff, y=yoff))
            return
        self.lines, self.info = J.raster_gcode(
            p, line, self._s(s), f,
            s_min=self._s(self._s_unten(s)) if self.v_mode.get() == "grau" else 0,
            overscan=over, x_off=xoff, y_off=yoff,
            kommentar=self._quellname()
                      + ("  RUECKSEITE" if sp != "nein" else ""))
        self.preview_pil = J.preview_image(p)
        self.preview_img = None
        self.preview_pos = (xoff, yoff + self.info["hoehe"])
        # Die Y-Grenzen kennt nur der Aufrufer: raster_gcode rechnet in
        # Zeilen, der Versatz kommt von hier.
        self.info["ymin"] = yoff
        self.info["ymax"] = yoff + self.info["hoehe"]
        i = self.info
        warn = ""
        if i["xmax"] > self.cfg["x_max"] or h > self.cfg["y_max"]:
            warn = T("\nACHTUNG: größer als der Verfahrweg!")
        self.lbl_info.configure(text=(
            (T("RÜCKSEITE gespiegelt an {achse} = {mm} mm\n").format(
                achse="X" if sp == "x" else "Y",
                mm=Z(achse, 1)) if sp != "nein" else "")
            + T("Motiv {b} x {h} mm\n"
                "X {x0} .. {x1} mm (mit Overscan)\n"
                "{n} Befehle, Brennweg {m} m\n"
                "Laufzeit ca. {min} min\n"
                "S{s}/F{f} = {j} J/mm{warn}").format(
                b=Z(i["breite"], 1), h=Z(i["hoehe"], 1),
                x0=Z(i["xmin"], 1), x1=Z(i["xmax"], 1),
                n=i["befehle"], m=Z(i["cut_m"], 1),
                min=Z(self._min(i["sekunden"]), 0),
                s=s, f=f, j=Z(J.energie(s, f, 1, self._watt()), 2),
                warn=warn)))
        # Der Schnitt haengt sich erst hier an - vorher wuerde die Gravur
        # seinen Text mit ihrem eigenen ueberschreiben. Genau einmal: stand
        # der Aufruf auch noch vor der Beschriftung, lag der Schnitt zweimal
        # im Job und fuhr seine Durchgaenge ein zweites Mal ab - ueber Teile,
        # die da schon lose im Brett lagen.
        if self.v_job.get() == "beides" and not self._schnitt_anhaengen(w, h):
            return
        self._gen_knopf()
        self._draw()


    def materialtest_anlegen(self):
        """Ein Materialtest-Element anlegen - schiebbar wie ein Motiv."""
        try:
            ss = [int(v) for v in self.v_mt_s.get().replace(";", ",").split(",")
                  if v.strip()]
            ff = [int(v) for v in self.v_mt_f.get().replace(";", ",").split(",")
                  if v.strip()]
            b, h = float(self.v_mt_b.get()), float(self.v_mt_h.get())
        except (tk.TclError, ValueError):
            messagebox.showerror(T("Materialtest"),
                                 T("Leistungen und Vorschübe als Zahlen, "
                                   "durch Komma getrennt."))
            return
        if len(ss) < 2 or len(ff) < 2 or b <= 0 or h <= 0:
            messagebox.showinfo(T("Materialtest"), T(
                "Mindestens zwei Leistungen und zwei Vorschübe, und eine "
                "Größe über null."))
            return
        test = {"ss": ss, "ff": ff, "zeile": float(self.v_line.get() or 0.1)}
        self._element_sichern()
        e = {"anzeige": T("Materialtest {a}x{b}").format(a=len(ss), b=len(ff)),
             "src": MT.vorschau(ss, ff, b, h, self.s_max),
             "vec": None, "vec_bb": None, "pfad": None, "quelle": None,
             "test": test, "v_w": b, "v_h": h, "v_lock": False,
             "v_job": "gravur", "v_eigen": True}
        self.elemente.append(e)
        self.aktiv = len(self.elemente) - 1
        self._element_laden(self.aktiv, zeichnen=False)
        self._platz_daneben()
        self._element_sichern()
        self._liste_auffrischen()
        self._gen_knopf()
        self._draw()
        self._log(T("Materialtest angelegt: {n} Felder, {b:.0f} x {h:.0f} mm")
                  .format(n=len(ss) * len(ff), b=b, h=h))

    def _erzeuge_materialtest(self):
        """Das Testraster dort erzeugen, wo das Element gerade liegt.

        Ein Materialtest mit festen Koordinaten in einer Datei ist das
        Gegenteil von brauchbar: man will ihn auf dem Reststueck
        hinschieben, das man gerade in der Hand hat. Deshalb ist er ein
        Element wie jedes andere - Groesse und Versatz kommen aus den
        Feldern, die Werte je Feld aus dem Parametersatz.
        """
        try:
            w, h = self.v_w.get(), self.v_h.get()
            x, y = self.v_xoff.get(), self.v_yoff.get()
        except tk.TclError:
            messagebox.showerror(T("Eingabe"), T("Zahlenfeld ungültig."))
            return
        d = self.test
        g, info = MT.gitter(d["ss"], d["ff"], x, y, w, h,
                            zeile=d.get("zeile", 0.1), smax=self.s_max,
                            schrift_s=self._s(self._test_schrift_s()))
        if g is None:
            messagebox.showinfo(T("Materialtest"), T(
                "So klein geht das Raster nicht auf - zieh es größer."))
            return
        self.cut_polys = self.schnitt_ab = None
        self.lines, self.info = g, info
        self.preview_pil = MT.vorschau(d["ss"], d["ff"], w, h, self.s_max)
        self.preview_pos = (x, y + h)
        self.lbl_info.configure(text=T(
            "Materialtest {n} Felder zu {b:.1f} x {h:.1f} mm\n"
            "S {s}\nF {f}\nca. {min:.0f} min").format(
                n=info["felder"], b=info["feld_b"], h=info["feld_h"],
                s=", ".join(str(v) for v in d["ss"]),
                f=", ".join(str(v) for v in d["ff"]),
                min=max(1, self._min(info["sekunden"]))))
        return

    def _test_schrift_s(self):
        """Leistung fuer die Beschriftung: sichtbar, nicht tief.

        Ein fester Anteil der Skala taugt nicht - an 22 W waeren 5 %
        nur 0,011 J/mm und auf Holz nicht zu sehen. Gerechnet wird aus
        einer Zielenergie, dann stimmt es an jeder Maschine.
        """
        f = max(self.test["ff"])
        return max(1, min(1000, int(round(
            MT.SCHRIFT_J * J.S_MAX * (f / 60.0) / max(0.1, self._watt())))))
    def _schnitt_polys(self, w, h, melden=True):
        """Konturen an ihrer endgueltigen Stelle - fuer das Schneiden und
        fuer das Abfahren mit schwachem Strahl."""
        if not self.vec:
            if melden:
                messagebox.showinfo(T("Schneiden"),
                                    T("Keine Konturen - bitte ein SVG oder DXF öffnen."))
            return None
        bw, bh = self._vec_dreh_bb()
        sc = min(w / bw if bw else 1e9, h / bh if bh else 1e9)
        bezug = getattr(self, "vec_voll", None) or self.vec
        polys = V.rotate(V.flatten(self.vec, sc), self.v_rot.get())
        bb = getattr(self, "bild_bb", None)
        if bb and self.v_job.get() != "schnitt":
            # Schnittvorlage: Breite und Hoehe gelten fuer die Gravur, also
            # richtet sich der Schnitt an ihr aus und nicht an sich selbst.
            # Sonst zieht V.fit seinen Kasten auf den der Gravur zusammen -
            # und genau die Luft zwischen Zeichnung und Schnittlinie, wegen
            # der man beides in eine Datei legt, verschwindet dabei.
            ganz = V.rotate([{"pts": [(bb[0], bb[1]), (bb[2], bb[1]),
                                      (bb[2], bb[3]), (bb[0], bb[3])],
                              "closed": True}], self.v_rot.get())
        else:
            ganz = V.rotate(V.flatten(bezug, sc), self.v_rot.get())
        xoff = max(0.0, float(self.v_xoff.get()))
        yoff = max(0.0, float(self.v_yoff.get()))
        polys, _ = V.fit(polys, w, h, xoff, yoff, bezug=ganz,
                         verzerren=not self.v_lock.get())
        sp, achse = self.v_spiegel.get(), float(self.v_achse.get())
        if sp != "nein":
            polys = V.mirror(polys, sp, achse)
            x0, y0, x1, y1 = V.bbox(polys)
            if x0 < 0 or y0 < 0:
                if melden:
                    messagebox.showerror(T("Rückseite"),
                        T("Gespiegelt beginnt der Schnitt bei X {x:.1f} / Y {y:.1f} mm.\n"
                          "Wendeachse groesser waehlen.").format(x=x0, y=y0))
                return None
        # Der Schnitt laeuft um die Gravur herum und braucht deshalb vor ihr
        # Platz. Ohne Versatz liegt er im Negativen - der Kopf faehrt dann
        # gegen den Anschlag, statt zu schneiden.
        x0, y0, _, _ = V.bbox(polys)
        if x0 < -0.001 or y0 < -0.001:
            if melden:
                messagebox.showerror(T("Schneiden"), T(
                    "Der Schnitt beginnt bei X {x:.1f} / Y {y:.1f} mm und "
                    "liegt damit vor dem Nullpunkt.\n\n"
                    "Er umschliesst die Gravur und braucht ringsum Platz: "
                    "Versatz X mindestens {nx:.1f} mm, Versatz Y mindestens "
                    "{ny:.1f} mm.").format(x=x0, y=y0, nx=xoff - min(0.0, x0),
                                           ny=yoff - min(0.0, y0)))
            return None
        return V.order(polys)

    def _doppelte_melden(self, ci):
        """Sagen, wenn die Zeichnung Schnittlinien doppelt fuehrt.

        Stillschweigend die Haelfte wegzulassen waere unheimlich: wer die
        Schnittzeit kennt, soll wissen, warum sie sich halbiert hat. Und
        wer sein SVG kennt, erfaehrt hier, dass darin Striche als duenne
        Flaechen liegen.
        """
        mm = ci.get("doppelt_mm") or 0.0
        if mm < 1.0:
            return
        gesamt = ci.get("cut_m", 0.0) * 1000 + mm
        self._log(T("{m:.2f} m doppelt gezeichnete Schnittlinie übersprungen "
                    "({p:.0f} % der Strecke) - sonst wäre jede zweimal "
                    "gefahren.").format(m=mm / 1000,
                                        p=100 * mm / gesamt if gesamt else 0))

    def _schnitt_anhaengen(self, w, h):
        """An die fertige Gravur den Schnitt haengen - in dieser Reihenfolge,
        sonst faellt das Teil heraus, bevor es graviert ist."""
        polys = self._schnitt_polys(w, h)
        if polys is None:
            self.lines = self.info = None
            return False
        cs, cf = self._schnittwerte()
        passes = max(1, self.v_passes.get())
        g, ci = V.cut_gcode(polys, self._s(cs), cf, passes,
                            kommentar=self._quellname())
        self._doppelte_melden(ci)
        # Die Rueckfahrt am Ende der Gravur faellt weg, der Schnitt faengt
        # ohnehin mit einer eigenen Anfahrt an.
        if self.lines and self.lines[-1].startswith("G0 X0 Y0"):
            self.lines = self.lines[:-1]
        self.lines = self.lines + g
        i = self.info
        # Die Konturmarken zaehlen in ihrem eigenen G-Code ab Null und muessen
        # hinter die Gravur geschoben werden. Ohne sie bleibt die Anzeige den
        # ganzen Schnitt ueber auf der letzten Gravurzeile stehen, "Kontur n
        # von m" kommt nie, und der Waechter sieht den Schnitt nicht anlaufen.
        versatz = len(self.lines) - len(g)
        marken = list(i.get("marken") or [])
        marken += [(k + versatz, art, nr, ges) for k, art, nr, ges in ci["marken"]]
        self.info = dict(i)
        self.info.update(
            befehle=len(self.lines),
            cut_m=i["cut_m"] + ci["cut_m"],
            sekunden=i["sekunden"] + ci["sekunden"],
            xmin=min(i["xmin"], ci["xmin"]),
            xmax=max(i["xmax"], ci["xmax"]),
            ymin=min(i.get("ymin", ci["ymin"]), ci["ymin"]),
            ymax=max(i.get("ymax", ci["ymax"]), ci["ymax"]),
            marken=marken,
            konturen=ci["konturen"], schnitt_m=ci["cut_m"],
            schnitt_sekunden=ci["sekunden"])
        self.cut_polys = polys
        # Die Naht merken: bei mehreren Elementen muss der Job die Schnitte
        # aller Teile hinter alle Gravuren ziehen, und dafuer muss er wissen,
        # wo in diesen Zeilen die Gravur aufhoert.
        self.schnitt_ab = versatz
        self.lbl_info.configure(text=self.lbl_info.cget("text") + T(
            "\n\nDazu Schnitt: {k} Konturen, {m} m x {p}\n"
            "S{s}/F{f} x {p} = {j} J/mm, ca. {min} min").format(
                k=ci["konturen"], m=Z(ci["cut_m"], 2), p=passes, s=cs, f=cf,
                j=Z(J.energie(cs, cf, passes, self._watt()), 2),
                min=Z(max(1, self._min(ci["sekunden"])), 0)))
        # Frueher stand die Gravur schon mit dem Schnitt zusammen in info,
        # als die Warnung geschrieben wurde. Jetzt kommt der Schnitt spaeter -
        # also hier noch einmal nachsehen, ob er ueber den Verfahrweg laeuft.
        # Auch nach oben: der Schnitt umschliesst die Gravur und steht
        # deshalb ueber sie hinaus.
        if (self.info["xmax"] > self.cfg["x_max"]
                or ci["ymax"] > self.cfg["y_max"]):
            self.lbl_info.configure(text=self.lbl_info.cget("text")
                                    + T("\nACHTUNG: größer als der Verfahrweg!"))
        return True

    def _generate_cut(self, w, h, s, f):
        polys = self._schnitt_polys(w, h)
        if polys is None:
            return
        sp = self.v_spiegel.get()
        passes = max(1, self.v_passes.get())
        self.lines, self.info = V.cut_gcode(polys, self._s(s), f, passes,
                                            kommentar=self._quellname())
        self._doppelte_melden(self.info)
        self.cut_polys = polys
        self.preview_img = None
        self._gen_knopf()
        i = self.info
        warn = T("\nACHTUNG: größer als der Verfahrweg!") if (
            i["xmax"] > self.cfg["x_max"] or i["hoehe"] > self.cfg["y_max"]) else ""
        self.lbl_info.configure(text=(
            (T("RÜCKSEITE gespiegelt\n") if sp != "nein" else "")
            + T("Schnitt {b} x {h} mm\n"
                "{k} Konturen, innen vor außen\n"
                "Schnittlänge {m} m x {p} Durchgang/-gänge\n"
                "Laufzeit ca. {min} min\n"
                "S{s}/F{f} x {p} = {j} J/mm{warn}").format(
                b=Z(i["breite"], 1), h=Z(i["hoehe"], 1), k=i["konturen"],
                m=Z(i["cut_m"], 2), p=passes,
                min=Z(max(1, self._min(i["sekunden"])), 0),
                s=s, f=f, j=Z(J.energie(s, f, passes, self._watt()), 2),
                warn=warn)))
        self._draw()

    def save_gcode(self):
        if not self.lines:
            return
        base = os.path.splitext(os.path.basename(self.src_path or "motiv"))[0]
        p = filedialog.asksaveasfilename(defaultextension=".nc",
                                         initialfile=base + ".nc",
                                         initialdir=os.path.expanduser("~/Downloads"))
        if p:
            with open(p, "w") as fh:
                fh.write("\n".join(self.lines) + "\n")

    def load_gcode(self):
        p = filedialog.askopenfilename(initialdir=os.path.expanduser("~/Downloads"),
                                       filetypes=[("G-Code", "*.nc *.gcode *.gc *.ngc"),
                                                  (T("alle"), "*")])
        if not p:
            return
        self.clear_motif()
        with open(p) as f:
            self.lines = [l for l in (x.split(";")[0].strip() for x in f) if l]
        png, (x0, y0, x1, y1), info = J.gcode_preview(self.lines, (CANVAS - 20) / self.area)
        if info is None:
            messagebox.showerror(T("G-Code"), T("Keine Fahrbewegungen in der Datei gefunden."))
            self.lines = None
            return
        self.info = info
        import io
        from PIL import Image as _I
        self.preview_pil = _I.open(io.BytesIO(png)).convert("L")
        self.preview_img = None
        self.preview_pos = (x0, y1)          # linke obere Ecke in mm
        self.src_path = p
        self._gen_knopf()
        m3 = any(l.upper().startswith("M3") for l in self.lines)
        # G91 = relative Fahrten. Dann haengt alles davon ab, wo der Kopf
        # beim Start steht - bei unseren eigenen Dateien nie der Fall.
        rel = any(re.match(r"\s*G0*91\b", l.upper()) for l in self.lines)
        zb = J.z_extent(self.lines)
        neg = x0 < -0.01 or y0 < -0.01
        self.lbl_info.configure(text=(
            T("{datei}\n"
              "X {x0:.1f} .. {x1:.1f}   Y {y0:.1f} .. {y1:.1f} mm\n"
              "{n} Befehle, Brennweg {m:.1f} m\n"
              "Laufzeit ca. {min:.0f} min").format(
                datei=os.path.basename(p), x0=x0, x1=x1, y0=y0, y1=y1,
                n=info["befehle"], m=info["cut_m"],
                min=max(1, self._min(info["sekunden"])))
            + (T("\nHinweis: nutzt M3 - bei Pause brennt der\nLaser weiter!")
               if m3 else "")
            + (T("\nHinweis: negative Koordinaten - Nullpunkt\n"
                 "liegt nicht links unten!") if neg else "")
            + (T("\nHinweis: nutzt G91 - die Datei fährt relativ!\n"
                 "Erst auf den Startpunkt fahren.") if rel else "")
            + (T("\nZ von {u:.2f} bis {o:.2f} mm").format(u=zb[0], o=zb[1])
               if zb else "")))
        self._draw()

    # ================================================================ Material
    def load_preset(self):
        d = self.presets.get(self.v_preset.get())
        if not d:
            return
        # Die Fokuskorrektur steht nicht mehr im Preset: sie sagt, wo die
        # Brennebene zur Z-Referenz liegt, und das ist eine Eigenschaft der
        # Maschine. In jedem Preset mitzulaufen hiess, dass jedes alte Preset
        # eine veraltete Zahl mitschleppt - geladen hat eines davon die
        # frisch gemessene Korrektur ueberschrieben. Aeltere Presets haben
        # den Schluessel noch; er wird nicht mehr gelesen.
        self.v_dicke.set(d.get("dicke", self.v_dicke.get()))
        self.v_s.set(d.get("s", 830)); self.v_f.set(d.get("f", 1000))
        self.v_smin.set(d.get("smin", 0))
        self.v_line.set(d.get("line", 0.1)); self.v_notiz.set(d.get("notiz", ""))
        self.v_mode.set(d.get("mode", "schwelle")); self.v_schw.set(d.get("schwelle", 0.5))
        self.v_raster.set(d.get("rasterart", "floyd"))
        self.v_luft.set(bool(d.get("luft", False)))
        self.v_gamma.set(d.get("gamma", 1.0)); self._gamma_zeigen()
        # Aeltere Presets haben keine Schnittwerte. 0 heisst "nimm die vom
        # Material", 1 Durchgang - genau das Verhalten von vorher.
        self.v_cs.set(d.get("schnitt_s", 0)); self.v_cf.set(d.get("schnitt_f", 0))
        self.v_passes.set(d.get("durchgaenge", 1))
        self.v_pname.set(self.v_preset.get())
        self._save_cfg()           # die Dicke ueberlebt den Neustart

    def _anlauf(self, feed=None):
        """Wirksamer Anlauf: eingestellt, oder 0 = aus der Maschine gerechnet."""
        try:
            gesetzt = float(self.v_over.get())
        except tk.TclError:
            gesetzt = 0.0
        return gesetzt if gesetzt > 0 else self._anlauf_noetig(feed)

    def _anlauf_noetig(self, feed=None):
        """Wie lang der Anlauf sein muss, damit die Achse auf Tempo ist.

        Im Lasermodus skaliert M4 die Leistung mit der Geschwindigkeit.
        Faengt die Zeile zu frueh an, brennt ihr Anfang zu schwach - und
        im Werkstueck steht etwas anderes als in der Vorschau.
        """
        if feed is None:
            feed = float(self.v_f.get()) if self._zahl(self.v_f) else 1000.0
        noetig = J.anlauf_noetig(feed, self.cfg.get("accel", 30.0))
        return round(min(noetig * 1.1 + 0.2, 25.0), 1)      # etwas Luft

    def _anlauf_zeigen(self, *_):
        if not hasattr(self, "lbl_anlauf"):
            return
        noetig = self._anlauf_noetig()
        text = T("nötig bei F{f:.0f}: {n:.1f} mm").format(
            f=float(self.v_f.get()) if self._zahl(self.v_f) else 1000.0, n=noetig)
        if self._anlauf() + 0.05 < noetig:
            text += T("  - eingestellt zu kurz!")
        self.lbl_anlauf.configure(text=text)

    @staticmethod
    def _zahl(var):
        try:
            float(var.get())
            return True
        except tk.TclError:
            return False

    def _schneidet(self):
        """Wird irgendwo geschnitten? Dann beim Start vor Brandgefahr warnen."""
        return any(e.get("v_job") in ("schnitt", "beides") for e in self.elemente)

    def _schnittwerte(self):
        """Leistung und Vorschub fuers Schneiden - eigene oder die vom Material."""
        try:
            s = int(self.v_cs.get())
            f = int(self.v_cf.get())
        except tk.TclError:
            s = f = 0
        return (s if s > 0 else int(self.v_s.get()),
                f if f > 0 else int(self.v_f.get()))

    def _s_unten(self, s_max):
        """Kleinste Leistung fuer Graustufen: eingestellt, sonst 30 % von S.

        Bei Material mit scharfer Schwelle (Buche) liegen Zeichnen und
        Verkohlen eng beieinander. Dann muss die Tonskala genau in dieses
        Fenster gelegt werden, sonst ist die helle Haelfte unsichtbar und
        die dunkle einheitlich schwarz.
        """
        try:
            unten = int(self.v_smin.get())
        except tk.TclError:
            unten = 0
        if unten <= 0:
            return s_max * 0.3
        return min(unten, max(0, s_max - 1))

    def _show_sf(self):
        try:
            s = self.v_s.get()
            self.lbl_sf.configure(text=T("S/F = {sf:.2f}   (Holz bewährt: 0,83)"
                                         "\nGraustufen: S{u:.0f} .. S{o:.0f}").format(
                sf=s / self.v_f.get(), u=self._s_unten(s), o=s))
        except (tk.TclError, ZeroDivisionError):
            pass
        self._watt_zeigen()

    # --------------------------------------------------- Laufzeit
    def _zeitfaktor(self):
        """Was die letzten Laeufe zum Modell gesagt haben, als Median.

        Eins, solange es nichts zu sagen gibt. Ein einzelner Lauf aendert
        nichts - genau so ist der alte Faktor 0,80 entstanden, aus einem
        Graustufenlauf im September, und hat danach jede Strichgrafik um
        ein Viertel zu kurz geschaetzt.
        """
        werte = sorted(self.cfg.get("zeitmessungen") or ())
        if len(werte) < 3:
            return 1.0
        return float(werte[len(werte) // 2])

    def _min(self, sekunden):
        """Angesagte Minuten: Modell mal gemessener Faktor."""
        return (sekunden or 0.0) * self._zeitfaktor() / 60.0

    def _zeit_merken(self, echt, roh):
        """Was angesagt war gegen das, was es gedauert hat.

        Ohne diesen Vergleich steht die Schaetzung nur da und niemand
        erfaehrt, ob sie stimmt - bis einem ein Job eine Viertelstunde
        davonlaeuft.
        """
        if roh < 120 or echt < 120:
            return                      # zu kurz, um daraus etwas zu lernen
        gesagt = max(1.0, self._min(roh) * 60.0)   # mit dem bisherigen Faktor
        self._log(T("Laufzeit: {g:.0f} min angesagt, {e:.0f} min gebraucht "
                    "({a:+.0f} %)").format(g=gesagt / 60, e=echt / 60,
                                           a=(echt / gesagt - 1) * 100))
        # Gemerkt wird immer das Verhaeltnis zum rohen Modell, nie zur schon
        # korrigierten Ansage - sonst korrigiert sich der Faktor selbst weg.
        werte = list(self.cfg.get("zeitmessungen") or ())[-9:]
        werte.append(round(echt / roh, 4))
        self.cfg["zeitmessungen"] = werte
        P.save_config(self.cfg)
        if len(werte) >= 3:
            self._log(T("Aus {n} Läufen: Modell x {f:.2f}").format(
                n=len(werte), f=self._zeitfaktor()))

    def _z_target(self):
        return self.v_dicke.get() + self.v_korr.get()

    def _zv(self, z):
        return -z if self.v_zinv.get() else z

    def apply_preset(self):
        if not self.grbl.connected:
            messagebox.showinfo(T("Material"), T("Werte übernommen. Z fährt erst,\n"
                                  "wenn die Maschine verbunden ist."))
            return
        if not self.zref_ok:
            messagebox.showwarning(T("Keine Z-Referenz"),
                T("Z-Höhe kann nicht angefahren werden.\n\n"
                  "Unter 'Maschine': Fokus auf ein Material bekannter Dicke\n"
                  "einstellen und 'Z-Referenz' setzen."))
            return
        z = self._z_target()
        if not messagebox.askokcancel(T("Z anfahren"),
                T("Z auf {z:.2f} mm fahren?\n"
                  "(Kopf muss frei über dem Material stehen)").format(z=z)):
            return
        self._bg(lambda: self.grbl.goto(z=self._zv(z)),
                 T("Z -> {z:.2f}").format(z=z))

    def save_preset(self):
        n = self.v_pname.get().strip()
        if not n:
            return
        # Ohne Fokuskorrektur: die gehoert zur Maschine, nicht zum Material.
        self.presets[n] = dict(dicke=self.v_dicke.get(),
                               s=self.v_s.get(), smin=self.v_smin.get(),
                               f=self.v_f.get(), line=self.v_line.get(),
                               mode=self.v_mode.get(), schwelle=round(self.v_schw.get(), 2),
                               rasterart=self.v_raster.get(),
                               # Die Duese gehoert zum Material: Acryl ohne
                               # Luft qualmt, Holz ohne Luft brennt breiter.
                               luft=self.v_luft.get(),
                               gamma=round(self.v_gamma.get(), 2),
                               # Die Schnittwerte gehoeren dazu. Sie kosten am
                               # meisten Zeit zum Herausfinden - ein halber Tag
                               # fuer drei Zahlen - und standen bisher nirgends.
                               schnitt_s=self.v_cs.get(), schnitt_f=self.v_cf.get(),
                               durchgaenge=self.v_passes.get(),
                               notiz=self.v_notiz.get())
        P.save_presets(self.presets)
        self.cb_preset.configure(values=sorted(self.presets))
        self.v_preset.set(n)
        self._log(T("Preset '{0}' gespeichert").format(n))

    def delete_preset(self):
        n = self.v_preset.get()
        if n in self.presets and messagebox.askyesno(T("Löschen"), T("'{0}' löschen?").format(n)):
            del self.presets[n]
            P.save_presets(self.presets)
            self.cb_preset.configure(values=sorted(self.presets))
            self.v_preset.set("")

    # ================================================================ Maschine
    def toggle_connect(self):
        self._rettung = self.null_wco = None
        if self.grbl.connected:
            self.grbl.disconnect()
            self.btn_conn.configure(text=T("Verbinden"),
                                    style="Accent.TButton")
            self.zustand = ""
            self._status_zeigen()
            return
        port = self.v_port.get() or (G.ports() or [""])[0]
        if not port:
            messagebox.showerror(T("Kein Port"), T("Kein serielles Gerät gefunden."))
            return
        try:
            self.grbl.connect(port)
        except Exception as e:
            messagebox.showerror(T("Verbinden"), str(e))
            return
        self.cfg["port"] = port
        self._save_cfg()
        # Verbunden ist "Trennen" kein naechster Schritt mehr, sondern eine
        # Ausnahme - genau ein hervorgehobener Knopf auf dem Schirm.
        self.btn_conn.configure(text=T("Trennen"), style="TButton")
        self.zero_ok = self.zref_ok = False
        self._status_zeigen()
        self._log(T('verbunden: {0}').format(port))
        self._bg(self._lies_einstellungen, T("lese Maschineneinstellungen ($$)"))

    def set_sprache(self):
        kuerzel = {v: k for k, v in lw_text.SPRACHEN.items()}.get(
            self.v_sprache.get(), "de")
        if kuerzel == self.cfg.get("sprache", "de"):
            return
        self.cfg["sprache"] = kuerzel
        P.save_config(self.cfg)
        self._log(T("Sprache: {name} - gilt nach einem Neustart.").format(
            name=lw_text.SPRACHEN[kuerzel]))
        messagebox.showinfo(T("Sprache"),
            T("Die Sprache gilt, sobald Laserwerk neu gestartet wird."))

    def _rettbar(self):
        """Nur der eigene Soft-Reset laesst sich ueberleben. Nach einem
        USB-Abriss oder einem Neuverbinden ist die Maschinenposition
        wirklich unbekannt - dann waere ein wiederhergestellter Versatz
        schlimmer als keiner.

        Frueher galt das nur zwei Minuten lang. Wer nach einem STOPP erst
        in Ruhe nachsah, warum er gestoppt hat, und dann entsperrte, stand
        ohne Nullpunkt da - das Fenster war abgelaufen. Es gibt aber keinen
        Grund dafuer: der Versatz bleibt richtig, solange die Maschine ihre
        Position kennt, und genau das prueft das Abraeumen bei 'lost'.

        Gefragt wird, OB etwas gemerkt ist, nicht ob der Versatz von Null
        verschieden ist. Hier stand any(): wer den Nullpunkt setzt, ohne
        vorher zu fahren - nach dem Verbinden steht die Maschine auf ihrer
        eigenen Null - hat den Versatz (0, 0, 0), und der galt als "nichts
        gemerkt". Der G92 kam nicht zurueck, und X0 Y0 war danach die Null
        der Maschine.
        """
        return self._rettung is not None and self._rettung[0] is not None

    def null_zurueck_knopf(self):
        self._log(self.nullpunkt_zurueck())

    def _null_merken_xy(self):
        """Den Versatz so mitschreiben, wie 'G92 X0 Y0' ihn gerade gesetzt
        hat: X und Y aus der Maschinenposition, Z bleibt stehen.

        Aus dem naechsten Statusbericht lesen ginge auch - GRBL schickt WCO
        aber nur gelegentlich. Wer direkt nach dem Nullen STOPP drueckt,
        haette dann nichts zum Wiederherstellen.
        """
        st = self.grbl.status
        m = (list(st.get("mpos", ())) + [0, 0, 0])[:3]
        alt = (list(self.null_wco or st.get("wco", ())) + [0, 0, 0])[:3]
        self.null_wco = (m[0], m[1], alt[2])

    def nullpunkt_zurueck(self):
        """Den gemerkten Nullpunkt wieder setzen - jederzeit, nicht nur nach
        einem STOPP. Das Netz unter allem anderen: solange die Maschine in
        dieser Sitzung ihre Position nicht verloren hat, ist der Versatz noch
        richtig, und es gibt keinen Grund, ihn von Hand neu anfahren zu
        muessen."""
        if not self.grbl.connected:
            return T("Nicht verbunden.")
        if self.null_wco is None:
            return T("Kein Nullpunkt gemerkt - in dieser Sitzung wurde noch "
                     "keiner gesetzt.")
        self._rettung = (self.null_wco, True, self.zref_ok, time.time())
        self._bg(self._nullpunkt_retten, None)
        return T("Nullpunkt wird wieder gesetzt (X {x:.2f} / Y {y:.2f}).").format(
            x=self.null_wco[0], y=self.null_wco[1])

    def _nullpunkt_retten(self):
        """Den G92-Versatz nach einem Soft-Reset wiederherstellen.

        Beim Anhalten bremst das Programm erst aus und setzt erst dann zurueck,
        deshalb stimmt die Maschinenposition noch. Der Versatz wird also einfach
        neu gesetzt: G92 auf (MPos - altes WCO). Es bewegt sich dabei nichts.
        """
        # Zwei Wege koennen gleichzeitig retten wollen - das reset-Ereignis
        # und das Jobende. Wer zuerst kommt, nimmt die Rettung an sich; der
        # zweite findet nichts mehr vor und laesst es.
        rettung, self._rettung = self._rettung, None
        if rettung is None:
            return
        wco, war_null, war_zref, wann = rettung
        if wco is None:
            return
        self.grbl.wait_idle(timeout=8)
        st = self.grbl.status
        if self.grbl.alarm or st["state"].startswith(("Alarm", "Door")):
            self._rettung = (wco, war_null, war_zref, wann)  # nach dem Entsperren
            self.q.put(("msg", T("Nullpunkt gemerkt - er wird nach dem "
                                 "Entsperren ($X) wiederhergestellt.")))
            return
        m = (list(st.get("mpos", ())) + [0, 0, 0])[:3]
        ziel = [a - b for a, b in zip(m, (list(wco) + [0, 0, 0])[:3])]
        r = self.grbl.cmd("G92 X{:.3f} Y{:.3f} Z{:.3f}".format(*ziel))
        if str(r).startswith("ok"):
            self.zero_ok, self.zref_ok = war_null, war_zref
            self.q.put(("msg", T("Nullpunkt nach dem STOPP wiederhergestellt "
                                 "(X {x:.2f} / Y {y:.2f}).").format(
                                     x=ziel[0], y=ziel[1])))
        else:
            self.q.put(("msg", T("Nullpunkt konnte nicht wiederhergestellt "
                                 "werden ({r}) - bitte neu setzen.").format(r=r)))

    def set_watt(self):
        """Optische Leistung uebernehmen. Sie steht in keinem $-Wert: die
        Maschine kennt ihre Watt nicht, nur ihre Skala."""
        try:
            w = float(self.v_watt.get())
        except tk.TclError:
            return
        if not (0.1 <= w <= 500):
            messagebox.showerror(T("Leistung"), T("Wert zwischen 0,1 und 500 W."))
            return
        self.cfg["watt"] = w
        P.save_config(self.cfg)
        J.setze_maschine(self.cfg)
        self._watt_zeigen()
        self._maschine_zeigen()
        self._log(T("Leistung der Maschine: {w:.1f} W - mitgelieferte Werte "
                    "sind an 5,5 W gemessen, dieselbe Energie braucht hier "
                    "S/F mal {v:.2f}.").format(w=w, v=5.5 / w))

    def _watt_zeigen(self):
        """Was die Leistung fuer die eingestellten Werte bedeutet.

        Die Presets sind an 5,5 W gemessen. An einer staerkeren Maschine
        bringt dasselbe S/F ein Mehrfaches an Energie - und wer das nicht
        umrechnet, verbrennt das erste Brett.
        """
        if not hasattr(self, "lbl_watt"):
            return
        try:
            s, f = int(self.v_s.get()), int(self.v_f.get())
        except (tk.TclError, AttributeError):
            s, f = 830, 1000
        self.lbl_watt.configure(text=T(
            "Gravur S{s}/F{f} = {j} J/mm").format(
                s=s, f=f, j=Z(J.energie(s, f, 1, self._watt()), 2)))

    def _flaeche_titel(self):
        self.lf_flaeche.configure(text=T(
            "Arbeitsbereich ({x:.0f} x {y:.0f} mm, Nullpunkt unten links)").format(
                x=self.cfg["x_max"], y=self.cfg["y_max"]))

    def set_area(self):
        """Verfahrweg uebernehmen: Anzeige, Warnschwelle und Raster danach."""
        try:
            x, y = float(self.v_xmax.get()), float(self.v_ymax.get())
        except tk.TclError:
            return
        if not (10 <= x <= 2000 and 10 <= y <= 2000):
            messagebox.showerror(T("Verfahrweg"), T("Werte zwischen 10 und 2000 mm."))
            return
        self.cfg["x_max"], self.cfg["y_max"] = x, y
        P.save_config(self.cfg)
        self.area = max(x, y)
        self._flaeche_titel()
        self._log(T('Verfahrweg {0:.0f} x {1:.0f} mm').format(x, y))
        self.reset_view()

    def area_von_maschine(self):
        d = self.grbl.settings
        if not d.get("130"):
            messagebox.showinfo(T("Verfahrweg"),
                T("Noch keine $$-Antwort. Erst verbinden - die Werte werden\n"
                  "dann automatisch gelesen."))
            return
        self.v_xmax.set(round(d["130"], 1))
        self.v_ymax.set(round(d.get("131", d["130"]), 1))
        self.set_area()

    def _lies_einstellungen(self):
        """$$ lesen und pruefen, ob die Maschine so tickt wie erwartet.

        Entscheidend ist $30, der Hoechstwert von S: alle Werte hier sind auf
        die Skala 0..1000 bezogen. Steht dort 255, waere S50 fuer das
        Sichtkreuz nicht 5 % sondern 20 % - das brennt, statt zu zeigen.
        """
        d = self.grbl.read_settings()
        if not d:
            self.q.put(("msg", "$$ nicht beantwortet - Werte ungeprueft."))
            return
        self.q.put(("einstellungen", d))

    def _maschine_erkennen(self, d):
        """Passt die angeschlossene Maschine zu der, die gewaehlt ist?

        Zwei Maschinen abwechselnd heisst: man steckt um und vergisst
        umzuschalten. Dann gelten die Presets der anderen, und bei
        vierfacher Leistung ist das das erste verbrannte Brett.
        $130/$131 verraten es, bevor etwas laeuft.
        """
        x, y = d.get("130"), d.get("131")
        if not (x and y):
            return

        def passt(werte):
            try:
                return (abs(float(werte.get("x_max", -1)) - x) <= 2
                        and abs(float(werte.get("y_max", -1)) - y) <= 2)
            except (TypeError, ValueError):
                return False

        if passt(self.cfg):
            return
        andere = [n for n in self._maschinen_namen()
                  if n != self._maschine_name()
                  and passt(P.maschine_holen(self.maschinen, n)[0] or {})]
        if not andere:
            return                        # sagt schon die Verfahrwegwarnung
        if messagebox.askyesno(T("Maschine"), T(
                "Angeschlossen ist eine Maschine mit {x:.0f} x {y:.0f} mm "
                "Verfahrweg, gewählt ist '{n}' mit {cx:.0f} x {cy:.0f} mm.\n\n"
                "Zu '{a}' wechseln? Dort passt der Verfahrweg - und damit "
                "auch Leistung, Presets und Fokuskorrektur.").format(
                    x=x, y=y, n=self._maschine_name(),
                    cx=float(self.cfg["x_max"]), cy=float(self.cfg["y_max"]),
                    a=andere[0])):
            self.maschine_wechseln(andere[0], fragen=False)

    def _einstellungen_pruefen(self, d):
        # Zuerst: redet Laserwerk ueberhaupt mit der Maschine, die gewaehlt
        # ist? Sonst schreibt der naechste Abschnitt die Beschleunigung der
        # einen in das Profil der anderen.
        self._maschine_erkennen(d)
        hin = []
        s30 = d.get("30")
        if s30 and abs(s30 - self.s_max) > 0.5:
            self.s_max = float(s30)
            self.cfg["s_max"] = self.s_max
            P.save_config(self.cfg)
        if s30 and abs(s30 - J.S_MAX) > 0.5:
            hin.append(T("$30 = {ist:.0f} statt {soll}: Die Werte hier sind auf "
                         "0..{soll} bezogen und werden beim Senden umgerechnet "
                         "(S{a:.0f} wird S{b:.0f}).").format(
                ist=s30, soll=J.S_MAX, a=self.v_s.get(),
                b=self._s(self.v_s.get())))
        # Was die Maschine selbst sagt, zaehlt mehr als jede Vorgabe. Bei
        # unterschiedlichen Achsen die kleinere: die bremst den Weg.
        gelesen = {}
        if d.get("120") or d.get("121"):
            gelesen["accel"] = min(v for v in (d.get("120"), d.get("121")) if v)
        if d.get("110") or d.get("111"):
            gelesen["eilgang"] = min(v for v in (d.get("110"), d.get("111")) if v)
        if d.get("11"):
            gelesen["kreuzung"] = float(d["11"])
        alt = {k: self.cfg.get(k) for k in gelesen}
        if gelesen and alt != gelesen:
            self.cfg.update(gelesen)
            P.save_config(self.cfg)
            J.setze_maschine(self.cfg)
            self._log(T("Von der Maschine übernommen: {b:.0f} mm/s² "
                        "Beschleunigung, {e:.0f} mm/min Eilgang, "
                        "$11 = {k:.3f} mm").format(
                            b=J.ACCEL, e=J.EILGANG, k=J.KREUZUNG))
            self._anlauf_zeigen()
        if d.get("32") is not None and d["32"] < 0.5:
            hin.append(T("$32 = 0: Der Lasermodus ist AUS. Der Strahl brennt dann "
                         "auch im Stillstand weiter - mit '$32=1' einschalten."))
        if d.get("20", 0) >= 0.5:
            hin.append(T("$20 = 1: Softlimits sind an. Ohne Referenzfahrt ($H) "
                         "weist der Controller Fahrten ab."))
        x, y = d.get("130"), d.get("131")
        if x and y:
            self._log(T('Verfahrweg laut Maschine: {0:.0f} x {1:.0f} mm').format(x, y))
            if abs(x - self.cfg["x_max"]) > 1 or abs(y - self.cfg["y_max"]) > 1:
                hin.append(T("Verfahrweg laut $130/$131 ist {x:.0f} x {y:.0f} mm, "
                             "eingestellt sind {cx:.0f} x {cy:.0f} mm "
                             "(Reiter Maschine).").format(
                    x=x, y=y, cx=self.cfg["x_max"], cy=self.cfg["y_max"]))
        self._log(f"$30={d.get('30', 0):.0f}  $32={d.get('32', 0):.0f}  "
                  f"$110={d.get('110', 0):.0f}  $120={d.get('120', 0):.0f}")
        if hin:
            for z in hin:
                self._log(z)
            messagebox.showwarning(T("Maschineneinstellungen"), "\n\n".join(hin))

    def _zeig_s(self):
        """Leistung fuers Zeigen, gedeckelt auf das, was diese Maschine
        vertraegt.

        Sichtkreuz, Rahmen und Kontur sollen zeigen, wo etwas hinkommt,
        und nichts hinterlassen. Die Grenze dafuer ist Energie je
        Millimeter, nicht S/F: die feste 120 im Quelltext war die Grenze
        genau einer Maschine. An 22 W ist dasselbe S/F das Vierfache -
        S50/F600 zeigt an der kleinen und brennt an der Falcon ein.

        Gedeckelt wird, nicht abgebrochen: wer zeigen will, soll etwas
        sehen und nicht einen Dialog. Dass heruntergeregelt wurde, steht
        im Protokoll - sonst wundert sich jemand, warum der Punkt an der
        grossen Maschine blasser ist.
        """
        try:
            wunsch = max(1, int(self.v_zeig_s.get()))
        except (tk.TclError, ValueError):
            wunsch = J.zeig_s(self._watt())
        hoechst = J.zeig_s(self._watt(), j=J.ZEIG_J_MAX)
        if wunsch <= hoechst:
            return wunsch
        self._log(T("S{s} waeren {j:.3f} J/mm an {w:.1f} W - ab {jm:.3f} J/mm "
                    "bleibt eine Spur. Gezeigt wird mit S{h}.").format(
            s=wunsch, w=self._watt(), jm=J.ZEIG_J_MAX, h=hoechst,
            j=J.energie(wunsch, J.POINTER_FEED, 1, self._watt())))
        return hoechst

    def _s(self, wert):
        """Leistung von der Skala 0..1000 auf die der Maschine ($30) bringen."""
        try:
            v = float(wert) * self.s_max / J.S_MAX
        except (TypeError, ValueError):
            return wert
        return max(0, min(int(round(v)), int(self.s_max)))

    def _need(self, zero=False):
        if not self.grbl.connected:
            messagebox.showinfo(T("Maschine"), T("Nicht verbunden."))
            return False
        if self.grbl.job_running:
            messagebox.showinfo(T("Maschine"), T("Es läuft gerade ein Job."))
            return False
        if zero and not self.zero_ok:
            if not messagebox.askyesno(T("Nullpunkt"),
                    T("In dieser Sitzung wurde noch kein Nullpunkt gesetzt.\n"
                      "Trotzdem fortfahren?")):
                return False
        return True

    def jog(self, sx, sy, sz):
        if not self._need():
            return
        st = self.v_step.get()
        dz = self._zv(sz * st) if sz else 0
        try:
            self.grbl.jog(sx * st, sy * st, dz, feed=self.cfg.get("jog_feed", 1000))
        except Exception as e:
            self._log(T('Jog: {0}').format(e))

    def set_zero(self):
        if not self._need():
            return
        self.grbl.set_zero_xy()
        self.zero_ok = True
        self._null_merken_xy()
        self._log(T("Nullpunkt XY gesetzt"))

    def set_zref(self):
        if not self._need():
            return
        z = self.v_zref.get()
        self.grbl.set_z_reference(self._zv(z))
        self.zref_ok = True
        if self.null_wco:
            # 'G92 Z{wert}' verschiebt nur die Z-Achse des Versatzes.
            m = (list(self.grbl.status.get("mpos", ())) + [0, 0, 0])[:3]
            self.null_wco = (self.null_wco[0], self.null_wco[1],
                             m[2] - self._zv(z))
        self._log(T('Z-Referenz: aktuelle Höhe = Fokus für {0:.2f} mm').format(z))

    def goto_zero(self):
        if not self._need():
            return
        if not self.zero_ok:
            # Ohne gueltigen Versatz ist X0 Y0 der Maschinennullpunkt - und der
            # liegt irgendwo, nicht auf dem Werkstueck.
            if not messagebox.askokcancel(T("Zum Nullpunkt fahren"),
                    T("In dieser Sitzung ist kein Nullpunkt gesetzt (oder er ist "
                      "nach einem STOPP verloren).\n\n"
                      "X0 Y0 ist dann der Nullpunkt der MASCHINE, nicht der des "
                      "Werkstücks - der Kopf fährt irgendwohin.\n\n"
                      "Trotzdem fahren?")):
                return
        self._bg(lambda: self.grbl.goto(x=0, y=0), T("fahre zum Nullpunkt"))

    def zeigen(self):
        """Sichtkreuz: im Lasermodus geht Licht nur waehrend einer Fahrt."""
        if not self._need():
            return
        sv = self._zeig_s()
        arm = max(0.5, min(float(self.v_zeig_a.get()), 8.0))
        g = J.kreuz_lines(self._s(sv), J.POINTER_FEED, arm)
        self._log(T("Kreuz {mm:.1f} mm bei S{s}/F{f} (S/F {sf:.2f})").format(
            mm=2 * arm, s=sv, f=J.POINTER_FEED, sf=sv / J.POINTER_FEED))
        self._bg(lambda: [self.grbl.cmd(c) for c in g], None)

    def unlock(self):
        if self._need():
            self._log(self.grbl.unlock())
            if self._rettbar():
                self._bg(self._nullpunkt_retten, None)

    def laser_off(self):
        self.grbl.laser_off()
        self._log("M5 gesendet")

    def send_cmd(self):
        c = self.v_cmd.get().strip()
        if c and self._need():
            self._bg(lambda: self._log(T('{0} -> {1}').format(c, self.grbl.cmd(c))), None)
            self.v_cmd.set("")

    def _bg(self, fn, msg):
        if msg:
            self._log(msg)
        def run():
            try:
                fn()
            except Exception as e:
                self.q.put(("msg", T("Fehler: {e}").format(e=e)))
        threading.Thread(target=run, daemon=True).start()

    def _save_cfg(self):
        self.cfg["z_invert"] = self.v_zinv.get()
        self.cfg["luft"] = self._luft_an()
        self._fokus_sichern()
        P.save_config(self.cfg)
        # Der laufende Stand gehoert auch in das Profil der Maschine -
        # sonst holt der naechste Wechsel einen alten Stand zurueck.
        self._maschine_sichern()

    def _fokus_geaendert(self, *_):
        """Beschriftung sofort, Datei etwas spaeter.

        Jeder Tastendruck in einem der beiden Felder loest ein Schreiben
        aus - die Konfiguration bei jedem einzelnen neu zu schreiben hiesse
        auch, halb getippte Zahlen zu sichern.
        """
        self._fokus_zeigen()
        if self._fokus_job is not None:
            self.root.after_cancel(self._fokus_job)
        self._fokus_job = self.root.after(1500, self._fokus_spaet)

    def _fokus_spaet(self):
        self._fokus_job = None
        self._save_cfg()
        # Die Materialstaerke steckt auch im Kamerabild. Erst hier, nicht
        # bei jedem Tastendruck: das Umrechnen kostet einen Augenblick.
        if self._kamera_neu_rechnen():
            self._kamera_zeigen()

    def _fokus_zeigen(self):
        """Dicke, Korrektur und die Hoehe, die daraus wird - an beiden
        Stellen, an denen man sie braucht."""
        try:
            d, k = float(self.v_dicke.get()), float(self.v_korr.get())
        except (tk.TclError, ValueError):
            return                      # halb getippt, gleich kommt mehr
        vor = "+" if k >= 0 else "−"
        self.lbl_fokus.configure(text=T(
            "Mitte des Tests: Z {z} mm\n"
            "= Dicke {d} mm, Korrektur {v}{k} mm").format(
                z=Z(d + k, 2), d=Z(d, 2), v=vor, k=Z(abs(k), 2)))
        self.lbl_zhoehe.configure(text=T(
            "Z fährt auf {z} mm = Dicke {d} mm, Korrektur {v}{k} mm").format(
                z=Z(d + k, 2), d=Z(d, 2), v=vor, k=Z(abs(k), 2)))

    def _fokus_sichern(self):
        """Materialdicke und Fokuskorrektur in die Konfiguration schreiben.

        Beides stand bisher nur in der Oberflaeche und in Presets. Wer ein
        Preset nicht von Hand speicherte, fing nach jedem Start wieder bei
        0,0 an - und gravierte oder schnitt ausser Fokus weiter, ohne dass
        sich sichtbar etwas geaendert haette.
        """
        for name, var in (("dicke", self.v_dicke), ("korrektur", self.v_korr)):
            try:
                self.cfg[name] = float(var.get())
            except (tk.TclError, ValueError):
                pass                      # halb getipptes Feld nicht sichern

    # ================================================================ Tests
    def fokustest(self):
        if not self._need(zero=True):
            return
        if not self.zref_ok:
            messagebox.showwarning(T("Keine Z-Referenz"),
                T("Für den Z-Fokustest wird eine Z-Referenz gebraucht\n(Reiter Maschine)."))
            return
        zm = self._z_target()
        g, zs = J.fokustest_z(self._zv(zm), self.v_ft_span.get(), self.v_ft_step.get(),
                              self._s(self.v_ft_s.get()), self.v_ft_f.get())
        self.fokus_zs = [self._zv(z) for z in zs]
        self.lb_fz.delete(0, "end")
        for i, z in enumerate(self.fokus_zs, 1):
            self.lb_fz.insert("end", T("Strich {i:>2}:  Z = {z:.2f} mm").format(i=i, z=z))
        self._run(g, T("Fokustest {n} Striche").format(n=len(zs)), confirm=True)

    def take_focus(self):
        sel = self.lb_fz.curselection()
        if not sel:
            return
        z = self.fokus_zs[sel[0]]
        self.v_korr.set(round(z - self.v_dicke.get(), 2))
        # Sofort sichern. Der Wert ist gemessen, nicht geraten - ihn vom
        # Benutzer in ein Preset tippen zu lassen heisst, ihn zu verlieren.
        self._save_cfg()
        self._log(T('Fokuskorrektur = {0:+.2f} mm - gesichert, gilt auch nach '
                    'dem Neustart').format(self.v_korr.get()))

    def _gt_werte(self):
        ps = [int(x) for x in self.v_gt_s.get().replace(" ", "").split(",") if x]
        return (ps, int(self.v_gt_f.get()), max(2, int(self.v_gt_n.get())),
                max(2.0, float(self.v_gt_feld.get())))

    def _gt_vorschau(self):
        """Maße und Laufzeit vorab zeigen - der Test frisst sonst unbemerkt
        eine halbe Stunde und ein halbes Brett."""
        try:
            ps, fv, n, feld = self._gt_werte()
            if not ps:
                raise ValueError
        except (tk.TclError, ValueError):
            self.lbl_gt.configure(text=T("Werte prüfen."))
            return
        _, i = J.graustufentest(ps, fv, n, feld, line=self.v_line.get())
        self.lbl_gt.configure(text=T("{b} x {h} mm, Laufzeit ca. "
                                     "{min} min").format(
            b=Z(i["breite"], 0), h=Z(i["hoehe"], 0),
            min=Z(self._min(i["sekunden"]), 0)))

    def graustufentest(self):
        if not self._need(zero=True):
            return
        try:
            ps, fv, n, feld = self._gt_werte()
            if not ps:
                raise ValueError
        except (tk.TclError, ValueError):
            messagebox.showerror(T("Graustufentest"),
                                 T("Werte mit Komma trennen, z.B. 200,400,600"))
            return
        g, i = J.graustufentest([self._s(p) for p in ps], fv, n, feld,
                                line=self.v_line.get(),
                                s_min=self._s(self._s_unten(max(ps)))
                                if int(self.v_smin.get() or 0) > 0 else None)
        self.lines, self.info = g, i
        self.preview_pil = self.preview_img = self.cut_polys = None
        self._log(T("Graustufentest: {n} Leistungen x {s} Stufen, "
                    "{b:.0f} x {h:.0f} mm").format(n=len(ps), s=n,
                                                   b=i["breite"], h=i["hoehe"]))
        self._draw()
        self._run(g, T("Graustufentest"), confirm=True)

    # ================================================================ Job
    def frame(self):
        if not self.lines:
            messagebox.showinfo(T("Rahmen"), T("Erst G-Code erzeugen oder laden."))
            return
        sv = self._zeig_s() if self.v_frame_laser.get() else 0
        name = (T("Rahmenfahrt (Laser schwach, S{s})").format(s=sv) if sv
                else T("Rahmenfahrt (Laser aus)"))
        x0, x1, y0, y1 = J.brenn_extent(self.lines)
        self._log(T("Rahmen X {x0:.1f}..{x1:.1f}  Y {y0:.1f}..{y1:.1f} "
                    "({b:.1f} x {h:.1f} mm)").format(
            x0=x0, x1=x1, y0=y0, y1=y1, b=x1 - x0, h=y1 - y0))
        if self._need(zero=True):
            self._run(J.frame_lines(self.lines, self._s(sv), J.POINTER_FEED),
                      name, rahmen=True)

    def kontur(self):
        """Die echte Kontur mit schwachem Strahl abfahren statt nur den Kasten.

        Bei einem gedrehten oder runden Teil sagt das umschliessende Rechteck
        wenig darueber, ob das Motiv auf das Brettchen passt.
        """
        if not self.vec:
            messagebox.showinfo(T("Kontur fahren"),
                                T("Nur bei SVG und DXF - ein Pixelbild hat keine "
                                  "Konturen.\n\nFür Bilder den Rahmen fahren."))
            return
        try:
            w, h = float(self.v_w.get()), float(self.v_h.get())
        except tk.TclError:
            messagebox.showerror(T("Eingabe"), T("Zahlenfeld ungültig."))
            return
        polys = self._schnitt_polys(w, h)
        if polys is None:
            return
        sv = self._zeig_s()
        g, i = V.cut_gcode(polys, self._s(sv), J.POINTER_FEED, 1)
        self._log(T("Kontur fahren: {k} Konturen, {m:.2f} m, ca. {min:.0f} min, "
                    "S{s}/F{f}").format(k=i["konturen"], m=i["cut_m"],
                                        min=max(1, self._min(i["sekunden"])),
                                        s=sv, f=J.POINTER_FEED))
        if self._min(i["sekunden"]) > 2 and not messagebox.askokcancel(
                T("Kontur fahren"),
                T("{k} Konturen, {m:.2f} m Weg, ca. {min:.0f} min.\n\n"
                  "Fortfahren?").format(k=i["konturen"], m=i["cut_m"],
                                        min=max(1, self._min(i["sekunden"])))):
            return
        self._run(g, T("Kontur fahren"), rahmen=True)

    def start(self):
        if not self.lines:
            messagebox.showinfo(T("Start"), T("Erst G-Code erzeugen oder laden."))
            return
        self._run(self.lines, T("Gravur"), confirm=True)

    def _run(self, lines, name, confirm=False, rahmen=False):
        # Der Name ist nur Anzeige - uebersetzt taugt er nicht mehr als
        # Unterscheidung, deshalb sagt 'rahmen' ausdruecklich Bescheid.
        if not self._need(zero=not rahmen):
            return
        # Nicht die Spanne pruefen, sondern wo der Kopf wirklich hin muss.
        # Die Spanne verschweigt einen Job, der weit draussen liegt, und
        # verbietet einen, der nur zum Nullpunkt zurueckfaehrt.
        # Tiefer als das Material heisst: in die Unterlage. Beim Lasern
        # kommt Z nur im Fokustest vor und liegt dort ueber null.
        z = J.z_extent(lines)
        if z and z[0] < -0.01:
            try:
                dicke = float(self.v_dicke.get())
            except tk.TclError:
                dicke = 0.0
            if dicke > 0 and z[0] < -(dicke + 0.5):
                if not messagebox.askokcancel(T("Tiefe"),
                        T("Die Datei geht bis Z {z:.2f} mm hinunter, das "
                          "Material ist {d:.2f} mm dick.\n\n"
                          "Das schneidet in die Unterlage. Trotzdem "
                          "starten?").format(z=z[0], d=dicke)):
                    return
        x0, x1, y0, y1 = J.extent(lines)
        xm, ym = float(self.cfg["x_max"]), float(self.cfg["y_max"])
        if x1 > xm + 0.05 or y1 > ym + 0.05 or x0 < -0.05 or y0 < -0.05:
            messagebox.showerror(T("Zu groß"),
                T("Der Job braucht X {x0:.1f} .. {x1:.1f} und "
                  "Y {y0:.1f} .. {y1:.1f} mm.\n\n"
                  "Der Verfahrweg ist 0 .. {xm:.0f} und 0 .. {ym:.0f} mm "
                  "(Reiter Maschine, 'Verfahrweg der Maschine').").format(
                    x0=x0, x1=x1, y0=y0, y1=y1, xm=xm, ym=ym))
            return
        if confirm:
            t = ""
            if self.info and lines is self.lines and self.info.get("sekunden"):
                t = T("\nLaufzeit ca. {min:.0f} min").format(
                    min=self._min(self.info["sekunden"]))
            if not messagebox.askokcancel(name,
                    T("{name} starten?\nBereich X {x0:.1f}..{x1:.1f}, "
                      "Y {y0:.1f}..{y1:.1f} mm{zeit}\n\n"
                      "Schutzbrille auf? Absaugung an? Daneben bleiben."
                      ).format(name=name, x0=x0, x1=x1, y0=y0, y1=y1, zeit=t)
                    + (T("\n\nSCHNEIDEN: Brandgefahr - Material kann "
                         "weiterglimmen!")
                       if self._schneidet() and lines is self.lines else "")):
                return
        self.job_t0 = time.time()
        # Die Schaetzung jetzt festhalten: bis der Job zu Ende ist, kann
        # self.info laengst zu einem anderen Motiv gehoeren.
        self.job_schaetzung = ((self.info or {}).get("sekunden")
                               if lines is self.lines else None)
        self.marken = (self.info or {}).get("marken") if lines is self.lines else None
        self._marken_idx = [m[0] for m in self.marken] if self.marken else None
        self.prog["value"] = 0
        self._log(T('{0} gestartet').format(name))

        def run():
            res = self.grbl.run_job(
                lines, lambda d, t, el, er: self.q.put(("prog", (d, t, el, er))),
                marken=self._marken_idx)
            self.q.put(("jobend", (name, res)))
        threading.Thread(target=run, daemon=True).start()

    def pause(self):
        """Anhalten - entweder sofort oder am Ende der laufenden Zeile.

        Ein Feed Hold bremst mitten in der Zeile ab. Im Lasermodus geht der
        Strahl dabei zwar aus, aber die Bremsspur liegt im Motiv, und beim
        Weiterfahren faengt die Zeile aus dem Stand wieder an - beides sieht
        man hinterher. Am Zeilenende steht der Kopf im Anlauf daneben.
        """
        if not self.grbl.connected:
            return
        if self.v_pause_ende.get() and self.grbl.job_running:
            self.grbl.pause_am_zeilenende()
            self._log(T("Pause angemeldet - hält am Ende der laufenden Zeile."))
            return
        self.grbl.pause()
        self._log(T("Pause (Feed Hold) - Laser aus. 'Weiter' setzt fort."))

    def resume(self):
        if self.grbl.connected:
            self.grbl.resume()
            self._log(T("weiter"))

    def stop(self):
        if not self.grbl.connected:
            return
        # Der Soft-Reset im Controller loescht den G92-Versatz. Vorher merken,
        # damit der Nullpunkt danach wiederhergestellt werden kann - sonst
        # faehrt "Zum Nullpunkt" an den Maschinennullpunkt. Der mitgefuehrte
        # Versatz ist die bessere Quelle: WCO kommt nur gelegentlich im
        # Statusbericht, und nach einem Alarm steht da schon (0, 0, 0).
        wco = self.null_wco
        if wco is None:
            # Nichts mitgeschrieben: dann taugt nur ein Versatz aus dem
            # Statusbericht, und der ist nach einem Alarm schon (0, 0, 0) -
            # also nur, wenn wirklich etwas drinsteht.
            st = tuple(self.grbl.status.get("wco", ()) or ())
            wco = st if any(st) else None
        self._rettung = (wco, self.zero_ok, self.zref_ok, time.time())
        self._log(T("STOPP"))
        # Die Rettung haengt sonst daran, dass der Controller sich mit einer
        # Zeile zurueckmeldet, die "Grbl" heisst. Der Soft-Reset ist aber
        # unser eigener: kommt keine erkannte Startzeile, holt dieser Faden
        # den Nullpunkt selbst zurueck. Eine fremde Firmware sagt etwas
        # anderes - und der Nullpunkt waere ohne das weg.
        vorher = getattr(self.grbl, "reset_seen", 0)

        def werk():
            self.grbl.stop()
            for _ in range(30):                   # bis zu 3 s
                if getattr(self.grbl, "reset_seen", 0) != vorher:
                    return                        # das Ereignis macht es
                time.sleep(0.1)
            self.q.put(("msg", T("Keine erkannte Startzeile nach dem "
                                 "Soft-Reset - der Nullpunkt wird ohne sie "
                                 "wiederhergestellt.")))
            self._nullpunkt_retten()

        threading.Thread(target=werk, daemon=True).start()

    # ================================================================ Aussehen
    def _theme_label(self):
        self.btn_theme.configure(
            text=T("Hell") if S.THEME == "dunkel" else T("Dunkel"))

    def toggle_theme(self):
        neu = "hell" if S.THEME == "dunkel" else "dunkel"
        S.apply(self.root, neu)
        S.restyle_widgets([self.log, self.lb_fz])
        self.cv.configure(bg=S.CANVAS_BG, highlightbackground=S.LINE)
        for w in self.root.winfo_children():
            for c in w.winfo_children():
                for d in c.winfo_children():
                    if d.winfo_class() == "Canvas" and d is not self.cv:
                        d.configure(bg=S.BG)
        self.cfg["theme"] = neu
        P.save_config(self.cfg)
        self._theme_label()
        self._draw()

    # ================================================================ Ereignisse
    def _poll(self):
        # Lebenszeichen fuer den Wachhund: bleibt die Schleife stehen, wird
        # das hier alt, und die Threadspuren landen in der Haengerdatei.
        self._herzschlag = time.time()
        try:
            while True:
                k, d = self.q.get_nowait()
                self._event(k, d)
        except queue.Empty:
            pass
        self._poll_id = self.root.after(100, self._poll)

    def beenden(self, fragen=True):
        """Sauber zumachen: Abfrage anhalten, Bot stilllegen, Port schliessen.
        Ohne das laeuft die Abfrage in ein zerstoertes Fenster und der
        Controller behaelt die offene Verbindung.

        Laeuft ein Job, wird vorher gefragt - sonst reicht ein Klick auf das
        Kreuz, um eine Gravur nach einer Stunde zu verlieren.
        """
        if fragen and self.grbl.connected and self.grbl.job_running:
            if not messagebox.askokcancel(T("Beenden"),
                    T("Es läuft gerade ein Job.\n\n"
                      "Beenden hält ihn an und schaltet den Laser aus. "
                      "Fortsetzen ist danach nur über die Position möglich "
                      "(fortsetzen.py).\n\nWirklich beenden?")):
                return
            self.grbl.stop()
        try:
            if getattr(self, "_poll_id", None):
                self.root.after_cancel(self._poll_id)
                self._poll_id = None
            # Ein noch offenes Sichern von Dicke/Korrektur jetzt erledigen,
            # statt es in ein zerstoertes Fenster laufen zu lassen.
            if getattr(self, "_fokus_job", None):
                self.root.after_cancel(self._fokus_job)
                self._fokus_job = None
                self._save_cfg()
        except Exception:
            pass
        if self.fern is not None:
            self.fern.stop()
        try:
            if self.grbl.connected:
                self.grbl.laser_off()
                self.grbl.disconnect()
        except Exception:
            pass
        self.root.destroy()

    def _event(self, k, d):
        if k == "status":
            x, y, z = (list(d["wpos"]) + [0, 0, 0])[:3]
            if self.v_zinv.get():
                z = -z
            self.kopf_pos = (x, y, z)
            self.kopf_fs = (d["fs"][0] if d["fs"] else 0,
                            d["fs"][1] if len(d["fs"]) > 1 else 0)
            self.zustand = d["state"]
            self.head = (x, y)
            # Den Versatz mitschreiben, solange der Nullpunkt steht. GRBL
            # schickt WCO nur gelegentlich, deshalb nur bei echten Werten.
            if self.zero_ok and any(d.get("wco", ())):
                self.null_wco = tuple(d["wco"])
            self._draw_head()
            self._status_zeigen()
        elif k == "kamerabild":
            self._kamera_uebernehmen(d)
        elif k == "prog":
            done, tot, el, er = d
            self.prog["value"] = done * 1000 / tot
            rest = el / done * (tot - done) if done else 0
            if self.info and self.info.get("sekunden") and done > 0:
                # Modellschaetzung zaehlt mehr als lineare Hochrechnung
                rest = (max(0.0, self._min(self.info["sekunden"]) * 60 - el)
                        * 0.6 + rest * 0.4)
            self._jobtext = (
                T("{p} %   noch ~{min:.0f} min").format(p=done * 100 // tot,
                                                        min=rest / 60)
                + (T("   {n} Fehler").format(n=er) if er else ""))
            self.lbl_prog.configure(text=self._jobtext, style="TLabel")
            self.lbl_marke.configure(text=self._marke_text(done))
        elif k == "jobend":
            name, res = d
            txt = {"fertig": T("fertig"),
                   "abgebrochen": T("abgebrochen (Laser aus)"),
                   "alarm": T("ALARM - gestoppt"),
                   "verbindung": T("Verbindung verloren"),
                   "fehler": T("zu viele Übertragungsfehler")}.get(res, res)
            er = getattr(self.grbl, "job_errors", 0)
            gesendet = getattr(self.grbl, "job_done", 0)
            self._jobtext = (T('{0}: {1}').format(name, txt)
                             + (T("   {n} Fehler").format(n=er) if er else ""))
            self.lbl_prog.configure(text=self._jobtext, style="TLabel")
            self.lbl_marke.configure(text="")
            self._status_zeigen()
            self._log(T('{0}: {1}').format(name, txt))
            # Die Fehlerzahl stand bisher nur in der Fortschrittsanzeige und
            # war mit dem Jobende weg. Hinterher ist sie die einzige Spur,
            # die eine ausgelassene Zeile erklaeren koennte.
            self._log(T("Übertragung: {n} Fehler in {g} Befehlen").format(
                n=er, g=gesendet))
            self._melde(f"{name}: {txt}"
                        + (T("\n{n} Übertragungsfehler").format(n=er) if er else ""))
            if res == "fertig" and self.job_t0 and self.job_schaetzung:
                self._zeit_merken(time.time() - self.job_t0,
                                  self.job_schaetzung)
            if res != "fertig":
                # Der Soft-Reset nach einem Abbruch loescht den Versatz im
                # Controller - aber wir wissen, wo er lag. Frueher stand hier
                # nur "weg damit", und das traf auch die Rettung, die nach
                # dem Reset schon gelaufen war: der Nullpunkt kam zurueck und
                # dieses Ereignis loeschte ihn eine Sekunde spaeter wieder.
                # Genau das war das "ab und zu". Nur ein Abriss ist
                # endgueltig - der raeumt in seinem eigenen Zweig auf.
                if res == "verbindung" or self.null_wco is None:
                    self.zero_ok = self.zref_ok = False
                else:
                    if self._rettung is None:
                        self._rettung = (self.null_wco, True, self.zref_ok,
                                         time.time())
                    if not self.zero_ok:
                        # Der Reset ist schon durch und hat ihn gekostet -
                        # sonst holt ihn das reset-Ereignis selbst zurueck.
                        self._bg(self._nullpunkt_retten, None)
                if res != "abgebrochen":
                    messagebox.showwarning(name, txt)
        elif k == "pausiert":
            t = T("Pause am Zeilenende - Laser aus, Kopf steht. "
                  "'Weiter' setzt fort.")
            self._log(t)
            self._melde(t)
        elif k == "weiter":
            self._log(T("weiter ab {marke}").format(
                marke=self.lbl_marke.cget("text") or T("der nächsten Zeile")))
        elif k == "alarm":
            self._log(d)
            self._melde(f"ALARM: {d}")
        elif k == "reset":
            self.zero_ok = self.zref_ok = False
            if self._rettbar():
                self._bg(self._nullpunkt_retten, None)
            elif self._rettung is not None:
                self._rettung = None
            else:
                self._log(T("Controller neu gestartet - Nullpunkt und "
                            "Z-Referenz neu setzen!"))
        elif k == "lost":
            self.btn_conn.configure(text=T("Verbinden"), style="Accent.TButton")
            self.zustand = ""
            self.zero_ok = self.zref_ok = False
            # Position nach einem Abriss unbekannt - ein wiederhergestellter
            # Versatz waere dann schlimmer als gar keiner.
            self._rettung = self.null_wco = None
            self._log(T('VERBINDUNG VERLOREN: {0}').format(d))
            self._melde(T("VERBINDUNG VERLOREN - im Zweifel Laserschalter "
                          "von Hand aus!"))
            messagebox.showwarning(T("Verbindung verloren"),
                T("Die USB-Verbindung ist abgerissen.\nIch versuche Halt + Laser aus zu senden.\n\n"
                  "Im Zweifel: Laserschalter von Hand aus!"))
        elif k == "lost_secured":
            self._log(T('Halt + M5 an {0} gesendet. Neu verbinden, Nullpunkt neu setzen.').format(d))
            self.cb_port.configure(values=G.ports())
            self.v_port.set(d)
        elif k == "lost_unsecured":
            self._log(T("Controller nicht erreichbar - LASERSCHALTER VON HAND AUS!"))
            messagebox.showerror(T("Laser"), T("Controller nicht erreichbar.\nLaserschalter von Hand aus!"))
        elif k == "msg":
            self._log(d)
        elif k == "einstellungen":
            self._einstellungen_pruefen(d)
        elif k == "fernlabel":
            self._fern_label()
        elif k == "fern":
            aktion, wert, antwort = d
            try:
                antwort.put(self.fern_tun(aktion, wert))
            except Exception as e:
                antwort.put(T("Fehler: {e}").format(e=e))

    # ============================================================ Telegram
    def _marke_text(self, done):
        """Bei welcher Zeile oder Kontur steht er gerade?

        Wie der Schichtzaehler am 3D-Drucker: der Prozentwert sagt wenig
        darueber, wo im Bild der Kopf ist.
        """
        if not getattr(self, "_marken_idx", None):
            return ""
        i = bisect.bisect_right(self._marken_idx, done) - 1
        if i < 0:
            return ""
        _, art, nr, gesamt = self.marken[i]
        return (T("Zeile {nr} von {n}") if art == "zeile"
                else T("Kontur {nr} von {n}")).format(nr=nr, n=gesamt)

    def _melde(self, t):
        if self.fern is not None:
            self.fern.melde(t)

    def fern_tun(self, aktion, wert=None):
        """Auftrag vom Handy. Laeuft im Hauptthread, gibt Text zurueck und
        oeffnet nie einen Dialog - den sieht am Werkstueck niemand."""
        g = self.grbl
        if aktion == "status":
            return (T("{zustand} ({port}), {job}\n{pos}\n"
                      "Nullpunkt: {null}, Z-Ref: {zref}").format(
                        zustand=T("verbunden") if g.connected else T("nicht verbunden"),
                        port=g.port or "-",
                        job=T("Job laeuft") if g.job_running else T("kein Job"),
                        pos=self.fern.position(),
                        null=T("gesetzt") if self.zero_ok else T("NICHT gesetzt"),
                        zref=T("gültig") if self.zref_ok else T("fehlt"))
                    + (f"\n{self.lbl_prog.cget('text')}" if g.job_running else ""))
        if aktion == "aus":
            g.laser_off(); self._log(T("Laser aus (Telegram)"))
            return T("M5 gesendet - Laser aus.")
        # Pause und Weiter gehoeren vor die Jobsperre weiter unten: sie
        # ergeben ueberhaupt nur Sinn, waehrend ein Job laeuft.
        if aktion == "pause":
            if not g.connected:
                return T("Nicht verbunden.")
            if not g.job_running:
                return T("Es läuft kein Job.")
            if g.pausiert:
                return T("Steht schon. /weiter macht weiter.")
            self.pause()
            return (T("Pause angemeldet - er hält am Ende der laufenden Zeile.")
                    if self.v_pause_ende.get()
                    else T("Feed Hold - Laser aus. /weiter macht weiter."))
        if aktion == "weiter":
            if not g.connected:
                return T("Nicht verbunden.")
            if not g.job_running:
                return T("Es läuft kein Job.")
            self.resume()
            return T("Weiter.")
        if aktion == "stopp":
            if not g.connected:
                return T("Nicht verbunden.")
            # Ueber self.stop(), nicht ueber g.stop(): nur dort wird der
            # Nullpunkt vor dem Soft-Reset gemerkt. Am Knopf ueberlebte er,
            # vom Handy aus war er jedes Mal weg.
            self.stop()
            self._log(T("STOPP (Telegram)"))
            return T("STOPP: Halt und Soft-Reset. Nullpunkt wird "
                     "wiederhergestellt.")
        if not g.connected:
            return T("Nicht verbunden.")
        if g.job_running:
            return T("Es läuft ein Job - frei sind nur /status, /pause, "
                     "/weiter, /aus und /stopp.")
        if aktion == "frei":
            self._log(T("Entsperrt (Telegram)"))
            antwort = g.unlock()
            # Nach einem STOPP wartet der Nullpunkt auf das Entsperren. Am
            # Knopf wurde er danach gesetzt, vom Handy aus nicht.
            if self._rettbar():
                self._bg(self._nullpunkt_retten, None)
            return f"$X -> {antwort}"
        if g.alarm:
            return g.alarm + T("\nErst entsperren: /frei")
        if aktion == "pos":
            return self.fern.position()
        if aktion == "jog":
            achse, mm = wert
            dx, dy, dz = {"x": (mm, 0, 0), "y": (0, mm, 0),
                          "z": (0, 0, self._zv(mm))}[achse]
            g.jog(dx, dy, dz, feed=self.cfg.get("jog_feed", 1000))
            return ""                 # leer: der Bot meldet danach die Position
        if aktion == "kreuz":
            sv = self._zeig_s()
            arm = max(0.5, min(float(self.v_zeig_a.get()), 8.0))
            self._log(T('Kreuz S{0} (Telegram)').format(sv))
            self._bg(lambda: [g.cmd(c) for c in
                              J.kreuz_lines(self._s(sv), J.POINTER_FEED, arm)], None)
            return T("Kreuz {mm:.1f} mm bei S{s}").format(mm=2 * arm, s=sv)
        if aktion == "null":
            g.set_zero_xy(); self.zero_ok = True
            self._null_merken_xy()
            self._log(T("Nullpunkt XY gesetzt (Telegram)"))
            return T("Nullpunkt XY = hier.")
        if aktion == "nullzurueck":
            self._log(T("Nullpunkt zurückholen (Telegram)"))
            return self.nullpunkt_zurueck()
        if aktion == "heim":
            self._bg(lambda: g.goto(x=0, y=0), T("fahre zum Nullpunkt (Telegram)"))
            return T("fahre zum Nullpunkt")
        return T("Unbekannter Auftrag.")

    def fern_start(self):
        if self.fern is not None and self.fern.aktiv:
            self.fern.stop(); self.fern = None
            self._fern_label(); self._log(T("Telegram: angehalten"))
            return
        d = TG.lade()
        # Der Token darf auch von Hand in der Datei stehen - ein leeres Feld
        # loescht ihn dann nicht.
        tok = self.v_tg_token.get().strip() or d.get("token", "").strip()
        if not tok:
            messagebox.showinfo(T("Telegram"),
                T("Erst den Token vom BotFather eintragen -\n"
                  "hier im Feld oder in\n") + TG.DATEI)
            return
        self.v_tg_token.set(tok)
        d["token"] = tok; d["auto"] = bool(self.v_tg_auto.get())
        TG.sichere(d)
        self.fern = TG.Fern(self)
        def an():
            try:
                name = self.fern.start()
                self.q.put(("msg", T("Telegram: @{name} laeuft").format(name=name)
                            + ("" if self.fern.chat
                               else T(" - jetzt /start im Chat senden"))))
            except Exception as e:
                self.fern = None
                self.q.put(("msg", f"Telegram: {e}"))
            self.q.put(("fernlabel", None))
        threading.Thread(target=an, daemon=True).start()
        self._fern_label()

    def _tg_auto(self):
        d = TG.lade(); d["auto"] = bool(self.v_tg_auto.get()); TG.sichere(d)

    def fern_loesen(self):
        d = TG.lade(); d["chat"] = None; TG.sichere(d)
        if self.fern is not None:
            self.fern.chat = None
        self._log(T("Telegram: Verknuepfung geloest - der naechste /start uebernimmt."))
        self._fern_label()

    def _fern_label(self):
        if self.fern is None or not self.fern.aktiv:
            t = "aus"
        elif not self.fern.chat:
            t = T("wartet auf /start im Chat")
        else:
            t = T("laeuft, Chat {chat}").format(chat=self.fern.chat)
        self.lbl_tg.configure(text=t)
        self.btn_tg.configure(text=T("Bot anhalten") if (self.fern and self.fern.aktiv)
                              else T("Bot starten"))

    LOGZEILEN = 2000

    def _fehler_melden(self, art, wert, spur):
        """Ein Fehler in der Oberflaeche - sichtbar statt spurlos.

        tkinter schreibt ihn sonst auf die Standardfehlerausgabe. Die gibt
        es nicht, wenn das Programm aus dem Menue gestartet wurde: das
        Fenster steht da, als waere nichts gewesen, und die Haelfte eines
        Vorgangs ist einfach nicht passiert. Jetzt steht die Spur im
        Protokoll und vollstaendig in derselben Datei wie die Haenger.
        """
        text = "".join(traceback.format_exception(art, wert, spur))
        try:
            with open(os.path.join(P.DIR, HAENGERDATEI), "a") as f:
                f.write("\n==== %s: Fehler in der Oberflaeche ====\n%s"
                        % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
        except OSError:
            pass
        if not hasattr(self, "log"):
            traceback.print_exception(art, wert, spur)
            return
        self._log(T("Fehler: {0}: {1}").format(art.__name__, wert))
        for zeile in text.rstrip().splitlines()[1:-1][-4:]:
            self._log("    " + zeile.strip())
        self._log(T("Ganze Spur in {0}").format(
            os.path.join(P.DIR, HAENGERDATEI)))

    def _log(self, t):
        self.log.insert("end", f"{time.strftime('%H:%M:%S')} {t}\n")
        # Begrenzen: ein Textfeld mit hunderttausend Zeilen frisst Speicher,
        # und jedes see('end') wird langsamer, bis das Fenster steht.
        zeilen = int(self.log.index("end-1c").split(".")[0])
        if zeilen > self.LOGZEILEN:
            self.log.delete("1.0", "%d.0" % (zeilen - self.LOGZEILEN + 1))
        self.log.see("end")

    # ================================================================ Zeichnen
    def _cv(self):
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        return (w if w > 1 else CANVAS), (h if h > 1 else CANVAS)

    def _scale(self):
        w, h = self._cv()
        return self._grundmass() * self.zoom

    def _grundmass(self):
        """Massstab, bei dem der ganze Verfahrweg ins Fenster passt - nach
        Breite UND Hoehe, sonst verschenkt eine flache Maschine die Haelfte."""
        w, h = self._cv()
        return min((w - 20) / max(10.0, float(self.cfg["x_max"])),
                   (h - 20) / max(10.0, float(self.cfg["y_max"])))

    def _resized(self, e):
        """Fenster groesser: Ansicht unten links verankert lassen."""
        alt_w, alt_h = self._cvsize
        self._cvsize = (e.width, e.height)
        if self.zoom == 1.0:
            self.reset_view()
            return
        self.oy += e.height - alt_h
        self._draw()

    def _mm(self, x, y):
        s = self._scale()
        return self.ox + x * s, self.oy - y * s

    def _mm_zurueck(self, x, y):
        """Bildpunkt auf der Flaeche zurueck in Millimeter - Gegenstueck
        zu _mm."""
        s = self._scale()
        return (x - self.ox) / s, (self.oy - y) / s

    def _wheel(self, e):
        """Mausrad: zoomen, wobei der Punkt unter dem Zeiger stehen bleibt."""
        rauf = getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0
        f = 1.15 if rauf else 1 / 1.15
        neu = max(0.3, min(self.zoom * f, 25.0))
        if neu == self.zoom:
            return
        s1 = self._scale()
        s2 = self._grundmass() * neu
        mx, my = (e.x - self.ox) / s1, (self.oy - e.y) / s1
        self.zoom = neu
        self.ox, self.oy = e.x - mx * s2, e.y + my * s2
        self._draw()

    def _pan_start(self, e):
        self._pan = (e.x, e.y)

    def _pan_move(self, e):
        if not hasattr(self, "_pan"):
            return
        self.ox += e.x - self._pan[0]
        self.oy += e.y - self._pan[1]
        self._pan = (e.x, e.y)
        self._draw()

    def reset_view(self):
        self.zoom = 1.0
        w, h = self._cv()
        s = self._grundmass()
        # mittig einpassen statt unten links kleben - bei einer flachen
        # Maschine bleibt sonst oben ein breiter leerer Streifen
        self.ox = max(10, (w - float(self.cfg["x_max"]) * s) / 2)
        self.oy = h - max(10, (h - float(self.cfg["y_max"]) * s) / 2)
        self._draw()

    def _draw(self):
        cv = self.cv
        cv.delete("all")
        # Die Flaeche ist so breit und so hoch wie der Verfahrweg - nicht
        # quadratisch. Sonst sieht ein Brett aus, als passe es nicht.
        wx, wy = float(self.cfg["x_max"]), float(self.cfg["y_max"])
        x0, y0 = self._mm(0, 0)
        x1, y1 = self._mm(wx, wy)
        cv.create_rectangle(x0, y1, x1, y0, outline=S.CANVAS_EDGE)
        self._kamera_unterlegen(x0, y0, x1, y1)
        s = self._scale()
        if s >= 6:                      # weit hineingezoomt: 1-mm-Raster dazu
            for m in range(0, int(wx) + 1):
                if m % 10:
                    a, _ = self._mm(m, 0)
                    cv.create_line(a, y0, a, y1, fill=S.CANVAS_GRID)
            for m in range(0, int(wy) + 1):
                if m % 10:
                    _, b = self._mm(0, m)
                    cv.create_line(x0, b, x1, b, fill=S.CANVAS_GRID)
        for m in range(10, int(wx), 10):
            a, _ = self._mm(m, 0)
            cv.create_line(a, y0, a, y1, fill=S.CANVAS_GRID if m % 50 else S.CANVAS_GRID2)
        for m in range(10, int(wy), 10):
            _, b = self._mm(0, m)
            cv.create_line(x0, b, x1, b, fill=S.CANVAS_GRID if m % 50 else S.CANVAS_GRID2)
        for m in range(50, int(wx), 50):
            a, _ = self._mm(m, 0); cv.create_text(a, y0 + 1, text=str(m), anchor="n", fill=S.MUTED, font=("sans", 7))
        if self.v_board.get():
            W, H = float(self.v_bw.get()), float(self.v_bh.get())
            ax, ay = self._mm(0, H); bx2, by2 = self._mm(W, 0)
            cv.create_rectangle(ax, ay, bx2, by2, fill="#8a6a42" if S.THEME == "dunkel"
                                else "#e8d7bd", outline="#6b4f2f", width=2)
            mx, _ = self._mm(W / 2, 0); _, my = self._mm(0, H / 2)
            cv.create_line(mx, ay, mx, by2, fill="#6b4f2f", dash=(3, 3))
            cv.create_line(ax, my, bx2, my, fill="#6b4f2f", dash=(3, 3))
        box = self._box()
        # Alle Elemente zeigen - das gewaehlte bekommt zusaetzlich den
        # Rahmen mit den Anfassern.
        for i, e in enumerate(self.elemente):
            r = e.get("ergebnis")
            gemalt = False
            if r:
                bild, pos = self._vorschau(e)
                if bild is not None:
                    cv.create_image(*self._mm(*pos), image=bild, anchor="nw")
                    gemalt = True
                for pl in (r.get("cut_polys") or ()):
                    pts = [c for p in pl["pts"] for c in self._mm(*p)]
                    if pl["closed"]:
                        pts += list(self._mm(*pl["pts"][0]))
                    if len(pts) >= 4:
                        cv.create_line(*pts, fill=S.DANGER, width=1)
                        gemalt = True
            if gemalt:
                continue
            if i == self.aktiv and box and self.src is not None:
                x, y, b, h = box
                img = self._live_image(b, h)
            else:                       # noch nicht erzeugt: trotzdem zeigen
                kasten = self._box_von(e)
                if not kasten:
                    continue
                x, y, b, h = kasten
                img = self._bild_von(e, b, h)
            if img is not None:
                cv.create_image(*self._mm(x, y + h), image=img, anchor="nw")
            else:
                a1, b1 = self._mm(x, y + h)
                a2, b2 = self._mm(x + b, y)
                cv.create_rectangle(a1, b1, a2, b2, outline=S.MUTED, dash=(2, 4))
        if not self.elemente and self.preview_pil is not None and self.preview_pos:
            ax, ay = self._mm(*self.preview_pos)     # geladener G-Code
            self._prepare_preview()
            if self.preview_img is not None:
                cv.create_image(ax, ay, image=self.preview_img, anchor="nw")
        if box:                         # Rahmen und Anfasser des gewaehlten
            x, y, b, h = box
            ax, ay = self._mm(x, y + h)
            cx, cy = self._mm(x + b, y)
            cv.create_rectangle(ax, ay, cx, cy, outline=S.ACCENT, dash=(3, 2))
            for hx, hy in ((ax, ay), (cx, ay), (ax, cy), (cx, cy)):
                cv.create_rectangle(hx - 4, hy - 4, hx + 4, hy + 4,
                                    fill=S.ACCENT, outline="")
            # Griff zum Drehen: ueber der Oberkante, am Stiel. Dort, wo ihn
            # jedes Zeichenprogramm hat - und weit genug weg, dass er nicht
            # mit dem Eckgriff verwechselt wird.
            gx, gy = (ax + cx) / 2, min(ay, cy) - self.DREHGRIFF
            self._drehgriff = (gx, gy)
            cv.create_line(gx, min(ay, cy), gx, gy + 5, fill=S.ACCENT,
                           dash=(2, 2))
            cv.create_oval(gx - 5, gy - 5, gx + 5, gy + 5, outline=S.ACCENT,
                           width=2)
            cv.create_text((ax + cx) / 2, min(ay, cy) - self.DREHGRIFF - 10,
                           fill=S.ACCENT, anchor="s",
                           text=T('{b} x {h} mm').format(b=Z(b, 1), h=Z(h, 1))
                           + (T('   {g}°').format(g=Z(self.v_rot.get(), 1))
                              if abs(float(self.v_rot.get() or 0)) > 0.05
                              else ""))
        if self.lines and not box:      # geladener G-Code ohne Motiv
            ex = J.brenn_extent(self.lines)
            a, b = self._mm(ex[0], ex[3]); c, d = self._mm(ex[1], ex[2])
            cv.create_rectangle(a, b, c, d, outline=S.ACCENT, dash=(2, 2))
        cv.create_oval(x0 - 4, y0 - 4, x0 + 4, y0 + 4, outline=S.DANGER, width=2)
        if abs(self.zoom - 1.0) > 0.01:
            cv.create_text(self._cv()[0] - 8, 8, anchor="ne", fill=S.MUTED,
                           text=T('{0:.1f}x   Mausrad = Zoom, mittlere/rechte Taste = schieben').format(self.zoom))
        self._draw_head()
        self._raender_zeigen()

    def _brett_geaendert(self):
        """Brettchen neu zeichnen und die Masse fuer die naechste Sitzung merken."""
        try:
            self.cfg["brett_x"] = float(self.v_bw.get())
            self.cfg["brett_y"] = float(self.v_bh.get())
        except tk.TclError:
            return
        self.cfg["brett_an"] = bool(self.v_board.get())
        self.cfg["einrasten"] = bool(self.v_snap.get())
        P.save_config(self.cfg)
        self._draw()

    def _box_von(self, e):
        """Motivrechteck eines Elements aus seinen gespeicherten Werten."""
        try:
            b, h = float(e["v_w"]), float(e["v_h"])
            x, y = float(e["v_xoff"]), float(e["v_yoff"])
        except (KeyError, TypeError, ValueError):
            return None
        if e.get("v_job") == "schnitt" and e.get("vec"):
            x0, y0, x1, y1 = V.bbox(V.rotate(V.flatten(e["vec"], 1.0),
                                             float(e.get("v_rot", 0) or 0)))
            bw, bh = x1 - x0, y1 - y0
            if bw > 0 and bh > 0:
                sc = min(b / bw, h / bh)
                b, h = bw * sc, bh * sc
        sp = e.get("v_spiegel", "nein")
        a = float(e.get("v_achse", 50.0))
        if sp == "x":
            x = 2 * a - x - b
        elif sp == "y":
            y = 2 * a - y - h
        return x, y, b, h

    @staticmethod
    def _auf_inhalt(im):
        """Das gedrehte Bild auf seinen Inhalt zuschneiden.

        rotate(expand=True) legt weisse Zwickel um das Motiv. In den Rahmen
        gezogen, der genau um den Inhalt liegt, waere das Motiv darin zu
        klein - es schwaemme mit Luft ringsum in seinem eigenen Kasten.
        """
        try:
            kasten = im.point(lambda v: 255 if v < 245 else 0).getbbox()
        except ValueError:            # kein Graustufenbild
            return im
        return im.crop(kasten) if kasten else im

    def _bild_von(self, e, b, h):
        """Das Motiv eines Elements als durchscheinendes Bild - fuer alle
        Elemente, nicht nur das gewaehlte. Sonst sieht man von den anderen
        nur ein Rechteck und weiss nicht, was darin steht."""
        im0 = e.get("src")
        if im0 is None:
            return None
        s = self._scale()
        w_px, h_px = max(1, int(b * s)), max(1, int(h * s))
        if w_px * h_px > 4_000_000:
            return None
        schluessel = (w_px, h_px, e.get("v_rot"), e.get("v_inv"),
                      e.get("v_spiegel"), round(e.get("v_hell", 0)),
                      round(e.get("v_kontrast", 0)), round(e.get("v_schaerfe", 0)))
        if e.get("_lcache", (None,))[0] == schluessel:
            return e["_lcache"][1]
        im = im0
        rot = float(e.get("v_rot", 0) or 0)
        if rot:
            im = self._auf_inhalt(im.rotate(-rot, expand=True, fillcolor=255))
        if e.get("v_spiegel") == "x":
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        elif e.get("v_spiegel") == "y":
            im = im.transpose(Image.FLIP_TOP_BOTTOM)
        im = im.resize((w_px, h_px), Image.BILINEAR)
        im = J.bildkorrektur(im, e.get("v_hell", 0), e.get("v_kontrast", 0),
                             e.get("v_schaerfe", 0))
        if e.get("v_inv"):
            from PIL import ImageOps
            im = ImageOps.invert(im)
        alpha = im.point(lambda v: 255 - v)
        im = Image.merge("RGBA", (im.point(lambda v: 60), im.point(lambda v: 38),
                                  im.point(lambda v: 24), alpha))
        b64 = io.BytesIO()
        im.save(b64, format="PNG")
        e["_lcache"] = (schluessel,
                        tk.PhotoImage(data=base64.b64encode(b64.getvalue())))
        return e["_lcache"][1]

    def _box(self):
        """Motivrechteck in Werkstueckkoordinaten (x, y, b, h), inkl. Rueckseite."""
        if self.src is None and not self.vec:
            return None
        try:
            b, h = float(self.v_w.get()), float(self.v_h.get())
            x, y = float(self.v_xoff.get()), float(self.v_yoff.get())
        except tk.TclError:
            return None
        if self.v_job.get() == "schnitt" and self.vec:
            # V.fit setzt die Konturen seitenverhaeltnistreu in den Rahmen und
            # legt sie an die linke untere Ecke. Dann ist der gezeichnete
            # Kasten groesser als der Schnitt - und "mittig" waere daneben.
            bw, bh = self._vec_dreh_bb()
            if bw > 0 and bh > 0:
                # Mit Haken behaelt der Schnitt sein Seitenverhaeltnis und
                # sitzt deshalb kleiner im Rahmen - ohne Haken fuellt er ihn
                # genau aus, so wie V.fit dann rechnet.
                if self.v_lock.get():
                    sc = min(b / bw, h / bh)
                    b, h = bw * sc, bh * sc
            elif bw > 0:              # waagrechte Linie: keine Hoehe
                h = 0.0
            elif bh > 0:              # senkrechte Linie: keine Breite
                b = 0.0
        sp, a = self.v_spiegel.get(), float(self.v_achse.get())
        if sp == "x":
            x = 2 * a - x - b
        elif sp == "y":
            y = 2 * a - y - h
        return x, y, b, h

    def _set_box(self, x, y, b=None, h=None):
        """Rechteck zurueckrechnen auf die Eingabefelder (Rueckseite beachten)."""
        sp, a = self.v_spiegel.get(), float(self.v_achse.get())
        if b is not None: self.v_w.set(round(b, 2))
        if h is not None: self.v_h.set(round(h, 2))
        bb = float(self.v_w.get()); hh = float(self.v_h.get())
        if sp == "x": x = 2 * a - x - bb
        elif sp == "y": y = 2 * a - y - hh
        self.v_xoff.set(round(max(self._xmin(), x), 2))
        self.v_yoff.set(round(max(0.0, y), 2))

    def _xmin(self):
        """Beim Gravieren muss links vom Motiv der Anlauf hinpassen."""
        if getattr(self, "v_job", None) is None or \
                self.v_job.get() not in ("gravur", "beides"):
            return 0.0
        return self._anlauf()

    def _snap(self, wert, ziele, tol):
        if not self.v_snap.get():
            return wert
        best = min(ziele, key=lambda z: abs(z - wert))
        return best if abs(best - wert) <= tol else wert

    DREHGRIFF = 22          # Bildpunkte ueber der Oberkante

    def _griff_unter(self, e):
        """Was liegt unter dem Zeiger: ein Eckgriff, der Drehgriff, das
        Motiv selbst - oder nichts. Eine Stelle fuer beides, den Klick und
        die Zeigerform; sonst fassen sie verschiedene Dinge."""
        box = self._box()
        if box is None:
            return None, None, None
        x, y, b, h = box
        px, py = self._mm(x, y + h)                  # linke obere Ecke
        qx, qy = self._mm(x + b, y)                  # rechte untere Ecke
        gx, gy = (px + qx) / 2, min(py, qy) - self.DREHGRIFF
        if abs(e.x - gx) <= 9 and abs(e.y - gy) <= 9:
            return "dreh", None, box
        ecken = {"ul": (px, py), "ur": (qx, py), "ol": (px, qy), "or": (qx, qy)}
        for name, (cx, cy) in ecken.items():
            if abs(e.x - cx) <= 9 and abs(e.y - cy) <= 9:
                return "size", name, box
        # Ein Rahmen ohne Hoehe (gerade Linie) waere sonst gar nicht zu
        # greifen - nur bei duennen Rahmen etwas Luft geben, sonst nicht.
        lx = 0 if abs(qx - px) > 6 else 4
        ly = 0 if abs(qy - py) > 6 else 4
        if min(px, qx) - lx <= e.x <= max(px, qx) + lx and \
                min(py, qy) - ly <= e.y <= max(py, qy) + ly:
            return "move", None, box
        return None, None, box

    ZEIGER = {("size", "ul"): "top_left_corner",
              ("size", "ur"): "top_right_corner",
              ("size", "ol"): "bottom_left_corner",
              ("size", "or"): "bottom_right_corner",
              ("dreh", None): "exchange",
              ("move", None): "fleur"}

    def _drag_ende(self, e):
        self.drag = None
        self._zeiger(e)

    def _zeiger(self, e):
        """Die Zeigerform sagt, was ein Klick hier taete.

        Ohne sie sieht ein Eckgriff aus wie der Rahmen und der Drehgriff
        wie ein Punkt - man probiert, statt zu sehen.
        """
        if self.drag:
            return
        art, ecke, _ = self._griff_unter(e)
        form = self.ZEIGER.get((art, ecke), "")
        if form != getattr(self, "_zeigerform", None):
            self._zeigerform = form
            try:
                self.cv.configure(cursor=form)
            except tk.TclError:
                self.cv.configure(cursor="")        # Form kennt dieses X11 nicht

    def _press(self, e):
        art, ecke, box = self._griff_unter(e)
        if art is None:
            return
        self.drag = (art, ecke, box, (e.x, e.y),
                     float(self.v_rot.get() or 0.0))

    def _drag_move(self, e):
        if not self.drag:
            return
        self.preview_pil = self.preview_img = self.cut_polys = None
        art, ecke, (bx, by, bb, bh), (sx, sy), grad0 = self.drag
        s = self._scale()
        if art == "dreh":
            # Winkel zwischen Mitte und Zeiger, Anfang gegen Jetzt.
            #
            # Hier stand ein Minus, begruendet damit, dass der Schirm Y nach
            # unten zaehlt und die Maschine nach oben. Das Vorzeichen hebt
            # sich aber zweimal auf: ein positives v_rot dreht das Motiv im
            # Werkstueck rechtsherum (V.rotate), und weil die Zeichnung Y
            # spiegelt, sieht man es auf dem Schirm ebenfalls rechtsherum.
            # Der Winkel hier wird in Schirmkoordinaten gemessen, waechst
            # also auch rechtsherum - ohne Minus folgt das Motiv der Hand.
            # Mit Minus drehte es dagegen, und der Griff drehte andersherum
            # als derselbe Winkel im Zahlenfeld.
            mx, my = self._mm(bx + bb / 2, by + bh / 2)
            a0 = math.degrees(math.atan2(sy - my, sx - mx))
            a1 = math.degrees(math.atan2(e.y - my, e.x - mx))
            grad = (grad0 + (a1 - a0)) % 360
            if self.v_snap.get():
                grad = round(grad / 15.0) * 15.0 % 360
            self.v_rot.set(grad)
            self._rotated()         # derselbe Weg wie Knopf und Zahlenfeld
            self._draw()
            return
        dx, dy = (e.x - sx) / s, -(e.y - sy) / s
        W, H = float(self.v_bw.get()), float(self.v_bh.get())
        tol = 7 / s                                   # Einrasten: 7 Bildpunkte
        if art == "move":
            x, y = bx + dx, by + dy
            x = self._snap(x, [self._xmin(), (W - bb) / 2, W - bb], tol)
            y = self._snap(y, [0, (H - bh) / 2, H - bh], tol)
            self._set_box(x, y)
        else:
            links = ecke in ("ul", "ol")
            unten = ecke in ("ol", "or")
            nb = bb + (-dx if links else dx)
            nh = bh + (-dy if unten else dy)
            if self.v_lock.get() and bb > 0 and bh > 0:   # Verhaeltnis halten
                nb = max(nb, 1.0); nh = nb * bh / bb
            # Mindestmass nur dort, wo die Vorlage ueberhaupt Ausdehnung hat.
            # Einer geraden Linie 2 mm Hoehe aufzuzwingen hat den Rahmen vom
            # Schnitt geloest und das Ziehen bei 2 mm festgenagelt.
            qb, qh = self._bezug_bb()
            nb = max(2.0, nb) if qb > 0 else 0.0
            nh = max(2.0, nh) if qh > 0 else 0.0
            x = bx + bb - nb if links else bx
            y = by + bh - nh if unten else by
            # Kanten und Mitte des Werkstuecks als Rastpunkte
            if links:
                x = self._snap(x, [self._xmin(), (W - nb) / 2], tol)
                nb = bx + bb - x
            else:
                rechts = self._snap(x + nb, [W, W / 2], tol); nb = rechts - x
            if self.v_lock.get() and bb > 0 and bh > 0:
                nh = nb * bh / bb
                if unten: y = by + bh - nh
            self._set_box(x, y, nb, nh)
        self._draw()

    def _raender_zeigen(self):
        """Die vier Abstaende aus der aktuellen Lage nachtragen."""
        kasten = self._box()
        if not kasten or not hasattr(self, "v_rand"):
            return
        x, y, b, h = kasten
        try:
            W, H = float(self.v_bw.get()), float(self.v_bh.get())
        except tk.TclError:
            return
        for seite, wert in (("l", x), ("r", W - x - b),
                            ("u", y), ("o", H - y - h)):
            self.v_rand[seite].set(round(wert, 1))
            # Ein negativer Rand ist keine Zahl wie jede andere: so weit
            # haengt das Motiv ueber das Werkstueck hinaus.
            feld = getattr(self, "e_rand", {}).get(seite)
            if feld is not None:
                feld.configure(style="Warn.TEntry" if wert < -0.05
                               else "TEntry")

    def _rand_setzen(self, seite):
        """Eingetippten Abstand in eine Lage umrechnen."""
        kasten = self._box()
        if not kasten:
            return
        x, y, b, h = kasten
        try:
            W, H = float(self.v_bw.get()), float(self.v_bh.get())
            v = float(self.v_rand[seite].get())
        except tk.TclError:
            return
        if seite == "l":
            x = v
        elif seite == "r":
            x = W - b - v
        elif seite == "u":
            y = v
        else:
            y = H - h - v
        self._set_box(x, y)
        self._raender_zeigen()
        self._draw()

    def center_motif(self):
        box = self._box()
        if box is None:
            return
        _, _, b, h = box
        W, H = float(self.v_bw.get()), float(self.v_bh.get())
        self._set_box((W - b) / 2, (H - h) / 2)
        self._draw()

    def _live_image(self, b, h):
        """Motiv als Bild in der aktuellen Groesse - unabhaengig vom G-Code."""
        if self.src is None:
            return None
        s = self._scale()
        w_px, h_px = max(1, int(b * s)), max(1, int(h * s))
        if w_px * h_px > 4_000_000:        # zu weit hineingezoomt: nur Rahmen
            return None
        # waehrend des Ziehens grob skalieren, danach sauber
        glatt = Image.BILINEAR if self.drag else Image.LANCZOS
        rot, inv, sp = self.v_rot.get(), self.v_inv.get(), self.v_spiegel.get()
        bk = (round(self.v_hell.get()), round(self.v_kontrast.get()),
              round(self.v_schaerfe.get()))
        key = (w_px, h_px, rot, inv, sp, glatt, bk, id(self.src))
        if self._live_cache and self._live_cache[0] == key:
            return self._live_cache[1]
        im = self.src
        if rot:
            im = self._auf_inhalt(im.rotate(-rot, expand=True, fillcolor=255))
        if sp == "x":
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        elif sp == "y":
            im = im.transpose(Image.FLIP_TOP_BOTTOM)
        im = im.resize((w_px, h_px), glatt)
        im = J.bildkorrektur(im, *bk)
        if inv:
            from PIL import ImageOps
            im = ImageOps.invert(im)
        # Helle Stellen durchsichtig, dunkle als Brandspur: so bleibt das
        # Brettchen sichtbar und die Lage ist beurteilbar wie am Werkstueck.
        alpha = im.point(lambda v: 255 - v)
        im = Image.merge("RGBA", (im.point(lambda v: 60), im.point(lambda v: 38),
                                  im.point(lambda v: 24), alpha))
        b64 = io.BytesIO(); im.save(b64, format="PNG")
        img = tk.PhotoImage(data=base64.b64encode(b64.getvalue()))
        self._live_cache = (key, img)
        return img

    def _vorschau(self, e):
        """Erzeugte Vorschau eines Elements als Bild in der aktuellen
        Zoomstufe. Jedes Element haelt seinen eigenen Zwischenspeicher."""
        r = e.get("ergebnis")
        if not r or r.get("preview_pil") is None or not r.get("preview_pos"):
            return None, None
        i = r["info"]
        s = self._scale()
        w = max(1, min(int(i["breite"] * s), 4000))
        h = max(1, min(int(i["hoehe"] * s), 4000))
        if e.get("_cache", (None,))[0] != (w, h):
            im = r["preview_pil"].resize((w, h), Image.LANCZOS)
            alpha = im.point(lambda v: 255 - v)
            im = Image.merge("RGBA", (im.point(lambda v: 60),
                                      im.point(lambda v: 38),
                                      im.point(lambda v: 24), alpha))
            b = io.BytesIO()
            im.save(b, format="PNG")
            e["_cache"] = ((w, h),
                           tk.PhotoImage(data=base64.b64encode(b.getvalue())))
        return e["_cache"][1], r["preview_pos"]

    def _prepare_preview(self):
        """Vorschaubild in der aktuellen Zoomstufe bereitstellen (zwischengespeichert)."""
        s = self._scale()
        w = max(1, min(int(self.info["breite"] * s), 4000))
        h = max(1, min(int(self.info["hoehe"] * s), 4000))
        if self._prev_cache and self._prev_cache[0] == (w, h):
            self.preview_img = self._prev_cache[1]
            return
        import io
        im = self.preview_pil.resize((w, h), Image.LANCZOS)
        # Helle Stellen durchsichtig lassen, sonst deckt ein weisser Kasten
        # das Brettchen zu und man sieht die Lage nicht mehr.
        alpha = im.point(lambda v: 255 - v)
        im = Image.merge("RGBA", (im.point(lambda v: 60), im.point(lambda v: 38),
                                  im.point(lambda v: 24), alpha))
        b = io.BytesIO(); im.save(b, format="PNG")
        self.preview_img = tk.PhotoImage(data=base64.b64encode(b.getvalue()))
        self._prev_cache = ((w, h), self.preview_img)

    def _draw_head(self):
        self.cv.delete("head")
        h = getattr(self, "head", None)
        if not h:
            return
        x, y = self._mm(*h)
        self.cv.create_line(x - 8, y, x + 8, y, fill="#e00", width=2, tags="head")
        self.cv.create_line(x, y - 8, x, y + 8, fill="#e00", width=2, tags="head")


HAENGERDATEI = "haenger.txt"
_haenger_f = None          # offen halten, sonst schreibt faulthandler ins Leere


def spur(text):
    """Eine Zeile sofort in die Haengerdatei.

    Fuer Schritte, die ein Absturz nicht ueberleben soll. Das Protokoll
    im Fenster ist dann weg, die Datei nicht - und bei einem Absturz ohne
    Signal und ohne Spur ist die letzte geschriebene Zeile die einzige
    Auskunft darueber, wie weit es gekommen ist.
    """
    if _haenger_f is None:
        return
    try:
        _haenger_f.write("%s %s\n" % (time.strftime("%H:%M:%S"), text))
    except (OSError, ValueError):
        pass


def haenger_dauer(puls, start, jetzt, dialoge=0):
    """Wie lange die Oberflaeche schon steht. Null heisst: alles in Ordnung.

    Zwei Faelle sind kein Haenger und standen trotzdem in der Datei:

      * Ein Dialog wartet auf einen Menschen. Der Hauptthread steht dann
        in subprocess.run und atmet nicht - dafuer kann er nichts.
      * Das Programm ist gerade erst gestartet und hatte noch keinen
        Herzschlag. Dann rechnete der Wachhund gegen die Null und meldete
        "steht seit 1793962100 s", also seit dem 1. Januar 1970.

    Ohne Puls zaehlt deshalb die Startzeit. Bleibt es danach wirklich
    still, meldet der Wachhund das weiterhin - und dann heisst es auch
    etwas: die Schleife, die alle hundert Millisekunden laufen soll, laeuft
    nicht mehr.
    """
    if dialoge:
        return 0.0
    return jetzt - (puls or start)


def haenger_spuren(app=None, grenze=20.0):
    """Spuren aller Threads sichern, wenn die Oberflaeche stehenbleibt.

    Zwei Wege in dieselbe Datei:
      * von Hand:  kill -USR1 $(pgrep -f laserwerk.py)
      * von selbst: der Wachhund merkt, dass der Hauptthread nicht mehr
        atmet, und schreibt die Spuren ohne Zutun.

    Ohne das steht man hinterher vor einem eingefrorenen Fenster und hat
    nichts in der Hand - genau das ist passiert.
    """
    global _haenger_f
    import faulthandler, signal, threading
    try:
        os.makedirs(P.DIR, exist_ok=True)
        pfad = os.path.join(P.DIR, HAENGERDATEI)
        _haenger_f = open(pfad, "a", buffering=1)
        faulthandler.enable(file=_haenger_f, all_threads=True)
        if hasattr(signal, "SIGUSR1"):
            faulthandler.register(signal.SIGUSR1, file=_haenger_f,
                                  all_threads=True, chain=False)
    except OSError:
        return None
    if app is None:
        return pfad        # nur die Datei anlegen, sonst nichts anfassen
    # Auch alles, was Tk und die C-Seite auf die Fehlerausgabe schreiben.
    # Ein X-Fehler beendet Tk mit einer Zeile auf stderr und ohne Signal:
    # kein Faulthandler, kein Abbild, nichts - und wer das Programm aus dem
    # Menue startet, hat gar keine Fehlerausgabe. Deshalb auf der Ebene des
    # Dateizeigers umlenken, nicht nur sys.stderr. Im Terminal bleibt alles,
    # wie es war.
    try:
        if not sys.stderr.isatty():
            os.dup2(_haenger_f.fileno(), 2)
    except (OSError, ValueError, AttributeError):
        pass

    start = time.time()

    def wachen():
        gemeldet = False
        while True:
            time.sleep(5.0)
            still = haenger_dauer(getattr(app, "_herzschlag", 0), start,
                                  time.time(), D.LAEUFT)
            if still > grenze and not gemeldet:
                _haenger_f.write("\n==== %s: Oberflaeche steht seit %.0f s ====\n"
                                 % (time.strftime("%Y-%m-%d %H:%M:%S"), still))
                faulthandler.dump_traceback(file=_haenger_f, all_threads=True)
                gemeldet = True
            elif still < grenze:
                gemeldet = False

    threading.Thread(target=wachen, daemon=True).start()
    return pfad


def main():
    cfg = P.load_config()
    lw_text.setze(cfg.get("sprache", "de"))
    root = tk.Tk()
    S.apply(root, cfg.get("theme", "dunkel"))
    root.minsize(1100, 720)
    app = App(root)
    haenger_spuren(app)
    root.mainloop()


if __name__ == "__main__":
    main()
