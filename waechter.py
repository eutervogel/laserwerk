#!/usr/bin/env python3
"""Waechter: schaut dem laufenden Laserwerk ueber die Schulter.

Meldet per Telegram, bevor die Zeilen durch sind und wenn das Schneiden
anfaengt - fuer lange Jobs, bei denen man nicht stundenlang auf das
Geblinke schauen will.

Er laeuft als eigener Prozess neben der Oberflaeche, die Software muss
dafuer nicht neu gestartet werden. Zwei Dinge tut er bewusst nicht:

* Er schreibt nichts in den laufenden Prozess und nichts an den
  Controller. Ueber "tk send" holt er nur die Texte der Anzeigefelder
  aus dem Tk-Interpreter - lesend, wie ein Blick auf den Bildschirm.
  Die serielle Schnittstelle fasst er nicht an.
* Er ruft bei Telegram nur sendMessage, niemals getUpdates. getUpdates
  darf nur einer, und das ist der Bot in der laufenden Software - zwei
  Abholer bekommen HTTP 409 und nehmen sich gegenseitig die Nachrichten
  weg.

Aufruf:
    python3 waechter.py                  # Vorwarnung 10 min vorher
    python3 waechter.py --vorlauf 20     # ... oder 20 min vorher
    python3 waechter.py --lesen          # einmal hinsehen, nichts senden
"""

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DIR = os.path.expanduser("~/.config/laserwerk")
TELEGRAMDATEI = os.path.join(DIR, "telegram.json")
API = "https://api.telegram.org/bot{t}/{m}"

# Die Anzeigefelder, an denen er sich festhaelt. Deutsch und Englisch, weil
# lw_text beides kann und die Sprache mitten im Job umgestellt werden darf.
MARKE = re.compile(r"\b(Zeile|Kontur|Row|Contour)\s+(\d+)\s+(?:von|of)\s+(\d+)")
# Das Fortschrittsfeld, genau gefasst: "6 %   noch ~626 min" bzw.
# "6 %   ~626 min left". Lose nach einem Prozentzeichen zu suchen greift
# daneben - in den Hilfetexten stehen auch Prozentwerte.
PROG = re.compile(r"^\s*(\d+)\s*%\s+(?:\w+\s+)?~\s*(\d+)\s*min")
# Am Jobende steht im Fortschrittsfeld "Datei: fertig" - ohne Prozentzeichen.
ENDE = re.compile(r":\s*(?:fertig|abgebrochen|ALARM|Verbindung|zu viele"
                  r"|done|aborted|lost|too many)", re.I)
# Daran erkennt er, dass er den richtigen Interpreter vor sich hat. Ein
# einziges Merkmal waere zu wenig - auf eine Vorwarnung aus dem falschen
# Fenster koennte man sich nicht verlassen. Diese Felder stehen immer da,
# auch ohne Job.
KENNUNGEN = (re.compile(r"Nullpunkt|Zero point"),
             re.compile(r"Arbeitsbereich|Work area"),
             re.compile(r"Materialdicke|Material thickness"),
             re.compile(r"Vorschau|Preview"))


def erkannt(texte):
    """Mindestens zwei Merkmale - dann ist es Laserwerk und nicht
    irgendein anderes Tk-Fenster am Display."""
    return sum(any(k.search(t) for t in texte) for k in KENNUNGEN) >= 2

# Tcl, das im fremden Interpreter laeuft: alle Widgets ablaufen und die
# -text-Eigenschaft einsammeln. Kein Schreibzugriff, kein Seiteneffekt.
SKRIPT = r"""
set aus {}
set offen {.}
while {[llength $offen]} {
    set w [lindex $offen 0]
    set offen [concat [lrange $offen 1 end] [winfo children $w]]
    if {![catch {$w cget -text} t] && $t ne ""} { lappend aus $t }
}
join $aus "\u001f"
"""


