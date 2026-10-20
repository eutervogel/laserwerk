"""
Erscheinungsbild mit hellem und dunklem Farbschema.

Die Farbwerte stehen als Modulvariablen (S.BG, S.ACCENT ...) bereit und
werden von apply() auf das gewaehlte Schema gesetzt. Code, der S.* erst
beim Zeichnen liest, folgt einem Wechsel automatisch.
"""
import os
import tkinter as tk
from tkinter import ttk, font as tkfont

THEMES = {
    "dunkel": dict(
        BG="#1f2124", PANEL="#2a2d31", LINE="#3a3e44", TEXT="#e3e5e8", MUTED="#9aa0a8",
        ACCENT="#4a8fe0", ACCENT_H="#3c7bc7", DANGER="#d9534a", DANGER_H="#bf463e",
        SEL="#34465e", BTN="#33373c", BTN_H="#3d4248", BTN_P="#474c53",
        TAB="#26292d", TAB_H="#2f3337", TROUGH="#2c2f33", STATUS="#26292d",
        CANVAS_BG="#26282b", CANVAS_GRID="#2f3236", CANVAS_GRID2="#3b3f45",
        CANVAS_EDGE="#555a61", GTK="Adwaita:dark"),
    "hell": dict(
        BG="#f2f2f0", PANEL="#fbfbfa", LINE="#d4d4cf", TEXT="#2b2d30", MUTED="#6c7075",
        ACCENT="#3a78c9", ACCENT_H="#2f66ad", DANGER="#c8443b", DANGER_H="#a9362e",
        SEL="#dbe7f6", BTN="#e9e8e4", BTN_H="#dfddd8", BTN_P="#d7d5cf",
        TAB="#e5e4e0", TAB_H="#ecebe7", TROUGH="#e1e0db", STATUS="#e9e8e4",
        CANVAS_BG="#ffffff", CANVAS_GRID="#ecebe7", CANVAS_GRID2="#d9d7d0",
        CANVAS_EDGE="#b8b5ab", GTK="Adwaita"),
}

THEME = "dunkel"
globals().update(THEMES[THEME])


