"""
Fernsteuerung ueber Telegram - Achsen fahren und Sichtkreuz vom Handy aus.

Gedacht fuer das Einrichten am Werkstueck: man steht an der Maschine, nicht
am Rechner, und tippt sich Schritt fuer Schritt auf die Ecke.

Grenzen, bewusst gesetzt:
  - Kein Jobstart ueber den Bot. Gravur/Schnitt faehrt mit voller Leistung
    und darf nur dort ausgeloest werden, wo man auch hinsieht.
  - Das Sichtkreuz laeuft mit demselben S/F-Deckel wie im Programm (0,20).
  - Waehrend eines laufenden Jobs sind nur Status, Laser aus und STOPP frei.
  - Ein Schritt ist auf 50 mm begrenzt.

Technik: Bordmittel, keine Fremdbibliothek. Drei Threads, bewusst getrennt,
damit nichts aufeinander wartet:
  Lesen    haengt im Long-Poll (getUpdates) und legt Eingaenge nur ab,
  Arbeiten fuehrt sie der Reihe nach aus und wartet auf die Maschine,
  Senden   schickt Meldungen raus.
Jeder Thread haelt seine HTTPS-Verbindung offen; sonst kostet jeder
Tastendruck erneut Namensaufloesung, TCP und TLS. Alles, was die Oberflaeche
oder tkinter-Variablen beruehrt, laeuft nicht hier, sondern wird ueber die
Ereignisschlange der App im Hauptthread ausgefuehrt. /zeiten zeigt, wo die
Wartezeit zwischen Tastendruck und Fahrt tatsaechlich hingeht.
"""
import http.client, json, os, queue, threading, time
import urllib.parse, urllib.request

import lw_presets as P
from lw_text import T

DATEI = os.path.join(P.DIR, "telegram.json")
API = "https://api.telegram.org/bot{t}/{m}"
VERBINDEN = 12.0          # Sekunden fuer den Verbindungsaufbau
SCHRITTE = [0.1, 0.5, 1.0, 5.0, 10.0, 50.0]
MAX_SCHRITT = 50.0

def hilfe():
    return T(
        "Laserwerk-Fernsteuerung\n\n"
        "/pad - Steuerkreuz schicken\n"
        "/pos - Position\n"
        "/x 5   /y -2.5   /z 0.3 - einzeln fahren (max. 50 mm)\n"
        "/schritt 1 - Schrittweite fuer das Pad\n"
        "/kreuz - Sichtkreuz an der Stelle fahren\n"
        "/null - Nullpunkt XY = hier\n"
        "/heim - zum Nullpunkt fahren\n"
        "/aus - Laser aus (M5)\n"
        "/stopp - Halt und Soft-Reset\n"
        "/status - Verbindung, Zustand, Job\n"
        "/zeiten - wo die Wartezeit herkommt\n\n"
        "Gravur und Schnitt werden absichtlich nur am Rechner gestartet.")


def lade():
    try:
        with open(DATEI) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"token": "", "chat": None, "schritt": 1.0, "auto": False}


def sichere(d):
    os.makedirs(P.DIR, exist_ok=True)
    with open(DATEI, "w") as f:
        json.dump(d, f, indent=1)
    try:
        os.chmod(DATEI, 0o600)        # der Token ist ein Schluessel zur Maschine
    except OSError:
        pass


