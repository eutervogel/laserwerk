"""
GRBL-Anbindung fuer Laserwerk.

Ein Lesethread verarbeitet alles, was vom Controller kommt:
  - Statusberichte <...>      -> self.status (inkl. WPos = MPos - WCO)
  - ok / error                 -> Quittungs-Queue fuer den Sender
  - ALARM, [MSG], Startmeldung -> Ereignisse an die Oberflaeche
Ein Abfragethread schickt alle 250 ms ein '?'. Weil Quittungen und Status
getrennt gelesen werden, gehen keine 'ok' mehr verloren.

Erkenntnisse aus dem Betrieb, die hier eingebaut sind:
  - Nach einem USB-Abriss heisst der Port anders (ttyUSB0 -> ttyUSB1).
  - Beim Verbinden resettet das Board meist (DTR) -> MPos wird 0 und
    G92-Offsets (Nullpunkt, Z-Referenz) sind weg.
  - Im Lasermodus ($32=1) ist der Ausgang nur waehrend G1-Fahrten aktiv.
"""
import glob, os, queue, re, threading, time
import serial

from lw_text import T

RX_BUF = 127

# Wie oft ein Job eine verlorene Quittung verkraftet, bevor abgebrochen
# wird. Einzelne kommen vor - bei Millionen Zeilen ist das Statistik, und
# jede kostet hoechstens ein paar Zehntelmillimeter Strich. Haeufen sie
# sich, stimmt etwas mit der Verbindung nicht, und dann ist Weitermachen
# keine gute Idee.
MAX_RESYNC = 20


def ports():
    """Serielle Ports, stabile by-id-Namen zuerst."""
    out = [os.path.realpath(p) for p in sorted(glob.glob("/dev/serial/by-id/*"))]
    for p in sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")):
        if p not in out:
            out.append(p)
    return out


