#!/usr/bin/env python3
"""
Laserwerk - Oberflaeche fuer GRBL-Diodenlaser.

Bild oder SVG laden, skalieren, Material waehlen, Achsen steuern,
Nullpunkt setzen, Fokus testen, gravieren.
"""
import base64, bisect, io, math, os, queue, re, threading, time
from PIL import Image
import tkinter as tk
from tkinter import ttk

from lw_dialog import filedialog, messagebox   # native GTK-Dialoge
import lw_style as S

import lw_grbl as G
import lw_job as J
import lw_presets as P
import lw_vector as V
import lw_projekt as PR
import lw_telegram as TG
import lw_text
from lw_text import T

AREA = 200.0          # mm, Voreinstellung; wirklich gilt cfg["x_max"]/["y_max"]
CANVAS = 540          # px


class App:
    def __init__(self, root):
        self.root = root
        root.title("Laserwerk")
        self.cfg = P.load_config()
        self.presets = P.load_presets()
        self.q = queue.Queue()
        self.grbl = G.Grbl(lambda k, d: self.q.put((k, d)))
        self.src = None            # Graustufenbild (zugeschnitten)
        self.src_path = None
        self.lines = None          # erzeugter/geladener G-Code
        self.info = None
        self.preview_img = None
        self.preview_pil = None   # Quelle fuer beliebige Zoomstufen
        self.preview_pos = None
        self.zoom = 1.0
        self._prev_cache = None
        self._live_cache = None      # Motivbild in der aktuellen Zoomstufe
        self.drag = None             # laufende Maus-Aktion
        self.v_bw = tk.DoubleVar(value=self.cfg["brett_x"])   # Brettchen X
        self.v_bh = tk.DoubleVar(value=self.cfg["brett_y"])   # Brettchen Y
        self.v_board = tk.BooleanVar(value=self.cfg["brett_an"])
        self.v_snap = tk.BooleanVar(value=self.cfg["einrasten"])
        self.vec = None            # Konturen (nur bei SVG/DXF)
        self.vec_bb = None         # deren exakte Ausdehnung in mm
        self._vecdreh = None       # Ausdehnung der gedrehten Konturen
        self.cut_polys = None      # erzeugte Schnittkonturen
        self.zero_ok = False       # Nullpunkt XY in dieser Sitzung gesetzt
        self.zref_ok = False       # Z-Referenz gueltig
        self.fokus_zs = []
        self.fern = None               # Telegram-Fernsteuerung
        self._rettung = None           # Nullpunkt ueber einen Soft-Reset retten
        self._still = False            # Felder werden gerade umgeschaltet
        self.elemente = []             # mehrere Motive auf einem Werkstueck
        self.aktiv = -1                # welches davon die Felder bearbeiten
        self.projekt_pfad = None       # zuletzt gespeichertes Projekt
        self.quelle_pfad = None        # Vorlage, wie der Nutzer sie kennt
        self.s_max = float(self.cfg.get("s_max", J.S_MAX))   # $30 der Maschine
        self.area = max(float(self.cfg["x_max"]), float(self.cfg["y_max"]), 10.0)
        self.v_zeig_s = tk.IntVar(value=50)     # Leistung Sichtkreuz/Rahmen
        self.v_zeig_a = tk.DoubleVar(value=3.0)  # Armlaenge des Kreuzes
        self.v_frame_laser = tk.BooleanVar(value=True)
        self.v_xoff = tk.DoubleVar(value=2.0)   # Platz links fuer den Anlauf
        self.v_over = tk.DoubleVar(value=1.5)   # Anlauf je Zeilenende
        self.v_yoff = tk.DoubleVar(value=0.0)
        self.v_spiegel = tk.StringVar(value='nein')   # Rueckseite
        self.v_achse = tk.DoubleVar(value=50.0)       # Wendeachse in mm
        self.job_t0 = None
        self._build()
        self._poll_id = self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.beenden)
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
        self.cv.bind("<ButtonRelease-1>", lambda e: setattr(self, "drag", None))
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
        self._build_motiv()
        self._build_material()
        self._build_maschine()
        self._build_tests()
        for ev in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.root.bind_all(ev, self._rad, add="+")
        # jede Aenderung, die den G-Code beeinflusst, macht ihn ungueltig
        for v in (self.v_inv, self.v_mode, self.v_schw, self.v_rot,
                  self.v_s, self.v_f, self.v_line, self.v_job, self.v_passes,
                  self.v_xoff, self.v_over, self.v_yoff, self.v_gamma,
                  self.v_cs, self.v_cf,
                  self.v_spiegel, self.v_achse,
                  self.v_hell, self.v_kontrast, self.v_schaerfe):
            v.trace_add("write", lambda *a: self._stale())
        for v in (self.v_f, self.v_over):
            v.trace_add("write", lambda *a: self._anlauf_zeigen())
        self._anlauf_zeigen()
        for v in (self.v_bw, self.v_bh, self.v_board, self.v_snap):
            v.trace_add("write", lambda *a: self._brett_geaendert())

        # Jobleiste
        jb = ttk.Frame(main, padding=(0, 6, 0, 0))
        jb.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.btn_gen = ttk.Button(jb, text=T("Erzeugen"), command=self.generate)
        self.btn_gen.grid(row=0, column=0, padx=(0, 10))
        for i, (t, f, st) in enumerate([("Rahmen", self.frame, "TButton"),
                                        ("Kontur", self.kontur, "TButton"),
                                        ("Start", self.start, "Accent.TButton"),
                                        ("Pause", self.pause, "TButton"),
                                        ("Weiter", self.resume, "TButton"),
                                        ("STOPP", self.stop, "Danger.TButton")]):
            ttk.Button(jb, text=T(t), command=f, style=st).grid(row=0, column=i + 1, padx=3)
        ttk.Checkbutton(jb, text=T("Rahmen sichtbar"), variable=self.v_frame_laser
                        ).grid(row=0, column=6, padx=(10, 2))
        self.prog = ttk.Progressbar(jb, length=90, maximum=1000)
        self.prog.grid(row=0, column=7, padx=8, sticky="ew")
        self.lbl_prog = ttk.Label(jb, text=T("kein Job"), width=18, anchor="w")

        self.lbl_prog.grid(row=0, column=8)

        jb.columnconfigure(7, weight=1)

        if TG.lade().get("auto") and self.v_tg_token.get().strip():
            self.root.after(800, self.fern_start)

        self.lbl_status = ttk.Label(main, text=T("nicht verbunden"), anchor="w",
                                    style="Status.TLabel")
        self.lbl_status.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        # Zeilenzaehler in die Statuszeile - die Jobleiste ist voll, und hier
        # steht er neben Zustand und Vorschub, wo man ihn sucht.
        self.lbl_marke = ttk.Label(main, text="", anchor="e",
                                   style="Status.TLabel")
        self.lbl_marke.grid(row=2, column=1, sticky="ew", pady=(6, 0))

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
        ttk.Label(parent, text=T(label)).grid(row=r, column=0, sticky="w", pady=2)
        e = ttk.Entry(parent, textvariable=var, width=width)
        e.grid(row=r, column=1, sticky="w")
        if unit:
            ttk.Label(parent, text=T(unit)).grid(row=r, column=2, sticky="w")
        return e

    # ---------------------------------------------------------------- Motiv
    def _build_motiv(self):
        f = self.tab_motiv
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

        wk = ttk.LabelFrame(f, text=T("Werkstück (Nullpunkt = linke untere Ecke)"), padding=4)
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
        for sp, (seite, name) in enumerate((("l", "links"), ("r", "rechts"))):
            self.v_rand[seite] = tk.DoubleVar(value=0.0)
            ttk.Label(wk, text=T(name)).grid(row=2 + sp, column=1, sticky="e",
                                             padx=(0, 2), pady=(6 if not sp else 0, 0))
            e = ttk.Entry(wk, textvariable=self.v_rand[seite], width=6)
            e.grid(row=2 + sp, column=2, sticky="w", pady=(6 if not sp else 0, 0))
            e.bind("<Return>", lambda ev, s=seite: self._rand_setzen(s))
            e.bind("<FocusOut>", lambda ev, s=seite: self._rand_setzen(s))
        for sp, (seite, name) in enumerate((("u", "unten"), ("o", "oben"))):
            self.v_rand[seite] = tk.DoubleVar(value=0.0)
            ttk.Label(wk, text=T(name)).grid(row=2 + sp, column=3, sticky="e",
                                             padx=(8, 2), pady=(6 if not sp else 0, 0))
            e = ttk.Entry(wk, textvariable=self.v_rand[seite], width=6)
            e.grid(row=2 + sp, column=4, sticky="w", pady=(6 if not sp else 0, 0))
            e.bind("<Return>", lambda ev, s=seite: self._rand_setzen(s))
            e.bind("<FocusOut>", lambda ev, s=seite: self._rand_setzen(s))

        ttk.Button(wk, text=T("Motiv mittig setzen"), command=self.center_motif
                   ).grid(row=4, column=0, columnspan=5, sticky="ew", pady=(6, 0))
        ttk.Label(wk, text=T("Motiv mit der Maus schieben, an den Ecken ziehen zum Skalieren."),
                  style="Muted.TLabel").grid(row=5, column=0, columnspan=5, sticky="w")

        box = ttk.LabelFrame(f, text=T("Größe, Anlauf und Versatz"), padding=4)
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
        ttk.Label(box, text=T("0 = aus Vorschub und Beschleunigung gerechnet.\n"
                              "Zu kurz heißt: der Zeilenanfang brennt zu schwach."),
                  style="Muted.TLabel").grid(row=5, column=0, columnspan=6,
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
        ttk.Label(rs, text=T("Mittellinie der Aufspannung, nicht des Motivs."),
                  style="Muted.TLabel").grid(row=4, column=0, columnspan=3, sticky="w")

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

        self.v_inv = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text=T("Invertieren (Hell und Dunkel tauschen)"), variable=self.v_inv
                        ).grid(row=10, column=0, columnspan=3, sticky="w")
        self.v_mode = tk.StringVar(value="schwelle")
        ttk.Radiobutton(f, text=T("Schwarzweiß (Strichgrafik)"), value="schwelle",
                        variable=self.v_mode).grid(row=13, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(f, text=T("Rasterung (Punktdichte, für Fotos)"), value="raster",
                        variable=self.v_mode).grid(row=12, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(f, text=T("Graustufen (Leistung variiert)"), value="grau",
                        variable=self.v_mode).grid(row=11, column=0, columnspan=3, sticky="w")
        self.v_schw = tk.DoubleVar(value=0.5)
        ttk.Label(f, text=T("Schwelle")).grid(row=14, column=0, sticky="w")
        ttk.Scale(f, from_=0.1, to=0.9, variable=self.v_schw, length=140
                  ).grid(row=14, column=1, columnspan=2, sticky="w")

        # Tonwertkurve: hebt oder senkt nur die Mitten. Schwarz bleibt schwarz,
        # Weiss bleibt aus - das Mittel gegen "laeuft alles zu".
        self.v_gamma = tk.DoubleVar(value=1.0)
        ttk.Label(f, text=T("Mitten")).grid(row=15, column=0, sticky="w")
        sg = ttk.Frame(f)
        sg.grid(row=15, column=1, columnspan=2, sticky="w")
        ttk.Scale(sg, from_=0.4, to=2.5, variable=self.v_gamma, length=110,
                  command=lambda v: self._gamma_zeigen()).pack(side="left")
        self.lbl_gamma = ttk.Label(sg, width=4)
        self.lbl_gamma.pack(side="left", padx=(4, 0))
        ttk.Button(sg, text="1:1", width=3,
                   command=lambda: self.v_gamma.set(1.0)).pack(side="left", padx=(2, 0))
        self.lbl_gammahilfe = ttk.Label(
            f, text=T("größer = Mitten heller (nur Graustufen)"), style="Muted.TLabel")
        self.lbl_gammahilfe.grid(row=16, column=0, columnspan=3, sticky="w")
        self._gamma_zeigen()

        bk = ttk.LabelFrame(f, text=T("Bildkorrektur"), padding=4)
        bk.grid(row=17, column=0, columnspan=3, sticky="ew", pady=(8, 0))
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
        ttk.Label(bk, text=T("Fotos brauchen das fast immer: ohne Korrektur\n"
                             "brennt ein hellgrauer Hintergrund als dünner\n"
                             "Punkteteppich mit. 'Auto' zieht ihn auf Weiß."),
                  style="Muted.TLabel").grid(row=4, column=0, columnspan=3, sticky="w")
        self._bk_zeigen()

        jb = ttk.LabelFrame(f, text=T("Bearbeitung"), padding=4)
        jb.grid(row=18, column=0, columnspan=3, sticky="ew", pady=(8, 0))
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
        self.v_cs = tk.IntVar(value=0)
        self.v_cf = tk.IntVar(value=0)
        ttk.Label(jb, text=T("Schnitt S")).grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(jb, from_=0, to=1000, increment=10, width=6,
                    textvariable=self.v_cs).grid(row=4, column=1, sticky="w", pady=(6, 0))
        ttk.Label(jb, text=T("F")).grid(row=4, column=2, sticky="e", padx=(8, 2),
                                        pady=(6, 0))
        ttk.Spinbox(jb, from_=0, to=5000, increment=50, width=6,
                    textvariable=self.v_cf).grid(row=4, column=3, sticky="w", pady=(6, 0))
        ttk.Label(jb, text=T("0 = Werte aus dem Reiter Material.\n"
                             "Schneiden braucht meist mehr Leistung und\n"
                             "weniger Vorschub als Gravieren."),
                  style="Muted.TLabel").grid(row=5, column=0, columnspan=4, sticky="w")

        ttk.Button(f, text=T("Vorschau + G-Code erzeugen"), command=self.generate, style="Accent.TButton"
                   ).grid(row=19, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        self.lbl_info = ttk.Label(f, text="", justify="left")
        self.lbl_info.grid(row=20, column=0, columnspan=3, sticky="w")
        bb = ttk.Frame(f)
        bb.grid(row=21, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Button(bb, text=T("G-Code speichern"), command=self.save_gcode).pack(side="left")
        ttk.Button(bb, text=T("G-Code laden"), command=self.load_gcode).pack(side="left", padx=4)
        pb = ttk.Frame(f)
        pb.grid(row=22, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Button(pb, text=T("Projekt speichern"), command=self.save_project
                   ).pack(side="left", fill="x", expand=True)
        ttk.Button(pb, text=T("Projekt öffnen"), command=self.open_project
                   ).pack(side="left", fill="x", expand=True, padx=(4, 0))

    # ---------------------------------------------------------------- Material
    def _build_material(self):
        f = self.tab_mat
        self.v_preset = tk.StringVar()
        self.cb_preset = ttk.Combobox(f, textvariable=self.v_preset, width=30,
                                      values=sorted(self.presets), state="readonly")
        self.cb_preset.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.cb_preset.bind("<<ComboboxSelected>>", lambda e: self.load_preset())

        self.v_dicke = tk.DoubleVar(value=12.0)
        self.v_korr = tk.DoubleVar(value=0.0)
        self.v_s = tk.IntVar(value=830)
        self.v_f = tk.IntVar(value=1000)
        self.v_line = tk.DoubleVar(value=0.10)
        self._row(f, 1, "Materialdicke", self.v_dicke, unit="mm")
        self._row(f, 2, "Fokuskorrektur", self.v_korr, unit="mm")
        self.v_smin = tk.IntVar(value=0)
        self._row(f, 3, "Leistung S", self.v_s, unit="von 1000")
        self._row(f, 4, "Leistung ab", self.v_smin, unit="0 = automatisch")
        self._row(f, 5, "Vorschub F", self.v_f, unit="mm/min")
        self._row(f, 6, "Zeilenabstand", self.v_line, unit="mm")
        ttk.Label(f, text=T("'Leistung ab' ist die kleinste Leistung, bei der das\n"
                            "Material überhaupt zeichnet. Graustufen werden dann\n"
                            "zwischen diesen beiden Werten verteilt statt zwischen\n"
                            "30 % und S. Für Strichgrafik ohne Bedeutung."),
                  style="Muted.TLabel").grid(row=7, column=0, columnspan=3, sticky="w")
        self.lbl_sf = ttk.Label(f, text="")
        self.lbl_sf.grid(row=8, column=0, columnspan=3, sticky="w", pady=4)
        for v in (self.v_s, self.v_f, self.v_smin):
            v.trace_add("write", lambda *a: self._show_sf())
        self.v_notiz = tk.StringVar()
        ttk.Label(f, text=T("Notiz")).grid(row=9, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.v_notiz, width=32).grid(row=10, column=0, columnspan=3, sticky="ew")

        ttk.Button(f, text=T("Übernehmen + Z-Höhe anfahren"), command=self.apply_preset, style="Accent.TButton"
                   ).grid(row=11, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        ttk.Separator(f).grid(row=12, column=0, columnspan=3, sticky="ew", pady=8)
        self.v_pname = tk.StringVar()
        ttk.Label(f, text=T("Speichern als")).grid(row=13, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.v_pname, width=20).grid(row=13, column=1, columnspan=2, sticky="w")
        bb = ttk.Frame(f)
        bb.grid(row=14, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Button(bb, text=T("Speichern"), command=self.save_preset).pack(side="left")
        ttk.Button(bb, text=T("Löschen"), command=self.delete_preset).pack(side="left", padx=4)
        ttk.Label(f, text=T("Z fährt auf Materialdicke + Korrektur.\n"
                            "Dafuer muss unter 'Maschine' eine\nZ-Referenz gesetzt sein."), style="Muted.TLabel").grid(row=15, column=0, columnspan=3, sticky="w", pady=8)
        self._show_sf()

    # ---------------------------------------------------------------- Maschine
    def _build_maschine(self):
        f = self.tab_masch
        self.v_port = tk.StringVar(value=self.cfg.get("port", ""))
        self.cb_port = ttk.Combobox(f, textvariable=self.v_port, width=22,
                                    values=G.ports())
        self.cb_port.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Button(f, text=T("neu suchen"), command=lambda: self.cb_port.configure(
            values=G.ports())).grid(row=0, column=2)
        self.btn_conn = ttk.Button(f, text=T("Verbinden"), command=self.toggle_connect, style="Accent.TButton")
        self.btn_conn.grid(row=1, column=0, columnspan=3, sticky="ew", pady=4)

        self.lbl_pos = ttk.Label(f, text=T("X -  Y -  Z -"), style="Pos.TLabel")
        self.lbl_pos.grid(row=2, column=0, columnspan=3, sticky="w")
        self.lbl_ref = ttk.Label(f, text="")
        self.lbl_ref.grid(row=3, column=0, columnspan=3, sticky="w")

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
        ttk.Label(vw, text=T("Bestimmt die gezeichnete Arbeitsfläche und die\n"
                             "Warnung, wenn ein Job nicht hineinpasst."),
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=5, sticky="w")

        ttk.Button(f, text=T("Nullpunkt XY = hier"), command=self.set_zero
                   ).grid(row=6, column=0, columnspan=3, sticky="ew", pady=2)
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
        ttk.Label(zg, text=T("Kurzes Kreuz mit schwacher Leistung, danach\n"
                             "exakt zurück. Gilt auch für 'Rahmen sichtbar'."),
                  style="Muted.TLabel").grid(row=2, column=0, columnspan=3, sticky="w")
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
        ttk.Label(sp, text=T("Die Sprache gilt nach einem Neustart."),
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=2,
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
        ttk.Label(tg, text=T("Achsen und Sichtkreuz vom Handy. Gravur und\n"
                             "Schnitt starten absichtlich nur hier."),
                  style="Muted.TLabel").grid(row=4, column=0, columnspan=3, sticky="w")
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
        ttk.Label(fb, text=T("Mitte = Materialdicke + Korrektur\n"
                             "(Reiter Material). Striche von links\n"
                             "nach rechts = Z aufsteigend."), style="Muted.TLabel").grid(row=4, column=0, columnspan=3, sticky="w")
        ttk.Button(fb, text=T("Fokustest starten"), command=self.fokustest
                   ).grid(row=5, column=0, columnspan=3, sticky="ew", pady=4)
        self.lb_fz = tk.Listbox(fb, height=6, width=28)
        self.lb_fz.grid(row=6, column=0, columnspan=3, sticky="ew")
        ttk.Button(fb, text=T("Gewählten Strich ins Material übernehmen"),
                   command=self.take_focus).grid(row=7, column=0, columnspan=3, sticky="ew", pady=4)

        mb = ttk.LabelFrame(f, text=T("Materialtest"), padding=6)
        mb.grid(row=1, column=0, sticky="ew", pady=8)
        self.v_mt_s = tk.StringVar(value="200,400,600,830,1000")
        self.v_mt_f = tk.StringVar(value="600,1000")
        self._row(mb, 0, "Leistungen", self.v_mt_s, width=20)
        self._row(mb, 1, "Vorschübe", self.v_mt_f, width=20)
        ttk.Button(mb, text=T("Materialtest starten"), command=self.materialtest
                   ).grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Label(mb, text=T("Spalten = Leistung, Zeilen = Vorschub,\n"
                             "unten links beginnend. Felder 6 mm."), style="Muted.TLabel").grid(row=3, column=0, columnspan=3, sticky="w")

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
        ttk.Label(gb, text=T("Eine Zeile je Leistung, darin ein Tonwertkeil\n"
                             "von hell nach dunkel. Unten die kleinste\n"
                             "Leistung, links der hellste Ton. Jedes Feld\n"
                             "bekommt genau die Leistung, die eine Gravur\n"
                             "an dieser Stelle auch bekäme."),
                  style="Muted.TLabel").grid(row=4, column=0, columnspan=3, sticky="w")
        self.lbl_gt = ttk.Label(gb, text="", style="Muted.TLabel")
        self.lbl_gt.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(gb, text=T("Graustufentest starten"), command=self.graustufentest
                   ).grid(row=6, column=0, columnspan=3, sticky="ew", pady=4)
        for v in (self.v_gt_s, self.v_gt_f, self.v_gt_n, self.v_gt_feld):
            v.trace_add("write", lambda *a: self._gt_vorschau())
        self._gt_vorschau()

    # ================================================================ Motiv
    def open_image(self):
        p = filedialog.askopenfilename(
            title=T("Bild oder SVG"), initialdir=os.path.expanduser("~/Downloads"),
            filetypes=[(T("Bilder, SVG, DXF"),
                        "*.png *.jpg *.jpeg *.webp *.bmp *.svg *.dxf"),
                       (T("alle"), "*")])
        if p:
            self.lade_motiv(p)

    def lade_motiv(self, p, anzeige=None, fragen=True):
        """Datei einlesen und als Motiv setzen. 'anzeige' ueberschreibt den
        Namen im Fenster - ein Projekt zeigt den urspruenglichen, nicht den
        der ausgepackten Kopie."""
        ext = os.path.splitext(p)[1].lower()
        vec = None
        im = None
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
                im = J.autocrop(J.load_source(p, 3000 if ext == ".svg" else None), 245)
        except Exception as e:
            messagebox.showerror(T("Laden fehlgeschlagen"), str(e))
            return False
        if self.grbl.job_running:
            messagebox.showinfo(T("Motiv"), T("Während eines Jobs nicht möglich."))
            return False
        self._element_sichern()
        self._verwerfen()
        self.src, self.src_path, self.vec = im, p, vec
        self.quelle_pfad = p
        self.vec_bb = V.bbox(V.flatten(vec, 1.0)) if vec else None
        self.vec_voll = vec
        self.ebene = None
        self._vecdreh = self._live_cache = None
        if ext == ".dxf":
            self.v_job.set("schnitt")       # DXF = nur Konturen
        elif not vec and self.v_job.get() in ("schnitt", "beides"):
            self.v_job.set("gravur")
        self.v_rot.set(0)
        name = anzeige or os.path.basename(p)
        self.lbl_src.configure(text=T('{0}\n{1} x {2} px').format(
            name, im.width, im.height))
        self.elemente.append({"anzeige": name, "src": im, "vec": vec,
                              "vec_voll": vec, "vec_bb": self.vec_bb,
                              "pfad": p, "quelle": p})
        self.aktiv = len(self.elemente) - 1
        self.fit()                       # setzt Groesse, sichert gleich mit
        self._element_sichern()
        self._liste_auffrischen()
        self._gen_knopf()
        if vec and fragen:
            self._ebenen_anbieten()
        return True

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
        self.vec_voll = polys
        self.ebene = None
        self._vecdreh = self._live_cache = None
        self.v_rot.set(0)
        self.v_job.set("schnitt")          # eine Form ist zum Schneiden da
        self.lbl_src.configure(text=anzeige)
        self.elemente.append({"anzeige": anzeige, "src": im, "vec": polys,
                              "vec_voll": polys, "vec_bb": self.vec_bb,
                              "pfad": None, "quelle": None, "form": dict(form)})
        self.aktiv = len(self.elemente) - 1
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
        "v_w", "v_h", "v_lock", "v_rot", "v_inv", "v_mode", "v_schw",
        "v_gamma", "v_hell", "v_kontrast", "v_schaerfe",
        "v_xoff", "v_yoff", "v_over", "v_spiegel", "v_achse",
        "v_job", "v_passes", "v_cs", "v_cf",
        "v_s", "v_smin", "v_f", "v_line",
    )

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
                 vec_voll=getattr(self, "vec_voll", None) or self.vec,
                 ebene=getattr(self, "ebene", None),
                 pfad=self.src_path, quelle=self.quelle_pfad)

    def _element_laden(self, i, zeichnen=True):
        """Ein Element in die Eingabefelder holen."""
        if not (0 <= i < len(self.elemente)):
            return
        e = self.elemente[i]
        self.aktiv = i
        self.src, self.vec = e["src"], e["vec"]
        self.vec_bb, self.src_path = e["vec_bb"], e["pfad"]
        self.vec_voll = e.get("vec_voll") or e["vec"]
        self.ebene = e.get("ebene")
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
        self.lbl_src.configure(text=T('{0}\n{1} x {2} px').format(
            e["anzeige"], e["src"].width, e["src"].height))
        self._bk_zeigen(); self._gamma_zeigen(); self._show_sf()
        self._anlauf_zeigen()
        self._liste_auffrischen()
        if zeichnen:
            self._draw()

    def _liste_auffrischen(self):
        self.lb_el.delete(0, "end")
        for i, e in enumerate(self.elemente):
            art = {"gravur": T("gravieren"), "schnitt": T("schneiden"),
                   "beides": T("beides")}.get(e.get("v_job", "gravur"), "")
            self.lb_el.insert("end", "%d. %s  (%s)" % (i + 1, e["anzeige"], art))
        if 0 <= self.aktiv < len(self.elemente):
            self.lb_el.selection_clear(0, "end")
            self.lb_el.selection_set(self.aktiv)

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
            self.vec_voll = None
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
            self._element_sichern()
        for feld, schluessel in self.PROJEKTFELDER:
            if schluessel in d["werte"]:
                try:
                    getattr(self, feld).set(d["werte"][schluessel])
                except tk.TclError:
                    pass
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

    def clear_motif(self):
        """Alle Elemente und den erzeugten G-Code verwerfen."""
        if self.grbl.job_running:
            messagebox.showinfo(T("Motiv"), T("Während eines Jobs nicht möglich."))
            return
        self.elemente = []
        self.aktiv = -1
        self.src = self.src_path = None
        self.vec = self.vec_bb = self.vec_voll = self._vecdreh = None
        self._live_cache = None
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
        self._stale()
        self._raender_zeigen()
        self._draw()

    def _vec_dreh_bb(self):
        """Ausdehnung der GEDREHTEN Konturen. Das gedrehte Rechteck um eine
        Kontur ist meist groesser als das Rechteck um die gedrehte Kontur -
        wer damit rechnet, setzt das Motiv nicht wirklich mittig."""
        if not self.vec:
            return None
        try:
            grad = round(float(self.v_rot.get()), 1)
        except tk.TclError:
            grad = 0.0
        if self._vecdreh and self._vecdreh[0] == grad:
            return self._vecdreh[1]
        bezug = getattr(self, "vec_voll", None) or self.vec
        x0, y0, x1, y1 = V.bbox(V.rotate(V.flatten(bezug, 1.0), grad))
        self._vecdreh = (grad, (x1 - x0, y1 - y0))
        return self._vecdreh[1]

    def _dreh_bb(self, w, h):
        """Umschliessendes Rechteck nach dem Drehen - fuer jeden Winkel, nicht
        nur fuer Vielfache von 90 Grad."""
        try:
            a = math.radians(float(self.v_rot.get()))
        except tk.TclError:
            return w, h
        c, s = abs(math.cos(a)), abs(math.sin(a))
        return w * c + h * s, w * s + h * c

    def _bezug_bb(self):
        """Ausdehnung der Vorlage, auf die sich Breite und Hoehe beziehen.

        Beim Schneiden ist das die echte Kontur, beim Gravieren das
        gerenderte Bild - das ist breiter, weil die Strichdicke mitzaehlt.
        """
        if self.src is None:
            return 0.0, 0.0
        if self.v_job.get() == "schnitt" and self.vec:
            return self._vec_dreh_bb()
        return self._dreh_bb(*self.src.size)

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
        try:                         # 370 -> 10, -5 -> 355
            self.v_rot.set(round(float(self.v_rot.get()) % 360, 1))
        except tk.TclError:
            return
        self._keep_ratio("w")

    def _gen_knopf(self):
        """Hervorheben, solange kein gueltiger G-Code vorliegt."""
        if not hasattr(self, "btn_gen"):
            return
        fehlt = self.src is not None and self.lines is None
        self.btn_gen.configure(style="Accent.TButton" if fehlt else "TButton")

    def _stale(self):
        """Größe/Drehung geändert: erzeugter G-Code passt nicht mehr.

        Beim Umschalten zwischen Elementen aendern sich die Felder ebenfalls -
        das ist keine Benutzereingabe und darf das Ergebnis nicht verwerfen.
        """
        if getattr(self, "_still", False):
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

    def generate(self):
        """G-Code fuer alle Elemente: erst alles Gravieren, dann alles
        Schneiden. Umgekehrt faellt ein Teil heraus, bevor der Rest
        graviert ist."""
        if not self.elemente:
            messagebox.showinfo(T("Kein Motiv"), T("Erst ein Bild oder SVG öffnen."))
            return
        self._element_sichern()
        merke = self.aktiv
        gravur, schnitt = [], []
        sekunden = brennweg = 0.0
        try:
            for i in range(len(self.elemente)):
                self._element_laden(i, zeichnen=False)
                self.lines = self.info = None
                self.preview_pil = self.cut_polys = None
                self._erzeuge_eines()
                if self.lines is None:
                    return
                self._element_sichern()     # z.B. angehobener Versatz X
                e = self.elemente[i]
                e["ergebnis"] = dict(lines=self.lines, info=self.info,
                                     preview_pil=self.preview_pil,
                                     preview_pos=self.preview_pos,
                                     cut_polys=self.cut_polys,
                                     text=self.lbl_info.cget("text"))
                sekunden += self.info.get("sekunden", 0)
                brennweg += self.info.get("cut_m", 0)
                (schnitt if self.v_job.get() == "schnitt" else gravur).append(i)
        finally:
            self._element_laden(merke, zeichnen=False)
        folge = gravur + schnitt
        zeilen = []
        for i in folge:
            teil = self.elemente[i]["ergebnis"]["lines"]
            if zeilen and zeilen[-1].startswith("G0 X0 Y0"):
                zeilen = zeilen[:-1]        # Rueckfahrt zwischen Teilen sparen
            zeilen += teil
        marken, versatz = [], 0
        for i in folge:
            teil = self.elemente[i]["ergebnis"]
            for idx, art, nr, gesamt in teil["info"].get("marken", ()):
                marken.append((idx + versatz, art, nr, gesamt))
            versatz += len(teil["lines"])
            if versatz and zeilen[versatz - 1:versatz] == ["G0 X0 Y0"]:
                versatz -= 1          # dieselbe Kuerzung wie oben
        self.lines = zeilen
        erste = self.elemente[folge[0]]["ergebnis"]["info"]
        self.info = dict(erste)
        self.info.update(befehle=len(zeilen), sekunden=sekunden, cut_m=brennweg,
                         marken=marken)
        if len(self.elemente) > 1:
            self.lbl_info.configure(text=T(
                "{n} Elemente\n{b} Befehle, Brennweg {m:.1f} m\n"
                "Laufzeit ca. {min:.0f} min").format(
                    n=len(self.elemente), b=len(zeilen), m=brennweg,
                    min=sekunden / 60) + "\n\n" + "\n\n".join(
                "%d. %s\n%s" % (i + 1, self.elemente[i]["anzeige"],
                                 self.elemente[i]["ergebnis"]["text"])
                for i in folge))
        self._gen_knopf()
        self._draw()

    def _erzeuge_eines(self):
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
                src = J.autocrop(J.load_source(self.src_path, need), 245)
        p = J.prepare(src, w, h, line, invert=self.v_inv.get(),
                      gamma=max(0.2, float(self.v_gamma.get())),
                      helligkeit=self.v_hell.get(),
                      kontrast=self.v_kontrast.get(),
                      schaerfe=self.v_schaerfe.get(),
                      rotate=self.v_rot.get(), mode=self.v_mode.get(),
                      schwelle=self.v_schw.get())
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
        if self.v_job.get() == "beides":
            if not self._schnitt_anhaengen(w, h):
                return
        self._gen_knopf()
        i = self.info
        warn = ""
        if i["xmax"] > self.cfg["x_max"] or h > self.cfg["y_max"]:
            warn = T("\nACHTUNG: größer als der Verfahrweg!")
        self.lbl_info.configure(text=(
            (T("RÜCKSEITE gespiegelt an {achse} = {mm:.1f} mm\n").format(
                achse="X" if sp == "x" else "Y", mm=achse) if sp != "nein" else "")
            + T("Motiv {b:.1f} x {h:.1f} mm\n"
                "X {x0:.1f} .. {x1:.1f} mm (mit Overscan)\n"
                "{n} Befehle, Brennweg {m:.1f} m\n"
                "Laufzeit ca. {min:.0f} min\n"
                "S{s}/F{f} = S/F {sf:.2f}{warn}").format(
                b=i["breite"], h=i["hoehe"], x0=i["xmin"], x1=i["xmax"],
                n=i["befehle"], m=i["cut_m"], min=i["sekunden"] / 60,
                s=s, f=f, sf=s / f, warn=warn)))
        # Der Schnitt haengt sich erst hier an - vorher wuerde die Gravur
        # seinen Text mit ihrem eigenen ueberschreiben.
        if self.v_job.get() == "beides" and not self._schnitt_anhaengen(w, h):
            return
        self._draw()

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
        ganz = V.rotate(V.flatten(bezug, sc), self.v_rot.get())
        polys, _ = V.fit(polys, w, h, max(0.0, float(self.v_xoff.get())),
                         max(0.0, float(self.v_yoff.get())), bezug=ganz,
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
        return V.order(polys)

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
        # Die Rueckfahrt am Ende der Gravur faellt weg, der Schnitt faengt
        # ohnehin mit einer eigenen Anfahrt an.
        if self.lines and self.lines[-1].startswith("G0 X0 Y0"):
            self.lines = self.lines[:-1]
        self.lines = self.lines + g
        i = self.info
        self.info = dict(i)
        self.info.update(
            befehle=len(self.lines),
            cut_m=i["cut_m"] + ci["cut_m"],
            sekunden=i["sekunden"] + ci["sekunden"],
            xmax=max(i["xmax"], ci["xmax"]),
            konturen=ci["konturen"], schnitt_m=ci["cut_m"],
            schnitt_sekunden=ci["sekunden"])
        self.cut_polys = polys
        self.lbl_info.configure(text=self.lbl_info.cget("text") + T(
            "\n\nDazu Schnitt: {k} Konturen, {m:.2f} m x {p}\n"
            "S{s}/F{f} = S/F {sf:.2f}, ca. {min:.0f} min").format(
                k=ci["konturen"], m=ci["cut_m"], p=passes, s=cs, f=cf,
                sf=cs / cf if cf else 0, min=max(1, ci["sekunden"] / 60)))
        return True

    def _generate_cut(self, w, h, s, f):
        polys = self._schnitt_polys(w, h)
        if polys is None:
            return
        sp = self.v_spiegel.get()
        passes = max(1, self.v_passes.get())
        self.lines, self.info = V.cut_gcode(polys, self._s(s), f, passes,
                                            kommentar=self._quellname())
        self.cut_polys = polys
        self.preview_img = None
        self._gen_knopf()
        i = self.info
        warn = T("\nACHTUNG: größer als der Verfahrweg!") if (
            i["xmax"] > self.cfg["x_max"] or i["hoehe"] > self.cfg["y_max"]) else ""
        self.lbl_info.configure(text=(
            (T("RÜCKSEITE gespiegelt\n") if sp != "nein" else "")
            + T("Schnitt {b:.1f} x {h:.1f} mm\n"
                "{k} Konturen, innen vor außen\n"
                "Schnittlänge {m:.2f} m x {p} Durchgang/-gänge\n"
                "Laufzeit ca. {min:.0f} min\n"
                "S{s}/F{f} = S/F {sf:.2f}{warn}").format(
                b=i["breite"], h=i["hoehe"], k=i["konturen"], m=i["cut_m"],
                p=passes, min=max(1, i["sekunden"] / 60),
                s=s, f=f, sf=s / f, warn=warn)))
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
                min=max(1, info["sekunden"] / 60))
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
        self.v_dicke.set(d.get("dicke", 0)); self.v_korr.set(d.get("korrektur", 0))
        self.v_s.set(d.get("s", 830)); self.v_f.set(d.get("f", 1000))
        self.v_smin.set(d.get("smin", 0))
        self.v_line.set(d.get("line", 0.1)); self.v_notiz.set(d.get("notiz", ""))
        self.v_mode.set(d.get("mode", "schwelle")); self.v_schw.set(d.get("schwelle", 0.5))
        self.v_gamma.set(d.get("gamma", 1.0)); self._gamma_zeigen()
        self.v_pname.set(self.v_preset.get())

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
        self.presets[n] = dict(dicke=self.v_dicke.get(), korrektur=self.v_korr.get(),
                               s=self.v_s.get(), smin=self.v_smin.get(),
                               f=self.v_f.get(), line=self.v_line.get(),
                               mode=self.v_mode.get(), schwelle=round(self.v_schw.get(), 2),
                               gamma=round(self.v_gamma.get(), 2),
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
        self._rettung = None
        if self.grbl.connected:
            self.grbl.disconnect()
            self.btn_conn.configure(text=T("Verbinden"))
            self.lbl_status.configure(text=T("getrennt"))
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
        self.btn_conn.configure(text=T("Trennen"))
        self.zero_ok = self.zref_ok = False
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
        schlimmer als keiner."""
        return (self._rettung is not None and any(self._rettung[0])
                and time.time() - self._rettung[3] < 120)

    def _nullpunkt_retten(self):
        """Den G92-Versatz nach einem Soft-Reset wiederherstellen.

        Beim Anhalten bremst das Programm erst aus und setzt erst dann zurueck,
        deshalb stimmt die Maschinenposition noch. Der Versatz wird also einfach
        neu gesetzt: G92 auf (MPos - altes WCO). Es bewegt sich dabei nichts.
        """
        wco, war_null, war_zref, wann = self._rettung
        self._rettung = None
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

    def _einstellungen_pruefen(self, d):
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
        if d.get("120"):
            self.cfg["accel"] = float(d["120"])
            P.save_config(self.cfg)
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
        self._log(T("Nullpunkt XY gesetzt"))

    def set_zref(self):
        if not self._need():
            return
        z = self.v_zref.get()
        self.grbl.set_z_reference(self._zv(z))
        self.zref_ok = True
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
        sv = max(1, min(int(self.v_zeig_s.get()), 120))
        arm = max(0.5, min(float(self.v_zeig_a.get()), 8.0))
        if sv / J.POINTER_FEED > 0.20:
            messagebox.showwarning(T("Position zeigen"),
                T("S{s} bei F{f} ist S/F {sf:.2f}.\n"
                  "Ueber 0,20 brennt es sichtbar ein - bitte weniger."
                  ).format(s=sv, f=J.POINTER_FEED, sf=sv / J.POINTER_FEED))
            return
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
        P.save_config(self.cfg)

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
        self._log(T('Fokuskorrektur = {0:+.2f} mm - im Reiter Material speichern').format(self.v_korr.get()))

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
        self.lbl_gt.configure(text=T("{b:.0f} x {h:.0f} mm, Laufzeit ca. "
                                     "{min:.0f} min").format(
            b=i["breite"], h=i["hoehe"], min=i["sekunden"] / 60))

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

    def materialtest(self):
        if not self._need(zero=True):
            return
        try:
            ps = [int(x) for x in self.v_mt_s.get().split(",")]
            fs = [int(x) for x in self.v_mt_f.get().split(",")]
        except ValueError:
            messagebox.showerror(T("Materialtest"), T("Werte mit Komma trennen, z.B. 200,400,600"))
            return
        self._run(J.materialtest([self._s(p) for p in ps], fs),
                  T("Materialtest {a}x{b}").format(a=len(ps), b=len(fs)), confirm=True)

    # ================================================================ Job
    def frame(self):
        if not self.lines:
            messagebox.showinfo(T("Rahmen"), T("Erst G-Code erzeugen oder laden."))
            return
        sv = max(1, min(int(self.v_zeig_s.get()), 120)) if self.v_frame_laser.get() else 0
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
        sv = max(1, min(int(self.v_zeig_s.get()), 120))
        if sv / J.POINTER_FEED > 0.20:
            messagebox.showwarning(T("Kontur fahren"),
                T("S{s} bei F{f} ist S/F {sf:.2f}.\n"
                  "Ueber 0,20 brennt es sichtbar ein - bitte weniger."
                  ).format(s=sv, f=J.POINTER_FEED, sf=sv / J.POINTER_FEED))
            return
        g, i = V.cut_gcode(polys, self._s(sv), J.POINTER_FEED, 1)
        self._log(T("Kontur fahren: {k} Konturen, {m:.2f} m, ca. {min:.0f} min, "
                    "S{s}/F{f}").format(k=i["konturen"], m=i["cut_m"],
                                        min=max(1, i["sekunden"] / 60),
                                        s=sv, f=J.POINTER_FEED))
        if i["sekunden"] > 120 and not messagebox.askokcancel(
                T("Kontur fahren"),
                T("{k} Konturen, {m:.2f} m Weg, ca. {min:.0f} min.\n\n"
                  "Fortfahren?").format(k=i["konturen"], m=i["cut_m"],
                                        min=max(1, i["sekunden"] / 60))):
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
                    min=self.info["sekunden"] / 60)
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
        self.marken = (self.info or {}).get("marken") if lines is self.lines else None
        self._marken_idx = [m[0] for m in self.marken] if self.marken else None
        self.prog["value"] = 0
        self._log(T('{0} gestartet').format(name))

        def run():
            res = self.grbl.run_job(lines, lambda d, t, el, er: self.q.put(("prog", (d, t, el, er))))
            self.q.put(("jobend", (name, res)))
        threading.Thread(target=run, daemon=True).start()

    def pause(self):
        if self.grbl.connected:
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
        # faehrt "Zum Nullpunkt" an den Maschinennullpunkt.
        self._rettung = (tuple(self.grbl.status.get("wco", (0, 0, 0))),
                         self.zero_ok, self.zref_ok, time.time())
        self._log(T("STOPP"))
        threading.Thread(target=self.grbl.stop, daemon=True).start()

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
            self.lbl_pos.configure(text=T('X{0:8.2f}  Y{1:8.2f}  Z{2:7.2f}').format(x, y, z))
            self.lbl_status.configure(text=T("{port}  |  {zustand}  |  Vorschub {v:.0f}"
                                             "  Leistung {s:.0f}").format(
                port=self.grbl.port, zustand=d["state"],
                v=d["fs"][0] if d["fs"] else 0,
                s=d["fs"][1] if len(d["fs"]) > 1 else 0))
            self.head = (x, y)
            self._draw_head()
            self.lbl_ref.configure(text=T("Nullpunkt: {null}   Z-Ref: {zref}").format(
                null=T("gesetzt") if self.zero_ok else T("NICHT gesetzt"),
                zref=T("gültig") if self.zref_ok else T("fehlt")))
        elif k == "prog":
            done, tot, el, er = d
            self.prog["value"] = done * 1000 / tot
            rest = el / done * (tot - done) if done else 0
            if self.info and self.info.get("sekunden") and done > 0:
                # Modellschaetzung zaehlt mehr als lineare Hochrechnung
                rest = max(0, self.info["sekunden"] - el) * 0.6 + rest * 0.4
            self.lbl_prog.configure(
                text=T("{p} %   noch ~{min:.0f} min").format(p=done * 100 // tot,
                                                             min=rest / 60)
                + (T("   {n} Fehler").format(n=er) if er else ""))
            self.lbl_marke.configure(text=self._marke_text(done))
        elif k == "jobend":
            name, res = d
            txt = {"fertig": T("fertig"),
                   "abgebrochen": T("abgebrochen (Laser aus)"),
                   "alarm": T("ALARM - gestoppt"),
                   "verbindung": T("Verbindung verloren"),
                   "fehler": T("zu viele Übertragungsfehler")}.get(res, res)
            self.lbl_prog.configure(text=T('{0}: {1}').format(name, txt))
            self.lbl_marke.configure(text="")
            self._log(T('{0}: {1}').format(name, txt))
            self._melde(f"{name}: {txt}")
            if res != "fertig":
                # Soft-Reset/Abriss: Offsets sind nicht mehr verlaesslich
                self.zero_ok = self.zref_ok = False
                if res != "abgebrochen":
                    messagebox.showwarning(name, txt)
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
            self.btn_conn.configure(text=T("Verbinden"))
            self.zero_ok = self.zref_ok = False
            self._rettung = None      # Position nach einem Abriss unbekannt
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
        if aktion == "stopp":
            if not g.connected:
                return T("Nicht verbunden.")
            g.stop(); self.zero_ok = self.zref_ok = False
            self._log(T("STOPP (Telegram)"))
            return T("STOPP: Halt und Soft-Reset. Nullpunkt danach neu setzen.")
        if not g.connected:
            return T("Nicht verbunden.")
        if g.job_running:
            return T("Es laeuft ein Job - frei sind nur /status, /aus und /stopp.")
        if aktion == "frei":
            self._log(T("Entsperrt (Telegram)"))
            return f"$X -> {g.unlock()}"
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
            sv = max(1, min(int(self.v_zeig_s.get()), 120))
            arm = max(0.5, min(float(self.v_zeig_a.get()), 8.0))
            if sv / J.POINTER_FEED > 0.20:
                return T("S{s} bei F{f} ist S/F {sf:.2f} - ueber 0,20 brennt es "
                         "ein. Am Rechner kleiner stellen.").format(
                    s=sv, f=J.POINTER_FEED, sf=sv / J.POINTER_FEED)
            self._log(T('Kreuz S{0} (Telegram)').format(sv))
            self._bg(lambda: [g.cmd(c) for c in
                              J.kreuz_lines(self._s(sv), J.POINTER_FEED, arm)], None)
            return T("Kreuz {mm:.1f} mm bei S{s}").format(mm=2 * arm, s=sv)
        if aktion == "null":
            g.set_zero_xy(); self.zero_ok = True
            self._log(T("Nullpunkt XY gesetzt (Telegram)"))
            return T("Nullpunkt XY = hier.")
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
            cv.create_text((ax + cx) / 2, ay - 8, fill=S.ACCENT, anchor="s",
                           text=T('{0:.1f} x {1:.1f} mm').format(b, h))
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
            im = im.rotate(-rot, expand=True, fillcolor=255)
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

    def _press(self, e):
        box = self._box()
        if box is None:
            return
        x, y, b, h = box
        px, py = self._mm(x, y + h)                  # linke obere Ecke
        qx, qy = self._mm(x + b, y)                  # rechte untere Ecke
        ecken = {"ul": (px, py), "ur": (qx, py), "ol": (px, qy), "or": (qx, qy)}
        for name, (cx, cy) in ecken.items():
            if abs(e.x - cx) <= 9 and abs(e.y - cy) <= 9:
                self.drag = ("size", name, box, (e.x, e.y))
                return
        # Ein Rahmen ohne Hoehe (gerade Linie) waere sonst gar nicht zu
        # greifen - nur bei duennen Rahmen etwas Luft geben, sonst nicht.
        lx = 0 if abs(qx - px) > 6 else 4
        ly = 0 if abs(qy - py) > 6 else 4
        if min(px, qx) - lx <= e.x <= max(px, qx) + lx and \
                min(py, qy) - ly <= e.y <= max(py, qy) + ly:
            self.drag = ("move", None, box, (e.x, e.y))

    def _drag_move(self, e):
        if not self.drag:
            return
        self.preview_pil = self.preview_img = self.cut_polys = None
        art, ecke, (bx, by, bb, bh), (sx, sy) = self.drag
        s = self._scale()
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
            im = im.rotate(-rot, expand=True, fillcolor=255)
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
        return pfad

    def wachen():
        gemeldet = False
        while True:
            time.sleep(5.0)
            still = time.time() - getattr(app, "_herzschlag", 0)
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
