"""
Native Desktop-Dialoge ueber zenity (GTK) statt der Tk-eigenen.

Stellt 'filedialog' und 'messagebox' mit denselben Aufrufen bereit wie
tkinter, damit der restliche Code unveraendert bleibt. Fehlt zenity,
wird auf die Tk-Dialoge zurueckgegriffen.
"""
import os, shutil, subprocess
from tkinter import filedialog as _tkf, messagebox as _tkm

ZENITY = shutil.which("zenity")


def _esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _z(args):
    r = subprocess.run([ZENITY, "--width=440"] + args, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


class _FileDialog:
    def askopenfilename(self, title="Datei oeffnen", initialdir=None, filetypes=None, **kw):
        if not ZENITY:
            return _tkf.askopenfilename(title=title, initialdir=initialdir,
                                        filetypes=filetypes or [("alle", "*")])
        args = ["--file-selection", f"--title={title}"]
        if initialdir:
            args.append(f"--filename={os.path.join(initialdir, '')}")
        for name, pat in (filetypes or []):
            args.append(f"--file-filter={name} | {pat}")
        rc, out = _z(args)
        return out if rc == 0 else ""

    def asksaveasfilename(self, title="Speichern unter", initialdir=None,
                          initialfile="", defaultextension="", **kw):
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


filedialog = _FileDialog()
messagebox = _MessageBox()