def apply(root, theme=None):
    global THEME
    THEME = theme if theme in THEMES else THEME
    globals().update(THEMES[THEME])
    # zenity-Dialoge im selben Schema starten
    os.environ["GTK_THEME"] = GTK

    fam = "Noto Sans" if "Noto Sans" in tkfont.families(root) else "DejaVu Sans"
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont",
                 "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):
        try:
            tkfont.nametofont(name).configure(family=fam, size=10)
        except tk.TclError:
            pass
    root.configure(bg=BG)
    for k, v in (("*Listbox.background", PANEL), ("*Listbox.foreground", TEXT),
                 ("*Listbox.selectBackground", SEL), ("*Listbox.selectForeground", TEXT),
                 ("*Listbox.relief", "flat"), ("*Listbox.highlightThickness", 1),
                 ("*Listbox.highlightColor", LINE), ("*Listbox.highlightBackground", LINE),
                 ("*TCombobox*Listbox.background", PANEL),
                 ("*TCombobox*Listbox.foreground", TEXT),
                 ("*TCombobox*Listbox.selectBackground", SEL),
                 ("*TCombobox*Listbox.selectForeground", TEXT)):
        root.option_add(k, v)

    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, bordercolor=LINE,
                lightcolor=BG, darkcolor=BG, troughcolor=TROUGH,
                focuscolor=ACCENT, fieldbackground=PANEL, font=(fam, 10),
                selectbackground=SEL, selectforeground=TEXT,
                insertcolor=TEXT)
    s.configure("TFrame", background=BG)
    s.configure("TLabel", background=BG, foreground=TEXT)
    s.configure("Muted.TLabel", background=BG, foreground=MUTED)
    s.configure("Pos.TLabel", background=BG, foreground=TEXT, font=("DejaVu Sans Mono", 12))
    s.configure("TLabelframe", background=BG, bordercolor=LINE, relief="solid",
                borderwidth=1, padding=8, lightcolor=BG, darkcolor=BG)
    s.configure("TLabelframe.Label", background=BG, foreground=MUTED, font=(fam, 9, "bold"))

    s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 4, 0, 0),
                lightcolor=BG, darkcolor=BG, bordercolor=LINE)
    s.configure("TNotebook.Tab", background=TAB, foreground=MUTED, padding=(14, 6),
                borderwidth=0, lightcolor=TAB, darkcolor=TAB, bordercolor=LINE)
    s.map("TNotebook.Tab",
          background=[("selected", PANEL), ("active", TAB_H)],
          foreground=[("selected", TEXT)],
          lightcolor=[("selected", PANEL)], darkcolor=[("selected", PANEL)])

    s.configure("TButton", background=BTN, foreground=TEXT, bordercolor=LINE,
                lightcolor=BTN, darkcolor=BTN, padding=(10, 5), relief="flat",
                focusthickness=0)
    s.map("TButton",
          background=[("pressed", BTN_P), ("active", BTN_H)],
          lightcolor=[("active", BTN_H)], darkcolor=[("active", BTN_H)],
          foreground=[("disabled", MUTED)])
    for name, c, ch in (("Accent", ACCENT, ACCENT_H), ("Danger", DANGER, DANGER_H)):
        s.configure(f"{name}.TButton", background=c, foreground="white",
                    bordercolor=c, lightcolor=c, darkcolor=c,
                    font=(fam, 10, "bold"), padding=(12, 6))
        s.map(f"{name}.TButton",
              background=[("pressed", ch), ("active", ch)],
              bordercolor=[("active", ch)], lightcolor=[("active", ch)],
              darkcolor=[("active", ch)])

    s.configure("TEntry", fieldbackground=PANEL, foreground=TEXT, bordercolor=LINE,
                lightcolor=PANEL, darkcolor=PANEL, padding=4, insertcolor=TEXT)
    s.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])
    s.configure("TSpinbox", fieldbackground=PANEL, foreground=TEXT, background=BTN,
                bordercolor=LINE, lightcolor=PANEL, darkcolor=PANEL, arrowsize=12,
                padding=3, arrowcolor=TEXT, insertcolor=TEXT)
    s.configure("TCombobox", fieldbackground=PANEL, foreground=TEXT, background=BTN,
                bordercolor=LINE, lightcolor=PANEL, darkcolor=PANEL, arrowsize=14,
                padding=3, arrowcolor=TEXT, insertcolor=TEXT)
    s.map("TCombobox", fieldbackground=[("readonly", PANEL)],
          foreground=[("readonly", TEXT)], selectbackground=[("readonly", PANEL)],
          selectforeground=[("readonly", TEXT)], bordercolor=[("focus", ACCENT)],
          background=[("active", BTN_H)])
    for w in ("TCheckbutton", "TRadiobutton"):
        s.configure(w, background=BG, foreground=TEXT, indicatorcolor=PANEL,
                    indicatorbackground=PANEL, indicatorforeground="white",
                    padding=(2, 3), upperbordercolor=MUTED, lowerbordercolor=MUTED,
                    indicatorsize=13)
        # clam malt die Markierung mit indicatorforeground auf indicatorbackground:
        # ausgewaehlt = blau gefuellt mit weisser Markierung, gut sichtbar
        s.map(w, indicatorbackground=[("selected", ACCENT), ("pressed", SEL)],
              indicatorcolor=[("selected", ACCENT), ("pressed", SEL)],
              upperbordercolor=[("selected", ACCENT)], lowerbordercolor=[("selected", ACCENT)],
              background=[("active", BG)], foreground=[("active", TEXT)])
    s.configure("Horizontal.TScale", background=BTN, troughcolor=TROUGH,
                bordercolor=LINE, lightcolor=BTN, darkcolor=BTN)
    s.map("Horizontal.TScale", background=[("active", BTN_H)])
    s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=TROUGH,
                bordercolor=LINE, lightcolor=ACCENT, darkcolor=ACCENT, thickness=10)
    s.configure("TSeparator", background=LINE)
    s.configure("Status.TLabel", background=STATUS, foreground=MUTED, padding=(8, 4))
    return fam


def restyle_widgets(widgets):
    """Klassische Tk-Widgets (Canvas, Text, Listbox) nachfaerben."""
    for w in widgets:
        cls = w.winfo_class()
        if cls == "Canvas":
            w.configure(bg=CANVAS_BG, highlightbackground=LINE)
        elif cls in ("Text", "Listbox"):
            w.configure(bg=PANEL, fg=TEXT, highlightbackground=LINE,
                        selectbackground=SEL, selectforeground=TEXT)
            if cls == "Text":
                w.configure(insertbackground=TEXT)