class Fern:
    def __init__(self, app):
        self.app = app
        d = lade()
        self.token = d.get("token", "")
        self.chat = d.get("chat")
        self.schritt = d.get("schritt", 1.0)
        self.aktiv = False
        self.offset = 0
        self.raus = queue.Queue()        # Meldungen ans Handy
        self.auftraege = queue.Queue()   # eingegangene Befehle
        self.pad_id = None            # Nachricht mit dem Steuerkreuz
        self.fehler = ""
        self.messungen = []           # letzte Laufzeiten, fuer /zeiten
        self.http = {}                # Dauer je Telegram-Aufruf
        self.leitungen = {}           # gehaltene Verbindung je Thread

    # ---------------------------------------------------------- Telegram
    def _leitung(self, neu=False):
        """Eine offen gehaltene Verbindung je Thread. Spart bei jedem
        Tastendruck Namensaufloesung, TCP und TLS - und ein hakeliger Weg
        (etwa totes IPv6) wird einmal durchlitten statt jedes Mal."""
        th = threading.current_thread()
        c = self.leitungen.get(th)
        if c is not None and not neu:
            return c
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
        u = urllib.parse.urlsplit(API.format(t=self.token, m="x"))
        art = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        c = art(u.netloc, timeout=VERBINDEN)
        self.leitungen[th] = c
        return c

    def _api(self, methode, frist=40, **daten):
        """frist = Geduld beim Warten auf die Antwort; 'timeout' in daten ist
        das Long-Poll-Fenster von Telegram selbst."""
        pfad = urllib.parse.urlsplit(API.format(t=self.token, m=methode)).path
        koerper = json.dumps(daten).encode()
        kopf = {"Content-Type": "application/json", "Connection": "keep-alive"}
        t0 = time.time()
        try:
            for versuch in (1, 2):
                c = self._leitung(neu=(versuch == 2))
                try:
                    c.request("POST", pfad, koerper, kopf)
                    if c.sock is not None:
                        c.sock.settimeout(frist)   # Antwort darf laenger dauern
                    r = c.getresponse()
                    roh = r.read()
                    if r.status != 200:
                        d = json.loads(roh or b"{}")
                        raise RuntimeError(f"HTTP {r.status}: "
                                           f"{d.get('description', '')}"
                                           f" {d.get('parameters', '')}".strip())
                    return json.loads(roh)
                except (OSError, http.client.HTTPException) as e:
                    # Gegenstelle hat die Leitung zugemacht: einmal neu aufbauen
                    if versuch == 2:
                        raise RuntimeError(str(e) or e.__class__.__name__)
        finally:
            self.http[methode] = time.time() - t0

    def pruefe(self):
        """Token testen. Gibt den Botnamen zurueck oder wirft."""
        r = self._api("getMe", frist=15)
        return r["result"].get("username", "?")

    def start(self):
        if self.aktiv:
            return
        if not self.token:
            raise ValueError(T("Kein Token hinterlegt."))
        name = self.pruefe()
        self.aktiv = True
        self._alte_ueberspringen()
        threading.Thread(target=self._lesen, daemon=True).start()
        threading.Thread(target=self._arbeiten, daemon=True).start()
        threading.Thread(target=self._senden, daemon=True).start()
        if self.chat:
            self.melde(T("Laserwerk ist da. /pad fuer das Steuerkreuz."))
        return name

    def stop(self):
        self.aktiv = False
        for c in list(self.leitungen.values()):
            try:
                c.close()
            except Exception:
                pass
        self.leitungen.clear()

    def _alte_ueberspringen(self):
        """Nachrichten von vorhin nicht nachtraeglich ausfuehren - sonst faehrt
        die Maschine beim Start Befehle von gestern."""
        try:
            r = self._api("getUpdates", frist=15, offset=-1)
            for u in r.get("result", []):
                self.offset = max(self.offset, u["update_id"] + 1)
        except Exception:
            pass

    def melde(self, text):
        if self.aktiv and self.chat:
            self.raus.put(text)

    def _senden(self):
        while self.aktiv:
            try:
                t = self.raus.get(timeout=1.0)
            except queue.Empty:
                continue
            for versuch in (1, 2):
                try:
                    self._api("sendMessage", frist=20, chat_id=self.chat, text=t)
                    break
                except Exception as e:
                    if versuch == 2:
                        self._log(T("Telegram: Meldung nicht zugestellt ({e}): {t}"
                                    ).format(e=e, t=t))
                    else:
                        time.sleep(2)

    def _lesen(self):
        ruhe = 1
        ende = time.time()
        while self.aktiv:
            luecke = time.time() - ende     # Zeit ohne offene Abfrage
            try:
                r = self._api("getUpdates", frist=45, offset=self.offset,
                              timeout=30, allowed_updates=["message", "callback_query"])
            except Exception as e:
                self.fehler = str(e)
                if "409" in str(e):
                    self._log(T("Telegram: 409 - der Bot wird anderswo schon "
                              "abgefragt (zweites Laserwerk offen?)"))
                else:
                    self._log(T('Telegram: {0}').format(e))
                time.sleep(min(60, ruhe)); ruhe = min(60, ruhe * 2)
                continue
            ende = time.time()
            ruhe = 1
            self.fehler = ""
            for u in (r or {}).get("result", []):
                self.offset = u["update_id"] + 1
                # Der Lesethread darf nie auf die Maschine warten, sonst holt
                # er den naechsten Tastendruck erst nach der Fahrt ab.
                self.auftraege.put((time.time(), luecke, u))

    def _arbeiten(self):
        """Befehle der Reihe nach ausfuehren, getrennt vom Abholen."""
        while self.aktiv:
            try:
                empfang, luecke, u = self.auftraege.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._update(u, empfang, luecke)
            except Exception as e:
                self._log(T('Telegram: {0}').format(e))

    # ---------------------------------------------------------- Eingang
    def _update(self, u, empfang=None, luecke=0.0):
        t0 = time.time()
        warten = t0 - empfang if empfang else 0.0
        if "callback_query" in u:
            c = u["callback_query"]
            chat = c["message"]["chat"]["id"]
            if not self._erlaubt(chat, ""):
                return
            self.pad_id = c["message"]["message_id"]
            # Erst quittieren, dann fahren: sonst dreht sich die Uhr auf dem
            # Knopf so lange, wie die Maschine braucht.
            try:
                self._api("answerCallbackQuery", frist=15, callback_query_id=c["id"],
                          text=self._etikett(c.get("data", "")))
            except Exception:
                pass
            quittiert = time.time()
            text = self._knopf(c.get("data", ""))
            getan = time.time()
            self._pad_auffrischen(text)
            self._messe("Knopf", None, warten, luecke, quittiert - t0,
                        getan - quittiert, time.time() - getan)
            return
        m = u.get("message") or u.get("edited_message")
        if not m or "text" not in m:
            return
        chat, text = m["chat"]["id"], m["text"].strip()
        if not self._erlaubt(chat, text):
            return
        alter = time.time() - m["date"] if m.get("date") else None
        self._befehl(text)
        self._messe(text.split()[0][:12], alter, warten, luecke, 0.0,
                    time.time() - t0, 0.0)

    def _messe(self, was, alter, warten, luecke, quittung, maschine, antwort):
        """Woran haengt die Zeit?
        unterwegs = Absenden auf dem Handy bis hier (Telegram, Netz, Uhr),
        blind     = wie lange vorher keine Abfrage bei Telegram offen war,
        Schlange  = Wartezeit hinter einem vorherigen Befehl,
        Maschine  = Senden und Abwarten der Fahrt."""
        self.messungen.append(
            f"{time.strftime('%H:%M:%S')} {was}: "
            + (T("unterwegs {s:.1f}s, ").format(s=alter) if alter is not None else "")
            + T("blind {b:.1f}s, Schlange {w:.1f}s, ").format(b=luecke, w=warten)
            + (T("Quittung {s:.1f}s, ").format(s=quittung) if quittung else "")
            + T("Maschine {s:.1f}s").format(s=maschine)
            + (T(", Antwort {s:.1f}s").format(s=antwort) if antwort else ""))
        del self.messungen[:-12]

    def _erlaubt(self, chat, text):
        if self.chat is None:
            # Erster, der sich mit /start meldet, bekommt die Steuerung.
            if text.startswith("/start"):
                self.chat = chat
                d = lade(); d["chat"] = chat; sichere(d)
                self._log(T("Telegram: verknuepft mit Chat {chat}").format(chat=chat))
                self.raus.put(T("Verknuepft. ") + hilfe())
                self._pad_neu()
            return False
        if chat != self.chat:
            return False
        return True

    def _befehl(self, text):
        t = text.split()
        c = t[0].lower().lstrip("/").split("@")[0]
        arg = t[1] if len(t) > 1 else None
        if c in ("start", "hilfe", "help"):
            self.raus.put(hilfe()); self._pad_neu(); return
        if c == "pad":
            self._pad_neu(); return
        if c == "schritt":
            try:
                self.schritt = max(0.01, min(MAX_SCHRITT, float(arg.replace(",", "."))))
                d = lade(); d["schritt"] = self.schritt; sichere(d)
                self.raus.put(T("Schrittweite {mm:g} mm").format(mm=self.schritt))
            except (TypeError, ValueError):
                self.raus.put(T("So: /schritt 1"))
            return
        if c in ("x", "y", "z"):
            try:
                mm = float((arg or "").replace(",", "."))
            except ValueError:
                self.raus.put(T("So: /{c} 5").format(c=c)); return
            self.raus.put(self._fahren(c, mm)); return
        if c == "zeiten":
            self.raus.put(T("Letzte Laufzeiten:\n") + ("\n".join(self.messungen)
                          or T("noch nichts gemessen")))
            return
        bekannt = {"pos": "pos", "kreuz": "kreuz", "null": "null", "heim": "heim",
                   "aus": "aus", "stopp": "stopp", "stop": "stopp", "status": "status"}
        if c in bekannt:
            self.raus.put(self._tun(bekannt[c])); return
        self.raus.put(T("Kenne ich nicht. /hilfe"))

    def _etikett(self, data):
        """Was der Knopf vorhat - schon vor dem Ausfuehren bekannt."""
        if len(data) == 2 and data[0] in "xyz" and data[1] in "+-":
            mm = self.schritt if data[1] == "+" else -self.schritt
            return f"{data[0].upper()} {mm:+g} mm"
        return {"kreuz": T("Kreuz"), "pos": T("Position"), "null": T("Nullpunkt"),
                "heim": T("zum Nullpunkt"), "aus": T("Laser aus"),
                "stopp": T("STOPP"), "schritt": T("Schrittweite")}.get(data, data)

    def _knopf(self, data):
        if data == "schritt":
            i = (SCHRITTE.index(self.schritt) + 1) % len(SCHRITTE) \
                if self.schritt in SCHRITTE else 2
            self.schritt = SCHRITTE[i]
            d = lade(); d["schritt"] = self.schritt; sichere(d)
            return T("Schritt {mm:g} mm").format(mm=self.schritt)
        if len(data) == 2 and data[0] in "xyz" and data[1] in "+-":
            return self._fahren(data[0], self.schritt if data[1] == "+" else -self.schritt)
        return self._tun(data)

    # ---------------------------------------------------------- Maschine
    def _ruf(self, aktion, wert=None, timeout=25):
        """Im Hauptthread ausfuehren - dort liegen tkinter und die Variablen."""
        antwort = queue.Queue(1)
        self.app.q.put(("fern", (aktion, wert, antwort)))
        try:
            return antwort.get(timeout=timeout)
        except queue.Empty:
            return T("Keine Antwort vom Programm.")

    def _log(self, t):
        self.app.q.put(("msg", t))

    def _fahren(self, achse, mm):
        if abs(mm) > MAX_SCHRITT:
            return T("Mehr als {mm:g} mm am Stueck gibt es hier nicht."
                     ).format(mm=MAX_SCHRITT)
        antwort = self._ruf("jog", (achse, mm))
        if antwort:
            return antwort
        return self._nach_fahrt(
            T("{achse} {mm:+g} mm").format(achse=achse.upper(), mm=mm))

    def _tun(self, aktion):
        antwort = self._ruf(aktion)
        g = self.app.grbl
        if aktion in ("kreuz", "heim") and g.connected and not g.job_running:
            return self._nach_fahrt(antwort)
        return antwort

    def _nach_fahrt(self, was, grenze=15.0):
        """Erst das Anfahren abwarten, dann den Stillstand - sonst meldet der
        Bot die alte Position, weil die Fahrt noch gar nicht begonnen hat."""
        t0 = time.time()
        # Der Zustandsbericht kommt alle 250 ms; laenger als eine Berichtslaenge
        # auf das Losfahren zu warten lohnt nicht - kurze Spruenge sind da
        # ohnehin schon vorbei.
        while time.time() - t0 < 0.45:           # Losfahren abwarten
            if not self.app.grbl.status["state"].startswith("Idle"):
                break
            time.sleep(0.03)
        while time.time() - t0 < grenze:         # und wieder zum Stehen kommen
            if self.app.grbl.status["state"].startswith(("Idle", "Alarm")):
                break
            time.sleep(0.05)
        time.sleep(0.15)                         # letzter Statusbericht
        return f"{was}\n{self.position()}"

    def position(self):
        st = self.app.grbl.status
        x, y, z = (list(st["wpos"]) + [0, 0, 0])[:3]
        if self.app.cfg.get("z_invert"):
            z = -z
        return T("X {x:.2f}   Y {y:.2f}   Z {z:.2f}   [{zustand}]").format(
            x=x, y=y, z=z, zustand=st["state"])

    # ---------------------------------------------------------- Steuerkreuz
    def _tastatur(self):
        k = lambda t, d: {"text": t, "callback_data": d}
        return {"inline_keyboard": [
            [k("Z +", "z+"), k("Y +", "y+"), k(T("Position"), "pos")],
            [k("X -", "x-"), k(T("Kreuz"), "kreuz"), k("X +", "x+")],
            [k("Z -", "z-"), k("Y -", "y-"),
             k(T("Schritt {mm:g} mm").format(mm=self.schritt), "schritt")],
            [k(T("Nullpunkt = hier"), "null"), k(T("zum Nullpunkt"), "heim")],
            [k(T("Laser aus"), "aus"), k(T("STOPP"), "stopp")],
        ]}

    def _pad_neu(self):
        try:
            r = self._api("sendMessage", frist=20, chat_id=self.chat,
                          text=self.position(), reply_markup=self._tastatur())
            self.pad_id = r["result"]["message_id"]
        except Exception as e:
            self._log(T('Telegram: {0}').format(e))

    def _pad_auffrischen(self, letzte):
        if not self.pad_id:
            return
        text = f"{self.position()}\n\n{letzte}"[:3500]
        try:
            self._api("editMessageText", frist=20, chat_id=self.chat,
                      message_id=self.pad_id, text=text,
                      reply_markup=self._tastatur())
        except Exception as e:
            # "message is not modified" meldet Telegram mit 400 - kein Fehler.
            if "not modified" not in str(e):
                self._log(T('Telegram: {0}').format(e))