# ----------------------------------------------------------------- lesen
def interps():
    """Alle Tk-Interpreter am Display, so wie sie in der Registry stehen."""
    try:
        aus = subprocess.run(["xprop", "-root", "InterpRegistry"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    m = re.search(r'=\s*(.*)', aus)
    if not m:
        return []
    return [t.strip().strip('"').split(" ", 1)[1]
            for t in m.group(1).split('", "') if " " in t.strip().strip('"')]


def lese_direkt(interp):
    """Texte aus dem fremden Interpreter holen. Blockiert, wenn dessen
    Ereignisschleife steht - deshalb nur im Kindprozess aufrufen."""
    import tkinter
    r = tkinter.Tk()
    r.withdraw()
    try:
        return r.tk.call("send", interp, SKRIPT).split("\x1f")
    finally:
        r.destroy()


def lese(interp, frist=20.0):
    """Texte holen, aber mit Frist: ein eigener Prozess, der notfalls
    abgeraeumt wird. Ein haengendes send darf den Waechter nicht mitnehmen."""
    try:
        p = subprocess.run([sys.executable, os.path.abspath(__file__),
                            "--lesen", "--interp", interp, "--roh"],
                           capture_output=True, text=True, timeout=frist)
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except ValueError:
        return None


def finde(frist=20.0):
    """Den Interpreter finden, der nach Laserwerk aussieht."""
    for name in interps():
        texte = lese(name, frist)
        if texte and erkannt(texte):
            return name, texte
    return None, None


def deuten(texte):
    """Aus den Feldtexten herausziehen, was zaehlt."""
    d = {"art": None, "nr": None, "gesamt": None, "prozent": None,
         "restmin": None, "zustand": None, "marke": "", "prog": "",
         "schluss": ""}
    for t in texte:
        m = MARKE.search(t)
        if m:
            d["art"] = "kontur" if m.group(1) in ("Kontur", "Contour") else "zeile"
            d["nr"], d["gesamt"] = int(m.group(2)), int(m.group(3))
            d["marke"] = t
            continue
        mp = PROG.match(t)
        if mp and "\n" not in t:
            d["prog"] = t
            d["prozent"], d["restmin"] = int(mp.group(1)), int(mp.group(2))
            continue
        if ENDE.search(t):
            d["schluss"] = t
            continue
        if "|" in t and ("Vorschub" in t or "Feed" in t):
            teile = [x.strip() for x in t.split("|")]
            if len(teile) > 1:
                d["zustand"] = teile[1]
    return d


# -------------------------------------------------------------- telegram
def zugang():
    with open(TELEGRAMDATEI, encoding="utf-8") as f:
        d = json.load(f)
    if not d.get("token") or not d.get("chat"):
        raise SystemExit("In %s fehlen token oder chat - erst in der "
                         "Oberflaeche den Bot verknuepfen." % TELEGRAMDATEI)
    return d["token"], d["chat"]


def senden(token, chat, text, versuche=3):
    """Nur sendMessage. Scheitert es, wird es protokolliert, nicht geworfen -
    ein Netzaussetzer darf den Waechter nicht beenden."""
    daten = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    for i in range(versuche):
        try:
            with urllib.request.urlopen(
                    API.format(t=token, m="sendMessage"), data=daten,
                    timeout=20) as a:
                if json.load(a).get("ok"):
                    return True
        except (urllib.error.URLError, OSError, ValueError) as e:
            melde("Telegram-Fehler: %s" % e)
        time.sleep(2 + 3 * i)
    return False


def melde(text):
    print("%s  %s" % (time.strftime("%H:%M:%S"), text), flush=True)


# ------------------------------------------------------------------ Lauf
SPANNE = 120.0        # so lange muss gemessen sein, bevor er hochrechnet


def rate(proben):
    """Zeilen pro Sekunde aus den Proben der letzten Minuten.
    None, solange die Spanne zu kurz ist, um daraus etwas zu schliessen."""
    if len(proben) < 2:
        return None
    (t0, n0), (t1, n1) = proben[0], proben[-1]
    if t1 - t0 < SPANNE or n1 <= n0:
        return None
    return (n1 - n0) / (t1 - t0)


def dauer(sek):
    if sek is None:
        return "?"
    if sek < 90:
        return "%.0f s" % sek
    return "%.0f min" % (sek / 60)


def uhrzeit(sek):
    """Restzeit als Uhrzeit - danach schaut man leichter als nach Minuten."""
    if sek is None:
        return ""
    return time.strftime(" (gegen %H:%M)", time.localtime(time.time() + sek))


def wachen(a):
    token, chat = zugang()
    if a.interp:
        interp, texte = a.interp, lese(a.interp, a.frist)
    else:
        interp, texte = finde()
    if not interp or not texte:
        raise SystemExit("Kein Laserwerk-Interpreter am Display gefunden. "
                         "Laeuft die Oberflaeche, und ist DISPLAY richtig?")
    melde("Interpreter: %r" % interp)
    d = deuten(texte)
    melde("Stand: %s | %s | %s" % (d["marke"] or "-", d["prog"] or "-",
                                   d["zustand"] or "-"))

    if a.startmeldung:
        senden(token, chat, "Wächter läuft. Stand: %s%s\nIch melde mich "
               "%g min vor dem Ende der Zeilen und wenn das Schneiden "
               "anfängt." % (d["marke"] or "noch keine Marke",
                             ("  (" + d["prog"] + ")") if d["prog"] else "",
                             a.vorlauf))

    proben = collections.deque(maxlen=200)
    vorgewarnt = geschnitten = ausgefallen = False
    gesehen = False          # schon mal eine Marke gesehen? (fuer "Job vorbei")
    fehl = 0

    while True:
        # Ein unerwarteter Fehler darf den Waechter nicht still beenden -
        # sonst wartet man hinter dem Sichtschutz auf eine Meldung, die
        # nie kommt.
        try:
            texte = lese(interp, a.frist)
            if texte is None or not erkannt(texte):
                fehl += 1
                melde("kein Blick moeglich (%d. Mal)" % fehl)
                if fehl >= a.ausfall and not ausgefallen:
                    ausgefallen = True
                    senden(token, chat, "Ich sehe die Laserwerk-Oberfläche "
                           "seit %d Versuchen nicht mehr. Entweder ist sie zu "
                           "oder sie hängt. Bitte einmal hinsehen." % fehl)
                time.sleep(a.takt)
                continue
            if ausgefallen:
                ausgefallen = False
                senden(token, chat, "Ich sehe die Oberfläche wieder.")
            fehl = 0

            d = deuten(texte)

            # --- Job vorbei?
            if d["art"] is None:
                if gesehen:
                    gesehen = False
                    senden(token, chat, "Keine Marke mehr in der Anzeige - "
                           "der Job ist durch oder gestoppt.\n%s"
                           % (d["schluss"] or d["prog"] or ""))
                time.sleep(a.takt)
                continue
            gesehen = True

            # --- Schneiden angefangen?
            if d["art"] == "kontur":
                if not geschnitten:
                    geschnitten = True
                    senden(token, chat, "Jetzt wird geschnitten: %s\n%s%s"
                           % (d["marke"], d["prog"] or "",
                              ("\nZustand: " + d["zustand"])
                              if d["zustand"] else ""))
                    melde("Meldung: Schneiden faengt an")
                time.sleep(a.takt)
                continue

            # --- Zeilen: Vorwarnung
            proben.append((time.time(), d["nr"]))
            rest_zeilen = d["gesamt"] - d["nr"]
            r = rate(proben)
            rest_sek = rest_zeilen / r if r else None
            melde("Zeile %d von %d, noch %d, %s/Zeile, Rest %s"
                  % (d["nr"], d["gesamt"], rest_zeilen,
                     ("%.1f s" % (1 / r)) if r else "?", dauer(rest_sek)))

            if not vorgewarnt and (rest_zeilen <= a.rest
                                   or (rest_sek is not None
                                       and rest_sek <= a.vorlauf * 60)):
                vorgewarnt = True
                senden(token, chat,
                       "Die Zeilen sind fast durch: %s, noch %d Zeilen"
                       "%s%s.\nWenn danach Konturen kommen, fängt das "
                       "Schneiden an - ich melde mich dann nochmal.%s"
                       % (d["marke"], rest_zeilen,
                          (", geschätzt " + dauer(rest_sek)) if rest_sek else "",
                          uhrzeit(rest_sek),
                          ("\n" + d["prog"]) if d["prog"] else ""))
                melde("Meldung: Vorwarnung")

        except Exception as e:
            melde("Fehler in der Runde: %r" % e)
        time.sleep(a.takt)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--vorlauf", type=float, default=10.0,
                   help="Minuten vor dem Ende der Zeilen warnen (Vorgabe 10)")
    p.add_argument("--rest", type=int, default=5,
                   help="... oder spaetestens so viele Zeilen vorher (5)")
    p.add_argument("--takt", type=float, default=30.0,
                   help="Sekunden zwischen zwei Blicken (30)")
    p.add_argument("--frist", type=float, default=20.0,
                   help="Sekunden, die ein Blick hoechstens dauern darf (20)")
    p.add_argument("--ausfall", type=int, default=3,
                   help="So viele erfolglose Blicke, dann Alarm (3)")
    p.add_argument("--interp", default=None, help="Tk-Interpreter (sonst suchen)")
    p.add_argument("--lesen", action="store_true",
                   help="einmal hinsehen, nichts senden")
    p.add_argument("--roh", action="store_true", help="Texte als JSON (intern)")
    p.add_argument("--ohne-startmeldung", dest="startmeldung",
                   action="store_false", help="beim Start nichts senden")
    a = p.parse_args()

    if a.lesen:
        if a.interp and a.roh:
            print(json.dumps(lese_direkt(a.interp)))
            return
        interp, texte = (a.interp, lese(a.interp, a.frist)) if a.interp else finde()
        if not texte:
            raise SystemExit("nichts zu lesen")
        print("Interpreter: %r" % interp)
        for t in texte:
            print("  %s" % t.replace("\n", " / "))
        print(json.dumps(deuten(texte), ensure_ascii=False, indent=1))
        return

    wachen(a)


if __name__ == "__main__":
    main()