class Grbl:
    def __init__(self, on_event):
        # on_event(art, daten) wird aus Threads aufgerufen - die Oberflaeche
        # muss das selbst in den Hauptthread holen.
        self.on_event = on_event
        self.s = None
        self.port = None
        self.alive = False
        self.lock = threading.Lock()
        self.cmd_lock = threading.Lock()   # ein Einzelbefehl zur Zeit (GUI + Fern)
        self.oks = queue.Queue()
        self.status = {"state": "?", "mpos": (0, 0, 0), "wco": (0, 0, 0),
                       "wpos": (0, 0, 0), "fs": (0, 0)}
        self.alarm = None
        self.settings = {}           # $$-Werte, z.B. {"30": 1000.0}
        self.job_running = False
        self._stop = False
        self._pause_ende = False     # Pause am naechsten Zeilenende gewuenscht
        self.pausiert = False        # haelt gerade an einem Zeilenende
        self.job_errors = 0          # Uebertragungsfehler im letzten Job
        self.job_done = 0            # quittierte Befehle im letzten Job
        self.reset_seen = 0          # zaehlt Neustarts des Controllers
        self.job_resyncs = 0         # verlorene Quittungen, neu aufgesetzt

    # ---------- Verbindung ----------
    def connect(self, port, baud=115200):
        self.s = serial.Serial(port, baud, timeout=0.1)
        self.port = port
        time.sleep(2.0)              # Board startet ggf. neu (DTR)
        self.s.reset_input_buffer()
        self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._poller, daemon=True).start()
        self.write(b"\r\n")
        time.sleep(0.3)

    def disconnect(self):
        self.alive = False
        try:
            if self.s:
                self.s.close()
        except Exception:
            pass
        self.s = None

    @property
    def connected(self):
        return self.alive and self.s is not None

    def write(self, data):
        if not self.connected:
            raise RuntimeError(T("nicht verbunden"))
        with self.lock:
            self.s.write(data)

    # ---------- Threads ----------
    def _reader(self):
        buf = b""
        while self.alive:
            try:
                # read(256) wuerde bis zum Timeout auf 256 Bytes warten und die
                # Quittungen buendeln - das bremst den Sender auf ~50 Befehle/s.
                # Deshalb: auf das erste Byte warten, dann alles Vorhandene holen.
                chunk = self.s.read(1)
                if chunk and self.s.in_waiting:
                    chunk += self.s.read(self.s.in_waiting)
            except (serial.SerialException, OSError, TypeError) as e:
                self._lost(e)
                return
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                t = line.decode(errors="replace").strip()
                if t:
                    try:
                        self._handle(t)
                    except Exception as e:
                        # Eine unerwartete Zeile darf nie den Lesethread beenden
                        self.on_event("msg", T("Zeile nicht verstanden: {z!r} ({e})"
                                               ).format(z=t, e=e))

    def _poller(self):
        while self.alive:
            try:
                self.write(b"?")
            except Exception:
                pass
            time.sleep(0.25)

    def _handle(self, t):
        if t.startswith("<"):
            self._parse_status(t)
        elif t == "ok" or t.startswith("error"):
            self.oks.put(t)
        elif t.startswith("ALARM"):
            self.alarm = t
            self.on_event("alarm", t)
        elif t.startswith("$") and "=" in t:
            # Antwort auf '$$': '$30=1000.000'
            k, _, v = t[1:].partition("=")
            try:
                self.settings[k.strip()] = float(v.split()[0])
            except ValueError:
                pass
        elif t.startswith("Grbl"):
            # Controller hat neu gestartet: Nullpunkt und Z-Referenz ungueltig
            self.reset_seen += 1
            self.status["wco"] = (0, 0, 0)
            self.on_event("reset", t)
        else:
            self.on_event("msg", t)

    def _parse_status(self, t):
        body = t.strip("<>").split("|")
        st = self.status
        st["state"] = body[0]
        for f in body[1:]:
            k, _, v = f.partition(":")
            # Nicht jedes Feld ist numerisch: A:SFM (Zubehoer, z.B. A:C bei
            # laufendem Laser), Pn:XYZP (Pins). Diese einfach auslassen -
            # ein Absturz hier legt den Lesethread lahm und damit den Job.
            try:
                nums = tuple(float(x) for x in v.split(",")) if v else ()
            except ValueError:
                continue
            if k == "MPos":
                st["mpos"] = nums
            elif k == "WCO":
                st["wco"] = nums          # kommt nur gelegentlich -> merken
            elif k == "WPos":
                st["wpos"] = nums
            elif k == "FS":
                st["fs"] = nums
            elif k == "Bf":
                # Planerbloecke und freier Empfangspuffer. Daran erkennt
                # man, ob die Maschine wirklich alles abgearbeitet hat.
                st["bf"] = nums
        if "MPos" in t:
            m, w = st["mpos"], st["wco"]
            st["wpos"] = tuple(a - b for a, b in zip(m, w))
        self.on_event("status", dict(st))

    def _lost(self, e):
        """USB-Abriss. Nach Wiederanmeldung Halt und Laser aus hinterherschicken."""
        self.alive = False
        self.on_event("lost", str(e))
        for _ in range(20):
            time.sleep(1)
            for p in ports():
                try:
                    s2 = serial.Serial(p, 115200, timeout=0.3)
                    time.sleep(0.5)
                    s2.write(b"!"); time.sleep(1.0)
                    s2.write(b"M5\n"); time.sleep(0.3)
                    s2.close()
                    self.on_event("lost_secured", p)
                    return
                except Exception:
                    continue
        self.on_event("lost_unsecured", "")

    # ---------- Einzelbefehle ----------
    def cmd(self, line, timeout=10.0):
        """Befehl senden und auf ok/error warten. Nicht waehrend eines Jobs."""
        if self.job_running:
            raise RuntimeError(T("Job laeuft"))
        with self.cmd_lock:
            while not self.oks.empty():
                self.oks.get_nowait()
            self.write((line.strip() + "\n").encode())
            try:
                return self.oks.get(timeout=timeout)
            except queue.Empty:
                return "timeout"

    def realtime(self, b):
        self.write(b)

    def wait_idle(self, timeout=120.0):
        t0 = time.time()
        time.sleep(0.4)
        while time.time() - t0 < timeout:
            if self.status["state"].startswith("Idle"):
                return True
            time.sleep(0.2)
        return False

    def read_settings(self, timeout=3.0):
        """'$$' abfragen und die Antwortzeilen einsammeln. Wichtig sind
        $30 (Hoechstwert von S) und $32 (Lasermodus) - ohne sie rechnet das
        Programm mit fremden Zahlen."""
        self.settings = {}
        try:
            self.cmd("$$", timeout=timeout)
        except Exception:
            return {}
        t0 = time.time()                    # die Zeilen laufen noch nach
        while time.time() - t0 < 1.0 and "132" not in self.settings:
            time.sleep(0.05)
        return dict(self.settings)

    def unlock(self):
        self.alarm = None
        return self.cmd("$X")

    def set_zero_xy(self):
        self.cmd("G21"); self.cmd("G90")
        return self.cmd("G92 X0 Y0")

    def set_z_reference(self, z_value):
        """Aktuelle Hoehe bekommt den Z-Wert z_value (Materialdicke)."""
        return self.cmd(f"G92 Z{z_value:.3f}")

    def jog(self, dx=0.0, dy=0.0, dz=0.0, feed=1000):
        parts = []
        if dx: parts.append(f"X{dx:.3f}")
        if dy: parts.append(f"Y{dy:.3f}")
        if dz: parts.append(f"Z{dz:.3f}")
        if not parts:
            return
        self.write(f"$J=G91 G21 {' '.join(parts)} F{feed}\n".encode())

    def jog_cancel(self):
        self.write(b"\x85")

    def goto(self, x=None, y=None, z=None, feed=None):
        p = []
        if x is not None: p.append(f"X{x:.3f}")
        if y is not None: p.append(f"Y{y:.3f}")
        if z is not None: p.append(f"Z{z:.3f}")
        self.cmd("G90")
        self.cmd(("G0 " if feed is None else f"G1 F{feed} ") + " ".join(p))

    def laser_off(self):
        try:
            self.write(b"M5\n")
        except Exception:
            pass

    # ---------- Job ----------
    def run_job(self, lines, on_progress, max_errors=50, marken=None):
        """G-Code streamen (Character Counting). Laeuft im eigenen Thread.
        Rueckgabe: 'fertig', 'abgebrochen', 'alarm', 'verbindung', 'fehler'.

        marken: Zeilennummern, an denen eine neue Gravurzeile oder Kontur
        anfaengt. Nur damit ist eine Pause am Zeilenende moeglich.
        """
        self.job_running = True
        self._stop = False
        self._pause_ende = False
        self.pausiert = False
        self._still_seit = None
        self.job_resyncs = 0
        self.job_errors = self.job_done = 0
        self.alarm = None
        while not self.oks.empty():
            self.oks.get_nowait()
        pend, sent, done, errors = [], 0, 0, 0
        grenze = None                 # bis hierhin senden, dann anhalten
        total = len(lines)
        t0 = time.time()
        try:
            while done < total:
                if not self.alive:
                    return "verbindung"
                if self._stop:
                    return "abgebrochen"
                if self.alarm:
                    self._halt()
                    return "alarm"
                if self._pause_ende and grenze is None:
                    grenze = self._naechste_marke(marken, sent)
                if grenze is not None and done >= grenze:
                    if not self._zeilenpause(lines, sent):
                        return "abgebrochen" if self._stop else "verbindung"
                    grenze = None
                    continue
                ziel = total if grenze is None else grenze
                while sent < ziel and sum(pend) + len(lines[sent]) + 1 <= RX_BUF:
                    c = lines[sent] + "\n"
                    self.write(c.encode())
                    pend.append(len(c))
                    sent += 1
                try:
                    r = self.oks.get(timeout=0.5)
                except queue.Empty:
                    # Keine Quittung. Entweder arbeitet die Maschine noch,
                    # oder eine ist unterwegs verlorengegangen - ein Byte
                    # auf der USB-Leitung reicht. Frueher wurde hier
                    # einfach weitergewartet, und zwar endlos: der Job
                    # stand, die Maschine lief leer, und Laserwerk hielt
                    # ihn weiter fuer laufend.
                    if self._strom_steht(sent, done):
                        self.job_resyncs += 1
                        on_event = self.on_event
                        on_event("msg", T(
                            "Quittung ausgeblieben - Strom neu aufgesetzt "
                            "nach Zeile {n} ({m}. Mal). Bis zu {p} Befehle "
                            "koennen fehlen.").format(
                                n=done, m=self.job_resyncs, p=len(pend)))
                        if self.job_resyncs > MAX_RESYNC:
                            self._halt()
                            return "verbindung"
                        done += len(pend)
                        self.job_done = done
                        pend = []
                    continue
                if pend:
                    pend.pop(0)
                done += 1
                self.job_done = done
                if r.startswith("error"):
                    # einzelner Uebertragungsfehler = ein fehlender 0,1-mm-Strich
                    errors += 1
                    self.job_errors = errors
                    if errors > max_errors:
                        self._halt()
                        return "fehler"
                if done % 100 == 0 or done == total:
                    on_progress(done, total, time.time() - t0, errors)
            self.wait_idle(timeout=600)
            return "fertig"
        except (serial.SerialException, OSError, RuntimeError):
            return "verbindung"
        finally:
            self.job_running = False
            self.pausiert = False
            self._pause_ende = False

    STILL_SEKUNDEN = 3.0        # so lange muss es ruhig sein

    def _strom_steht(self, sent, done):
        """Steht der Strom wirklich, oder arbeitet die Maschine noch?

        Verlassen wird sich auf zwei Dinge, die beide stimmen muessen:
        die Maschine meldet Idle, und ihr Empfangspuffer ist leer. Dann
        hat sie alles bekommene ausgefuehrt, und was wir noch als
        unterwegs fuehren, kommt nicht mehr. Waehrend sie faehrt oder im
        Hold steht, ist Warten dagegen genau richtig - deshalb zaehlt
        hier nur der Leerlauf.
        """
        if sent <= done:
            return False
        if not self.status.get("state", "").startswith("Idle"):
            self._still_seit = None
            return False
        bf = self.status.get("bf") or ()
        if len(bf) > 1 and bf[0] < 1:
            # Planer noch voll: sie faehrt noch, auch wenn der Zustand
            # gerade Idle meldet.
            self._still_seit = None
            return False
        jetzt = time.time()
        if not getattr(self, "_still_seit", None):
            self._still_seit = jetzt
            return False
        if jetzt - self._still_seit < self.STILL_SEKUNDEN:
            return False
        self._still_seit = None
        return True

    @staticmethod
    def _naechste_marke(marken, sent):
        """Wo faengt die naechste Zeile an? Ohne Marke davor: anhalten,
        sobald der Puffer leer ist - auch das haelt kontrolliert an."""
        for m in marken or ():
            if m > sent:
                return m
        return sent

    @staticmethod
    def _laser_modus(lines, bis):
        """M3 oder M4 - was zuletzt gesendet wurde. Nach dem M5 der Pause
        muss genau das wieder gelten, sonst laeuft der Rest der Gravur im
        falschen Modus weiter."""
        for i in range(min(bis, len(lines)) - 1, -1, -1):
            c = lines[i].split(";")[0]
            if "M4" in c:
                return "M4"
            if "M3" in c:
                return "M3"
        return "M4"

    def _zwischenbefehl(self, line):
        """Ein einzelner Befehl mitten im Job. Nur erlaubt, wenn nichts mehr
        unquittiert ist - sonst zaehlt die Zeichenzaehlung falsch. Die
        Quittung wird hier abgeholt, nicht vom Jobzaehler."""
        self.write((line + "\n").encode())
        try:
            self.oks.get(timeout=5.0)
        except queue.Empty:
            pass

    def _zeilenpause(self, lines, sent):
        """Anhalten, wenn alles Gesendete quittiert ist.

        Die Maschine faehrt die gepufferten Bewegungen zu Ende und bleibt am
        Zeilenende stehen - im Anlauf neben dem Motiv statt mitten im Bild,
        wo ein Feed Hold eine Delle in die Zeile bremst.

        Rueckgabe: False, wenn waehrend der Pause abgebrochen wurde.
        """
        self.wait_idle(timeout=300)
        self._zwischenbefehl("M5")        # auch bei $32=0 sicher aus
        self.pausiert = True
        self.on_event("pausiert", "")
        try:
            while self._pause_ende:
                if self._stop or not self.alive:
                    return False
                time.sleep(0.2)
            self._zwischenbefehl(self._laser_modus(lines, sent))
            self.on_event("weiter", "")
            return True
        finally:
            self.pausiert = False

    def pause(self):
        self.realtime(b"!")

    def pause_am_zeilenende(self):
        """Nicht sofort, sondern am Ende der laufenden Zeile anhalten."""
        self._pause_ende = True

    def resume(self):
        if self._pause_ende or self.pausiert:
            self._pause_ende = False      # der Job laeuft von selbst weiter
            return
        self.realtime(b"~")

    def stop(self):
        """Abbruch: anhalten, Bremsweg abwarten, Soft-Reset (Laser aus)."""
        self._stop = True
        self._halt()

    def _halt(self):
        try:
            self.realtime(b"!")
            time.sleep(1.5)          # Bremsweg bei 30 mm/s^2
            self.realtime(b"\x18")
        except Exception:
            pass
