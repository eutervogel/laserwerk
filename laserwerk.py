#!/usr/bin/env python3
"""
Laserwerk - Oberflaeche fuer GRBL-Diodenlaser.

Bild oder SVG laden, skalieren, Material waehlen, Achsen steuern,
Nullpunkt setzen, Fokus testen, gravieren.
"""
import base64, io, math, os, queue, threading, time
from PIL import Image
import tkinter as tk
from tkinter import ttk

from lw_dialog import filedialog, messagebox   # native GTK-Dialoge
import lw_style as S

import lw_grbl as G
import lw_job as J
import lw_presets as P
import lw_vector as V
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
        self.root.after(100, self._poll)
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
        self.tab_motiv = self._scrollbereich(nb, "Motiv")
        self.tab_mat = self._scrollbereich(nb, "Material")
        self.tab_masch = self._scrollbereich(nb, "Maschine")
        self.tab_test = self._scrollbereich(nb, "Tests")
        self._build_motiv()
        self._build_material()
        self._build_maschine()
        self._build_tests()
        # jede Aenderung, die den G-Code beeinflusst, macht ihn ungueltig
        for v in (self.v_inv, self.v_mode, self.v_schw, self.v_rot,
                  self.v_s, self.v_f, self.v_line, self.v_job, self.v_passes,
                  self.v_xoff, self.v_over, self.v_yoff, self.v_gamma,
                  self.v_spiegel, self.v_achse):
            v.trace_add("write", lambda *a: self._stale())
        for v in (self.v_bw, self.v_bh, self.v_board, self.v_snap):
            v.trace_add("write", lambda *a: self._brett_geaendert())

        # Jobleiste
        jb = ttk.Frame(main, padding=(0, 6, 0, 0))
        jb.grid(row=1, column=0, columnspan=2, sticky="ew")
        for i, (t, f, st) in enumerate([("Rahmen fahren", self.frame, "TButton"),
                                        ("Start", self.start, "Accent.TButton"),
                                        ("Pause", self.pause, "TButton"),
                                        ("Weiter", self.resume, "TButton"),
                                        ("STOPP", self.stop, "Danger.TButton")]):
            ttk.Button(jb, text=T(t), command=f, style=st).grid(row=0, column=i, padx=3)
        ttk.Checkbutton(jb, text=T("Rahmen sichtbar"), variable=self.v_frame_laser
                        ).grid(row=0, column=5, padx=(8, 0))
        self.prog = ttk.Progressbar(jb, length=300, maximum=1000)
        self.prog.grid(row=0, column=6, padx=8)
        self.lbl_prog = ttk.Label(jb, text=T("kein Job"), width=34)
        self.lbl_prog.grid(row=0, column=7)
        self.btn_theme = ttk.Button(jb, command=self.toggle_theme, width=8)
        self.btn_theme.grid(row=0, column=8, padx=(6, 0))
        self._theme_label()
        jb.columnconfigure(6, weight=1)

        if TG.lade().get("auto") and self.v_tg_token.get().strip():
            self.root.after(800, self.fern_start)

        self.lbl_status = ttk.Label(main, text=T("nicht verbunden"), anchor="w",
                                    style="Status.TLabel")
        self.lbl_status.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    def _scrollbereich(self, nb, titel):
        """Reiterinhalt in einen scrollbaren Bereich packen - die Spalte ist
        laenger als mancher Bildschirm."""
        aussen = ttk.Frame(nb)
        nb.add(aussen, text=T(titel))
        cv = tk.Canvas(aussen, highlightthickness=0, bg=S.BG, width=400)
        sb = ttk.Scrollbar(aussen, orient="vertical", command=cv.yview)
        innen = ttk.Frame(cv, padding=12)
        fen = cv.create_window((0, 0), window=innen, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        def passend(e):
            # Breite mitwachsen lassen: sonst schneidet die Spalte Knoepfe
            # und Hinweise am rechten Rand ab.
            cv.configure(scrollregion=cv.bbox("all"),
                         width=max(400, innen.winfo_reqwidth()))
        innen.bind("<Configure>", passend)
        cv.bind("<Configure>", lambda e: cv.itemconfigure(fen, width=e.width))
        for ev, d in (("<Button-4>", -1), ("<Button-5>", 1)):
            cv.bind_all(ev, lambda e, d=d: (cv.yview_scroll(d, "units")
                                            if str(e.widget).startswith(str(innen)) else None))
        return innen

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
        ttk.Button(ob, text=T("Datei öffnen …"), command=self.open_image
                   ).pack(side="left", fill="x", expand=True)
        ttk.Button(ob, text=T("Motiv entfernen"), command=self.clear_motif
                   ).pack(side="left", padx=(4, 0))
        self.lbl_src = ttk.Label(f, text="-", wraplength=260)
        self.lbl_src.grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 8))

        self.v_w = tk.DoubleVar(value=100.0)
        self.v_h = tk.DoubleVar(value=100.0)
        self.v_lock = tk.BooleanVar(value=True)
        ew = self._row(f, 2, "Breite", self.v_w, unit="mm")
        eh = self._row(f, 3, "Höhe", self.v_h, unit="mm")
        ew.bind("<FocusOut>", lambda e: self._keep_ratio("w"))
        ew.bind("<Return>", lambda e: self._keep_ratio("w"))
        eh.bind("<FocusOut>", lambda e: self._keep_ratio("h"))
        eh.bind("<Return>", lambda e: self._keep_ratio("h"))
        ttk.Checkbutton(f, text=T("Seitenverhältnis halten"), variable=self.v_lock
                        ).grid(row=4, column=0, columnspan=3, sticky="w")

        wk = ttk.LabelFrame(f, text=T("Werkstück (Nullpunkt = linke untere Ecke)"), padding=4)
        wk.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(6, 2))
        ttk.Label(wk, text=T("Länge X")).grid(row=0, column=0, sticky="w")
        ttk.Spinbox(wk, from_=1, to=200, increment=1, width=6,
                    textvariable=self.v_bw).grid(row=0, column=1, sticky="w")
        ttk.Label(wk, text=T("Breite Y")).grid(row=0, column=2, sticky="e", padx=(8, 2))
        ttk.Spinbox(wk, from_=1, to=200, increment=1, width=6,
                    textvariable=self.v_bh).grid(row=0, column=3, sticky="w")
        ttk.Label(wk, text="mm").grid(row=0, column=4, sticky="w")
        ttk.Checkbutton(wk, text=T("anzeigen"), variable=self.v_board
                        ).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(wk, text=T("einrasten"), variable=self.v_snap
                        ).grid(row=1, column=2, columnspan=2, sticky="w")
        ttk.Button(wk, text=T("Motiv mittig setzen"), command=self.center_motif
                   ).grid(row=2, column=0, columnspan=5, sticky="ew", pady=(4, 0))
        ttk.Label(wk, text=T("Motiv mit der Maus schieben, an den Ecken ziehen zum Skalieren."),
                  style="Muted.TLabel").grid(row=3, column=0, columnspan=5, sticky="w")

        box = ttk.LabelFrame(f, text=T("Größe, Anlauf und Versatz"), padding=4)
        box.grid(row=6, column=0, columnspan=3, sticky="ew", pady=6)
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
        ttk.Spinbox(box, from_=0, to=10, increment=0.5, width=5,
                    textvariable=self.v_over).grid(row=2, column=1, sticky="w")
        ttk.Label(box, text=T("Versatz X")).grid(row=2, column=2, columnspan=2, sticky="e")
        ttk.Spinbox(box, from_=0, to=50, increment=0.5, width=5,
                    textvariable=self.v_xoff).grid(row=2, column=4, sticky="w")
        ttk.Label(box, text="mm").grid(row=2, column=5, sticky="w")
        ttk.Label(box, text=T("Versatz Y")).grid(row=3, column=2, columnspan=2, sticky="e")
        ttk.Spinbox(box, from_=0, to=200, increment=0.5, width=5,
                    textvariable=self.v_yoff).grid(row=3, column=4, sticky="w")
        ttk.Label(box, text="mm").grid(row=3, column=5, sticky="w")
        ttk.Label(box, text=T("Der Anlauf macht die Zeilenränder gleichmäßig,\n"
                              "der Versatz hält ihn rechts vom Nullpunkt."),
                  style="Muted.TLabel").grid(row=4, column=0, columnspan=6,
                                             sticky="w", pady=(4, 0))

        rs = ttk.LabelFrame(f, text=T("Rückseite (zweiseitig gravieren)"), padding=4)
        rs.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(0, 6))
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
        ttk.Label(f, text=T("Drehen")).grid(row=8, column=0, sticky="w")
        dr = ttk.Frame(f)
        dr.grid(row=8, column=1, columnspan=2, sticky="w")
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
                        ).grid(row=9, column=0, columnspan=3, sticky="w")
        self.v_mode = tk.StringVar(value="schwelle")
        ttk.Radiobutton(f, text=T("Schwarzweiß (Strichgrafik)"), value="schwelle",
                        variable=self.v_mode).grid(row=11, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(f, text=T("Graustufen (Leistung variiert)"), value="grau",
                        variable=self.v_mode).grid(row=10, column=0, columnspan=3, sticky="w")
        self.v_schw = tk.DoubleVar(value=0.5)
        ttk.Label(f, text=T("Schwelle")).grid(row=12, column=0, sticky="w")
        ttk.Scale(f, from_=0.1, to=0.9, variable=self.v_schw, length=140
                  ).grid(row=12, column=1, columnspan=2, sticky="w")

        # Tonwertkurve: hebt oder senkt nur die Mitten. Schwarz bleibt schwarz,
        # Weiss bleibt aus - das Mittel gegen "laeuft alles zu".
        self.v_gamma = tk.DoubleVar(value=1.0)
        ttk.Label(f, text=T("Mitten")).grid(row=13, column=0, sticky="w")
        sg = ttk.Frame(f)
        sg.grid(row=13, column=1, columnspan=2, sticky="w")
        ttk.Scale(sg, from_=0.4, to=2.5, variable=self.v_gamma, length=110,
                  command=lambda v: self._gamma_zeigen()).pack(side="left")
        self.lbl_gamma = ttk.Label(sg, width=4)
        self.lbl_gamma.pack(side="left", padx=(4, 0))
        ttk.Button(sg, text="1:1", width=3,
                   command=lambda: self.v_gamma.set(1.0)).pack(side="left", padx=(2, 0))
        self.lbl_gammahilfe = ttk.Label(
            f, text=T("größer = Mitten heller (nur Graustufen)"), style="Muted.TLabel")
        self.lbl_gammahilfe.grid(row=14, column=0, columnspan=3, sticky="w")
        self._gamma_zeigen()

        jb = ttk.LabelFrame(f, text=T("Bearbeitung"), padding=4)
        jb.grid(row=15, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.v_job = tk.StringVar(value="gravur")
        ttk.Radiobutton(jb, text=T("Gravieren (Flächen, zeilenweise)"), value="gravur",
                        variable=self.v_job, command=self._job_changed).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(jb, text=T("Schneiden (Konturen, SVG/DXF)"), value="schnitt",
                        variable=self.v_job, command=self._job_changed).grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Label(jb, text=T("Durchgänge")).grid(row=2, column=0, sticky="w")
        self.v_passes = tk.IntVar(value=1)
        ttk.Spinbox(jb, from_=1, to=10, textvariable=self.v_passes, width=4
                    ).grid(row=2, column=1, sticky="w")

        ttk.Button(f, text=T("Vorschau + G-Code erzeugen"), command=self.generate, style="Accent.TButton"
                   ).grid(row=16, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        self.lbl_info = ttk.Label(f, text="", justify="left")
        self.lbl_info.grid(row=17, column=0, columnspan=3, sticky="w")
        bb = ttk.Frame(f)
        bb.grid(row=18, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Button(bb, text=T("G-Code speichern"), command=self.save_gcode).pack(side="left")
        ttk.Button(bb, text=T("G-Code laden"), command=self.load_gcode).pack(side="left", padx=4)

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
        self._row(f, 3, "Leistung S", self.v_s, unit="von 1000")
        self._row(f, 4, "Vorschub F", self.v_f, unit="mm/min")
        self._row(f, 5, "Zeilenabstand", self.v_line, unit="mm")
        self.lbl_sf = ttk.Label(f, text="")
        self.lbl_sf.grid(row=6, column=0, columnspan=3, sticky="w", pady=4)
        for v in (self.v_s, self.v_f):
            v.trace_add("write", lambda *a: self._show_sf())
        self.v_notiz = tk.StringVar()
        ttk.Label(f, text=T("Notiz")).grid(row=7, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.v_notiz, width=32).grid(row=8, column=0, columnspan=3, sticky="ew")

        ttk.Button(f, text=T("Übernehmen + Z-Höhe anfahren"), command=self.apply_preset, style="Accent.TButton"
                   ).grid(row=9, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        ttk.Separator(f).grid(row=10, column=0, columnspan=3, sticky="ew", pady=8)
        self.v_pname = tk.StringVar()
        ttk.Label(f, text=T("Speichern als")).grid(row=11, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.v_pname, width=20).grid(row=11, column=1, columnspan=2, sticky="w")
        bb = ttk.Frame(f)
        bb.grid(row=12, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Button(bb, text=T("Speichern"), command=self.save_preset).pack(side="left")
        ttk.Button(bb, text=T("Löschen"), command=self.delete_preset).pack(side="left", padx=4)
        ttk.Label(f, text=T("Z fährt auf Materialdicke + Korrektur.\n"
                            "Dafuer muss unter 'Maschine' eine\nZ-Referenz gesetzt sein."), style="Muted.TLabel").grid(row=13, column=0, columnspan=3, sticky="w", pady=8)
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
        sp = ttk.LabelFrame(f, text=T("Sprache"), padding=4)
        sp.grid(row=15, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        self.v_sprache = tk.StringVar(
            value=lw_text.SPRACHEN.get(self.cfg.get("sprache", "de"), "Deutsch"))
        cbs = ttk.Combobox(sp, textvariable=self.v_sprache, state="readonly",
                           width=12, values=list(lw_text.SPRACHEN.values()))
        cbs.grid(row=0, column=0, sticky="w")
        cbs.bind("<<ComboboxSelected>>", lambda e: self.set_sprache())
        ttk.Label(sp, text=T("Gilt nach einem Neustart des Programms."),
                  style="Muted.TLabel").grid(row=0, column=1, padx=(8, 0), sticky="w")

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
        if not p:
            return
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
            return
        self.clear_motif()
        self.src, self.src_path, self.vec = im, p, vec
        self.vec_bb = V.bbox(V.flatten(vec, 1.0)) if vec else None
        self._vecdreh = None
        if ext == ".dxf":
            self.v_job.set("schnitt")       # DXF = nur Konturen
        elif not vec and self.v_job.get() == "schnitt":
            self.v_job.set("gravur")
        self.v_rot.set(0)
        self.lbl_src.configure(text=T('{0}\n{1} x {2} px').format(os.path.basename(p), im.width, im.height))
        self.fit()

    def clear_motif(self):
        """Bild, Vorschau und erzeugten/geladenen G-Code verwerfen."""
        if self.grbl.job_running:
            messagebox.showinfo(T("Motiv"), T("Während eines Jobs nicht möglich."))
            return
        self.src = self.src_path = None
        self.vec = self.cut_polys = self.vec_bb = self._vecdreh = None
        self.lines = self.info = self.preview_img = None
        self.preview_pil = self._prev_cache = self._live_cache = None
        self.drag = None
        self.lbl_src.configure(text="-")
        self.lbl_info.configure(text="")
        self._draw()

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
        if self.v_job.get() == "schnitt" and not self.vec:
            messagebox.showinfo(T("Schneiden"), T("Schneiden geht nur mit SVG- oder DXF-Dateien,\n"
                                  "weil dafür Konturen nötig sind."))
            self.v_job.set("gravur")
            return
        if self.v_job.get() == "schnitt":
            self._log(T("Schnittmodus: passendes Material-Preset wählen "
                        "(z.B. Papier S500/F600)"))
        self.fit()

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
        x0, y0, x1, y1 = V.bbox(V.rotate(V.flatten(self.vec, 1.0), grad))
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

    def _aspect(self):
        if self.src is None:
            return 1.0
        if self.v_job.get() == "schnitt" and self.vec:
            w, h = self._vec_dreh_bb()
        else:
            w, h = self._dreh_bb(*self.src.size)
        return w / h if h else 1.0

    def _keep_ratio(self, which):
        if not self.v_lock.get() or self.src is None:
            return
        try:
            a = self._aspect()
            if which == "w":
                self.v_h.set(round(self.v_w.get() / a, 2))
            else:
                self.v_w.set(round(self.v_h.get() * a, 2))
        except tk.TclError:
            pass
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

    def _stale(self):
        """Größe/Drehung geändert: erzeugter G-Code passt nicht mehr."""
        if self.src is not None and self.lines is not None:
            self.lines = self.info = self.preview_img = self.cut_polys = None
            self.preview_pil = self._prev_cache = None
            self.lbl_info.configure(text=T("Einstellung geändert -\nVorschau neu erzeugen."))

    def fit(self):
        if self.src is None:
            return
        a = self._aspect()
        mw, mh = self.v_maxw.get(), self.v_maxh.get()
        w, h = mw, mw / a
        if h > mh:
            h, w = mh, mh * a
        self.v_w.set(round(w, 2))
        self.v_h.set(round(h, 2))
        self._stale()
        self._draw()

    def generate(self):
        if self.src is None:
            messagebox.showinfo(T("Kein Motiv"), T("Erst ein Bild oder SVG öffnen."))
            return
        try:
            w, h, line = self.v_w.get(), self.v_h.get(), self.v_line.get()
            s, f = self.v_s.get(), self.v_f.get()
        except tk.TclError:
            messagebox.showerror(T("Eingabe"), T("Zahlenfeld ungültig."))
            return
        if self.v_job.get() == "schnitt":
            return self._generate_cut(w, h, s, f)
        self.cut_polys = None
        src = self.src
        if self.src_path.lower().endswith(".svg"):
            # SVG in passender Aufloesung neu rendern: scharfe Kanten
            need = int(w / line * 3)
            if need > src.width * 1.2:
                src = J.autocrop(J.load_source(self.src_path, need), 245)
        p = J.prepare(src, w, h, line, invert=self.v_inv.get(),
                      gamma=max(0.2, float(self.v_gamma.get())),
                      rotate=self.v_rot.get(), mode=self.v_mode.get(),
                      schwelle=self.v_schw.get())
        over = max(0.0, float(self.v_over.get()))
        xoff = max(0.0, float(self.v_xoff.get()))
        yoff = max(0.0, float(self.v_yoff.get()))
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
            s_min=self._s(s * 0.3) if self.v_mode.get() == "grau" else 0,
            overscan=over, x_off=xoff, y_off=yoff,
            kommentar=os.path.basename(self.src_path)
                      + ("  RUECKSEITE" if sp != "nein" else ""))
        if xoff < over:
            self._log(T("Hinweis: Anlauf {a:g} mm > Versatz {x:g} mm - der Kopf "
                        "faehrt bis X {bis:.1f}, also links am Nullpunkt vorbei."
                        ).format(a=over, x=xoff, bis=xoff - over))
        self.preview_pil = J.preview_image(p)
        self.preview_img = None
        self.preview_pos = (xoff, yoff + self.info["hoehe"])
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
        self._draw()

    def _generate_cut(self, w, h, s, f):
        if not self.vec:
            messagebox.showinfo(T("Schneiden"), T("Keine Konturen - bitte ein SVG oder DXF öffnen."))
            return
        bw, bh = self._vec_dreh_bb()
        sc = min(w / bw if bw else 1e9, h / bh if bh else 1e9)
        polys = V.flatten(self.vec, sc)
        polys = V.rotate(polys, self.v_rot.get())
        polys, _ = V.fit(polys, w, h, max(0.0, float(self.v_xoff.get())),
                         max(0.0, float(self.v_yoff.get())))
        sp, achse = self.v_spiegel.get(), float(self.v_achse.get())
        if sp != "nein":
            polys = V.mirror(polys, sp, achse)
            x0, y0, x1, y1 = V.bbox(polys)
            if x0 < 0 or y0 < 0:
                messagebox.showerror(T("Rückseite"),
                    T("Gespiegelt beginnt der Schnitt bei X {x:.1f} / Y {y:.1f} mm.\n"
                      "Wendeachse groesser waehlen.").format(x=x0, y=y0))
                return
        polys = V.order(polys)
        passes = max(1, self.v_passes.get())
        self.lines, self.info = V.cut_gcode(polys, self._s(s), f, passes,
                                            kommentar=os.path.basename(self.src_path))
        self.cut_polys = polys
        self.preview_img = None
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
        self.lines = [l for l in (x.split(";")[0].strip() for x in open(p)) if l]
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
        m3 = any(l.upper().startswith("M3") for l in self.lines)
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
                 "liegt nicht links unten!") if neg else "")))
        self._draw()

    # ================================================================ Material
    def load_preset(self):
        d = self.presets.get(self.v_preset.get())
        if not d:
            return
        self.v_dicke.set(d.get("dicke", 0)); self.v_korr.set(d.get("korrektur", 0))
        self.v_s.set(d.get("s", 830)); self.v_f.set(d.get("f", 1000))
        self.v_line.set(d.get("line", 0.1)); self.v_notiz.set(d.get("notiz", ""))
        self.v_mode.set(d.get("mode", "schwelle")); self.v_schw.set(d.get("schwelle", 0.5))
        self.v_gamma.set(d.get("gamma", 1.0)); self._gamma_zeigen()
        self.v_pname.set(self.v_preset.get())

    def _show_sf(self):
        try:
            self.lbl_sf.configure(text=T('S/F = {0:.2f}   (Holz bewährt: 0,83)').format(self.v_s.get()/self.v_f.get()))
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
                               s=self.v_s.get(), f=self.v_f.get(), line=self.v_line.get(),
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
                                line=self.v_line.get())
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
        x0, x1, y0, y1 = J.extent(lines)
        if x1 - x0 > self.cfg["x_max"] or y1 - y0 > self.cfg["y_max"]:
            messagebox.showerror(T("Zu groß"),
                T("Spanne {b:.0f} x {h:.0f} mm passt nicht in den Verfahrweg."
                  ).format(b=x1 - x0, h=y1 - y0))
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
                       if self.cut_polys and lines is self.lines else "")):
                return
        self.job_t0 = time.time()
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
        try:
            while True:
                k, d = self.q.get_nowait()
                self._event(k, d)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

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
        elif k == "jobend":
            name, res = d
            txt = {"fertig": T("fertig"),
                   "abgebrochen": T("abgebrochen (Laser aus)"),
                   "alarm": T("ALARM - gestoppt"),
                   "verbindung": T("Verbindung verloren"),
                   "fehler": T("zu viele Übertragungsfehler")}.get(res, res)
            self.lbl_prog.configure(text=T('{0}: {1}').format(name, txt))
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

    def _log(self, t):
        self.log.insert("end", f"{time.strftime('%H:%M:%S')} {t}\n")
        self.log.see("end")

    # ================================================================ Zeichnen
    def _cv(self):
        w, h = self.cv.winfo_width(), self.cv.winfo_height()
        return (w if w > 1 else CANVAS), (h if h > 1 else CANVAS)

    def _scale(self):
        w, h = self._cv()
        return (min(w, h) - 20) / self.area * self.zoom

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
        s2 = (min(*self._cv()) - 20) / self.area * neu
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
        self.ox, self.oy = 10, self._cv()[1] - 10
        self._draw()

    def _draw(self):
        cv = self.cv
        cv.delete("all")
        x0, y0 = self._mm(0, 0)
        x1, y1 = self._mm(self.area, self.area)
        cv.create_rectangle(x0, y1, x1, y0, outline=S.CANVAS_EDGE)
        s = self._scale()
        if s >= 6:                      # weit hineingezoomt: 1-mm-Raster dazu
            for m in range(0, int(self.area) + 1):
                if m % 10 == 0:
                    continue
                a, _ = self._mm(m, 0); cv.create_line(a, y0, a, y1, fill=S.CANVAS_GRID)
                _, b = self._mm(0, m); cv.create_line(x0, b, x1, b, fill=S.CANVAS_GRID)
        for m in range(10, int(self.area), 10):
            c = S.CANVAS_GRID if m % 50 else S.CANVAS_GRID2
            a, _ = self._mm(m, 0); cv.create_line(a, y0, a, y1, fill=c)
            _, b = self._mm(0, m); cv.create_line(x0, b, x1, b, fill=c)
        for m in range(50, int(self.area), 50):
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
        if self.cut_polys:              # Schnittkonturen: echte Geometrie
            for pl in self.cut_polys:
                pts = [c for p in pl["pts"] for c in self._mm(*p)]
                if pl["closed"]:
                    pts += list(self._mm(*pl["pts"][0]))
                if len(pts) >= 4:
                    cv.create_line(*pts, fill=S.DANGER, width=1)
        elif self.preview_pil is not None and self.preview_pos and self.info:
            ax, ay = self._mm(*self.preview_pos)      # erzeugte G-Code-Vorschau
            self._prepare_preview()
            if self.preview_img is not None:
                cv.create_image(ax, ay, image=self.preview_img, anchor="nw")
        elif box and self.src is not None:            # Platzierung live
            x, y, b, h = box
            img = self._live_image(b, h)
            if img is not None:
                cv.create_image(*self._mm(x, y + h), image=img, anchor="nw")
        if box:                         # Rahmen und Anfasser zum Ziehen
            x, y, b, h = box
            ax, ay = self._mm(x, y + h); cx, cy = self._mm(x + b, y)
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
                sc = min(b / bw, h / bh)
                b, h = bw * sc, bh * sc
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
        if getattr(self, "v_job", None) is None or self.v_job.get() != "gravur":
            return 0.0
        try:
            return max(0.0, float(self.v_over.get()))
        except tk.TclError:
            return 0.0

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
        if min(px, qx) <= e.x <= max(px, qx) and min(py, qy) <= e.y <= max(py, qy):
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
            if self.v_lock.get() and bb > 0:          # Seitenverhaeltnis halten
                nb = max(nb, 1.0); nh = nb * bh / bb
            nb, nh = max(2.0, nb), max(2.0, nh)
            x = bx + bb - nb if links else bx
            y = by + bh - nh if unten else by
            # Kanten und Mitte des Werkstuecks als Rastpunkte
            if links:
                x = self._snap(x, [self._xmin(), (W - nb) / 2], tol)
                nb = bx + bb - x
            else:
                rechts = self._snap(x + nb, [W, W / 2], tol); nb = rechts - x
            if self.v_lock.get() and bb > 0:
                nh = nb * bh / bb
                if unten: y = by + bh - nh
            self._set_box(x, y, nb, nh)
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
        key = (w_px, h_px, rot, inv, sp, glatt, id(self.src))
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


def main():
    cfg = P.load_config()
    lw_text.setze(cfg.get("sprache", "de"))
    root = tk.Tk()
    S.apply(root, cfg.get("theme", "dunkel"))
    root.minsize(1100, 720)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
