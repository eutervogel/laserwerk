"""
Native Desktop-Dialoge ueber zenity (GTK) statt der Tk-eigenen.

Stellt 'filedialog' und 'messagebox' mit denselben Aufrufen bereit wie
tkinter, damit der restliche Code unveraendert bleibt. Fehlt zenity,
wird auf die Tk-Dialoge zurueckgegriffen.
"""
import os, shutil, subprocess
from tkinter import filedialog as _tkf, messagebox as _tkm

from lw_text import T

ZENITY = shutil.which("zenity")

# Wie viele Dialoge gerade offen sind. Ein Dialog wartet auf einen Menschen,
# und solange steht die Oberflaeche still - das ist kein Haenger. Der
# Wachhund in laserwerk.py sieht hier nach, bevor er bellt.
LAEUFT = 0


def _esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _z(args):
    global LAEUFT
    LAEUFT += 1
    try:
        r = subprocess.run([ZENITY, "--width=440"] + args,
                           capture_output=True, text=True)
    finally:
        LAEUFT -= 1
    return r.returncode, r.stdout.strip()


class _FileDialog:
    def askopenfilename(self, title=None, initialdir=None, filetypes=None, **kw):
        title = title or T("Datei öffnen")
        if not ZENITY:
            return _tkf.askopenfilename(title=title, initialdir=initialdir,
                                        filetypes=filetypes or [(T("alle"), "*")])
        args = ["--file-selection", f"--title={title}"]
        if initialdir:
            args.append(f"--filename={os.path.join(initialdir, '')}")
        for name, pat in (filetypes or []):
            args.append(f"--file-filter={name} | {pat}")
        rc, out = _z(args)
        return out if rc == 0 else ""

    def askopenfilenames(self, title=None, initialdir=None, filetypes=None,
                         **kw):
        """Mehrere Dateien auf einmal. Gibt immer ein Tupel zurueck, auch
        wenn der Benutzer abbricht - dann ein leeres."""
        title = title or T("Dateien öffnen")
        if not ZENITY:
            return tuple(_tkf.askopenfilenames(
                title=title, initialdir=initialdir,
                filetypes=filetypes or [(T("alle"), "*")]) or ())
        args = ["--file-selection", "--multiple", "--separator=\n",
                f"--title={title}"]
        if initialdir:
            args.append(f"--filename={os.path.join(initialdir, '')}")
        for name, pat in (filetypes or []):
            args.append(f"--file-filter={name} | {pat}")
        rc, out = _z(args)
        if rc != 0:
            return ()
        return tuple(z for z in out.splitlines() if z)

    def asksaveasfilename(self, title=None, initialdir=None,
                          initialfile="", defaultextension="", **kw):
        title = title or T("Speichern unter")
        if not ZENITY:
            return _tkf.asksaveasfilename(title=title, initialdir=initialdir,
                                          initialfile=initialfile,
                                          defaultextension=defaultextension)
        start = os.path.join(initialdir or os.getcwd(), initialfile or "")
        rc, out = _z(["--file-selection", "--save", "--confirm-overwrite",
                      f"--title={title}", f"--filename={start}"])
        if rc != 0 or not out:
            return ""
        if defaultextension and not os.path.splitext(out)[1]:
            out += defaultextension
        return out


class _MessageBox:
    def _msg(self, kind, title, text):
        if not ZENITY:
            return getattr(_tkm, {"info": "showinfo", "warning": "showwarning",
                                  "error": "showerror"}[kind])(title, text)
        _z([f"--{kind}", f"--title={title}", f"--text={_esc(text)}"])

    def showinfo(self, title, text, **kw):
        self._msg("info", title, text)

    def showwarning(self, title, text, **kw):
        self._msg("warning", title, text)

    def showerror(self, title, text, **kw):
        self._msg("error", title, text)

    def _ask(self, title, text, yes, no, fallback):
        if not ZENITY:
            return fallback(title, text)
        rc, _ = _z(["--question", f"--title={title}", f"--text={_esc(text)}",
                    f"--ok-label={yes}", f"--cancel-label={no}"])
        return rc == 0

    def askyesno(self, title, text, **kw):
        return self._ask(title, text, "Ja", "Nein", _tkm.askyesno)

    def askokcancel(self, title, text, **kw):
        return self._ask(title, text, "OK", "Abbrechen", _tkm.askokcancel)

    def askyesnocancel(self, title, text, **kw):
        """Drei Antworten: ja, nein, abbrechen.

        Die gab es hier nicht, obwohl laserwerk danach fragt - das endete
        mitten in der Warnung vor ungleichen Schnittwerten in einem
        AttributeError, also genau dort, wo sie am noetigsten ist.

        zenity kennt nur zwei Knoepfe. Ein dritter geht als --extra-button,
        und der meldet sich nicht ueber den Rueckgabewert, sondern ueber
        seine Beschriftung auf der Ausgabe.
        """
        if not ZENITY:
            return _tkm.askyesnocancel(title, text)
        rc, out = _z(["--question", f"--title={title}", f"--text={_esc(text)}",
                      "--ok-label=Ja", "--cancel-label=Abbrechen",
                      "--extra-button=Nein"])
        if rc == 0:
            return True
        return False if out == "Nein" else None


filedialog = _FileDialog()
messagebox = _MessageBox()
