"""
Zweisprachigkeit: deutsche Oberflaeche, englische Uebersetzung.

Der deutsche Text ist der Schluessel. Fehlt eine Uebersetzung, erscheint
einfach das Deutsche - nichts bricht, und der Quelltext bleibt lesbar.

    from lw_text import T
    ttk.Label(f, text=T("Breite"))
    self._log(T("Verfahrweg {x:.0f} x {y:.0f} mm").format(x=x, y=y))

Bei Texten mit Platzhaltern wird erst uebersetzt, dann eingesetzt - deshalb
.format() statt f-Zeichenkette. Die Platzhalter heissen in beiden Sprachen
gleich, ihre Reihenfolge darf sich aber unterscheiden.

Comments and identifiers in this project are German. The user interface is
not: set "sprache": "en" in ~/.config/laserwerk/config.json, or pick the
language in the Machine tab.
"""

SPRACHE = "de"

SPRACHEN = {"de": "Deutsch", "en": "English"}


def setze(sprache):
    global SPRACHE
    SPRACHE = sprache if sprache in SPRACHEN else "de"
    return SPRACHE


def T(text):
    if SPRACHE == "de":
        return text
    return EN.get(text, text)


def fehlende(texte):
    """Welche der uebergebenen Texte haben keine Uebersetzung? (fuer Tests)"""
    return [t for t in texte if t not in EN]


# ---------------------------------------------------------------- Englisch
EN = {
    # ---- Fenster, Reiter, Jobleiste
    "Arbeitsbereich ({x:.0f} x {y:.0f} mm, Nullpunkt unten links)":
        "Work area ({x:.0f} x {y:.0f} mm, origin at bottom left)",
    "Ansicht zurücksetzen (Doppelklick)": "Reset view (double-click)",
    "Motiv": "Artwork",
    "Material": "Material",
    "Maschine": "Machine",
    "Tests": "Tests",
    "Rahmen fahren": "Trace frame",
    "Start": "Start",
    "Pause": "Pause",
    "Weiter": "Resume",
    "STOPP": "STOP",
    "Rahmen sichtbar": "Visible frame",
    "kein Job": "no job",
    "nicht verbunden": "not connected",
    "getrennt": "disconnected",
    "Hell": "Light",
    "Dunkel": "Dark",

    # ---- Reiter Motiv
    "Datei öffnen …": "Open file …",
    "Motiv entfernen": "Remove artwork",
    "Bild oder SVG": "Image or SVG",
    "Bilder, SVG, DXF": "Images, SVG, DXF",
    "alle": "all",
    "Breite": "Width",
    "Höhe": "Height",
    "Seitenverhältnis halten": "Keep aspect ratio",
    "Werkstück (Nullpunkt = linke untere Ecke)":
        "Workpiece (origin = bottom left corner)",
    "Länge X": "Length X",
    "Breite Y": "Width Y",
    "anzeigen": "show",
    "einrasten": "snap",
    "Motiv mittig setzen": "Centre the artwork",
    "Motiv mit der Maus schieben, an den Ecken ziehen zum Skalieren.":
        "Drag the artwork with the mouse, drag a corner to resize.",
    "Größe, Anlauf und Versatz": "Size, overscan and offset",
    "max.": "max.",
    "Einpassen": "Fit",
    "Originalgröße 1:1 (SVG/DXF)": "Original size 1:1 (SVG/DXF)",
    "Anlauf": "Overscan",
    "Versatz X": "Offset X",
    "Versatz Y": "Offset Y",
    "Der Anlauf macht die Zeilenränder gleichmäßig,\n"
    "der Versatz hält ihn rechts vom Nullpunkt.":
        "Overscan evens out the row ends, the offset\nkeeps it right of the origin.",
    "Rückseite (zweiseitig gravieren)": "Reverse side (two-sided engraving)",
    "Vorderseite": "Front side",
    "Rückseite, Wenden links/rechts": "Reverse, flipped left/right",
    "Rückseite, Wenden oben/unten": "Reverse, flipped top/bottom",
    "Wendeachse bei": "Flip axis at",
    "Mittellinie der Aufspannung, nicht des Motivs.":
        "Centre line of the fixture, not of the artwork.",
    "Drehen": "Rotate",
    "Invertieren (Hell und Dunkel tauschen)": "Invert (swap light and dark)",
    "Graustufen (Leistung variiert)": "Greyscale (power varies)",
    "Schwarzweiß (Strichgrafik)": "Black and white (line art)",
    "Schwelle": "Threshold",
    "Bearbeitung": "Operation",
    "Gravieren (Flächen, zeilenweise)": "Engrave (areas, row by row)",
    "Schneiden (Konturen, SVG/DXF)": "Cut (contours, SVG/DXF)",
    "Durchgänge": "Passes",
    "Vorschau + G-Code erzeugen": "Build preview + G-code",
    "G-Code speichern": "Save G-code",
    "G-Code laden": "Load G-code",

    # ---- Reiter Material
    "Preset": "Preset",
    "Laden": "Load",
    "Speichern": "Save",
    "Löschen": "Delete",
    "Materialdicke": "Material thickness",
    "Fokuskorrektur": "Focus correction",
    "Leistung S": "Power S",
    "Vorschub F": "Feed F",
    "Zeilenabstand": "Row pitch",
    "Notiz": "Note",
    "Name": "Name",
    "Werte übernehmen und Z anfahren": "Apply values and move Z",
    "Z fährt auf Materialdicke + Korrektur.": "Z moves to thickness + correction.",

    # ---- Reiter Maschine
    "neu suchen": "rescan",
    "Verbinden": "Connect",
    "Trennen": "Disconnect",
    "Verfahren": "Jogging",
    "Z hoch": "Z up",
    "Z runter": "Z down",
    "Z-Richtung umkehren": "Reverse Z direction",
    "Verfahrweg der Maschine": "Machine travel",
    "übernehmen": "apply",
    "aus der Maschine ($130/$131)": "from the machine ($130/$131)",
    "Bestimmt die gezeichnete Arbeitsfläche und die\n"
    "Warnung, wenn ein Job nicht hineinpasst.":
        "Sets the drawn work area and the warning\nwhen a job does not fit.",
    "Nullpunkt XY = hier": "Set XY origin here",
    "Fokus sitzt auf Material": "Focus sits on material",
    "Z-Referenz": "Z reference",
    "Zum Nullpunkt fahren": "Move to origin",
    "Entsperren ($X)": "Unlock ($X)",
    "Laser aus (M5)": "Laser off (M5)",
    "Position zeigen": "Show position",
    "Kreuz +/- mm": "Cross +/- mm",
    "Kreuz fahren": "Trace cross",
    "Kurzes Kreuz mit schwacher Leistung, danach\n"
    "exakt zurück. Gilt auch für 'Rahmen sichtbar'.":
        "A short cross at low power, then exactly back.\n"
        "Also applies to 'Visible frame'.",
    "Befehl:": "Command:",
    "senden": "send",
    "Sprache": "Language",
    "Gilt nach einem Neustart des Programms.": "Takes effect after a restart.",

    # ---- Reiter Tests
    "Fokustest über Z": "Focus test along Z",
    "Spanne": "Span",
    "Schritt": "Step",
    "Mitte = Materialdicke + Korrektur\n(Reiter Material). Striche von links\n"
    "nach rechts = Z aufsteigend.":
        "Centre = thickness + correction (Material\ntab). Lines from left to right\n"
        "mean increasing Z.",
    "Fokustest starten": "Run focus test",
    "Gewählten Strich ins Material übernehmen": "Take selected line into Material",
    "Materialtest": "Material test",
    "Leistungen": "Power values",
    "Vorschübe": "Feed rates",
    "Materialtest starten": "Run material test",
    "Spalten = Leistung, Zeilen = Vorschub,\nunten links beginnend. Felder 6 mm.":
        "Columns = power, rows = feed, starting at\nthe bottom left. Patches of 6 mm.",

    # ---- Meldungen, Dialoge und Zahlenformate
    'Kein Motiv':
        'No artwork',
    'Kein Port':
        'No port',
    'Zu groß':
        'Too large',
    'Rückseite':
        'Reverse side',
    'Z anfahren':
        'Move Z',
    'Keine Z-Referenz':
        'No Z reference',
    'Laden fehlgeschlagen':
        'Could not load',
    'Originalgröße':
        'Original size',
    'Speichern als':
        'Save as',
    'Fernsteuerung über Telegram':
        'Remote control via Telegram',
    'Chat lösen':
        'Unlink chat',
    'Bot starten':
        'Start bot',
    'Bot anhalten':
        'Stop bot',
    'beim Programmstart mitstarten':
        'start with the program',
    'Übernehmen + Z-Höhe anfahren':
        'Apply and move Z',
    'Erst ein Bild oder SVG öffnen.':
        'Open an image or SVG first.',
    'Zahlenfeld ungültig.':
        'Invalid number field.',
    'Erst G-Code erzeugen oder laden.':
        'Build or load G-code first.',
    'Keine Fahrbewegungen in der Datei gefunden.':
        'No movements found in the file.',
    'Keine Konturen - bitte ein SVG oder DXF öffnen.':
        'No contours - please open an SVG or DXF.',
    'keine Konturen in der DXF gefunden':
        'no contours found in the DXF',
    'SVG-Konturen nicht lesbar: {0}':
        'SVG contours not readable: {0}',
    'Nur bei SVG und DXF möglich - Pixelbilder haben keine\nverlässliche Größe in Millimetern.':
        'Only for SVG and DXF - pixel images carry no\nreliable size in millimetres.',
    'Originalgröße 1:1: {0:.3f} x {1:.3f} mm':
        'Original size 1:1: {0:.3f} x {1:.3f} mm',
    "DXF-Dateien enthalten nur Konturen.\nZum Nachzeichnen 'Schneiden' mit wenig Leistung nehmen.":
        "DXF files hold contours only.\nTo trace them use 'Cut' at low power.",
    'Schneiden geht nur mit SVG- oder DXF-Dateien,\nweil dafür Konturen nötig sind.':
        'Cutting needs an SVG or DXF file,\nbecause it works from contours.',
    'Schnittmodus: passendes Material-Preset wählen (z.B. Papier S500/F600)':
        'Cutting mode: pick a matching preset (e.g. paper S500/F600)',
    'Einstellung geändert -\nVorschau neu erzeugen.':
        'Setting changed -\nbuild the preview again.',
    '{0}\n{1} x {2} px':
        '{0}\n{1} x {2} px',
    '{0:.1f} x {1:.1f} mm':
        '{0:.1f} x {1:.1f} mm',
    '{0:g} mm':
        '{0:g} mm',
    'mm':
        'mm',
    'mm/min':
        'mm/min',
    'von 1000':
        'of 1000',
    'x  Y':
        'x  Y',
    'X+':
        'X+',
    'X-':
        'X-',
    'Y+':
        'Y+',
    'Y-':
        'Y-',
    'Motiv {b:.1f} x {h:.1f} mm\nX {x0:.1f} .. {x1:.1f} mm (mit Overscan)\n{n} Befehle, Brennweg {m:.1f} m\nLaufzeit ca. {min:.0f} min\nS{s}/F{f} = S/F {sf:.2f}{warn}':
        'Artwork {b:.1f} x {h:.1f} mm\nX {x0:.1f} .. {x1:.1f} mm (with overscan)\n{n} commands, {m:.1f} m burnt\nabout {min:.0f} min\nS{s}/F{f} = S/F {sf:.2f}{warn}',
    'Schnitt {b:.1f} x {h:.1f} mm\n{k} Konturen, innen vor außen\nSchnittlänge {m:.2f} m x {p} Durchgang/-gänge\nLaufzeit ca. {min:.0f} min\nS{s}/F{f} = S/F {sf:.2f}{warn}':
        'Cut {b:.1f} x {h:.1f} mm\n{k} contours, inner before outer\n{m:.2f} m of cut x {p} pass(es)\nabout {min:.0f} min\nS{s}/F{f} = S/F {sf:.2f}{warn}',
    '{datei}\nX {x0:.1f} .. {x1:.1f}   Y {y0:.1f} .. {y1:.1f} mm\n{n} Befehle, Brennweg {m:.1f} m\nLaufzeit ca. {min:.0f} min':
        '{datei}\nX {x0:.1f} .. {x1:.1f}   Y {y0:.1f} .. {y1:.1f} mm\n{n} commands, {m:.1f} m burnt\nabout {min:.0f} min',
    '\nACHTUNG: größer als der Verfahrweg!':
        '\nWARNING: larger than the machine travel!',
    'RÜCKSEITE gespiegelt\n':
        'REVERSE SIDE, mirrored\n',
    'RÜCKSEITE gespiegelt an {achse} = {mm:.1f} mm\n':
        'REVERSE SIDE, mirrored about {achse} = {mm:.1f} mm\n',
    '\nHinweis: nutzt M3 - bei Pause brennt der\nLaser weiter!':
        '\nNote: uses M3 - on pause the beam\nkeeps burning!',
    '\nHinweis: negative Koordinaten - Nullpunkt\nliegt nicht links unten!':
        '\nNote: negative coordinates - the origin\nis not at the bottom left!',
    'Gespiegelt landet das Motiv bei X {x:.1f} / Y {y:.1f} mm,\nalso links bzw. unter dem Nullpunkt.\n\nWendeachse groesser waehlen oder Nullpunkt weiter links setzen.':
        'Mirrored, the artwork lands at X {x:.1f} / Y {y:.1f} mm,\nleft of or below the origin.\n\nChoose a larger flip axis or set the origin further left.',
    'Gespiegelt beginnt der Schnitt bei X {x:.1f} / Y {y:.1f} mm.\nWendeachse groesser waehlen.':
        'Mirrored, the cut starts at X {x:.1f} / Y {y:.1f} mm.\nChoose a larger flip axis.',
    'Hinweis: Anlauf {a:g} mm > Versatz {x:g} mm - der Kopf faehrt bis X {bis:.1f}, also links am Nullpunkt vorbei.':
        'Note: overscan {a:g} mm > offset {x:g} mm - the head runs to X {bis:.1f}, past the origin on the left.',
    'S/F = {0:.2f}   (Holz bewährt: 0,83)':
        'S/F = {0:.2f}   (proven on wood: 0.83)',
    "Preset '{0}' gespeichert":
        "Preset '{0}' saved",
    "'{0}' löschen?":
        "Delete '{0}'?",
    'Werte übernommen. Z fährt erst,\nwenn die Maschine verbunden ist.':
        'Values applied. Z only moves once\nthe machine is connected.',
    "Z-Höhe kann nicht angefahren werden.\n\nUnter 'Maschine': Fokus auf ein Material bekannter Dicke\neinstellen und 'Z-Referenz' setzen.":
        "Cannot move Z yet.\n\nUnder 'Machine': focus on material of known\nthickness and set the Z reference.",
    'Z auf {z:.2f} mm fahren?\n(Kopf muss frei über dem Material stehen)':
        'Move Z to {z:.2f} mm?\n(the head must stand clear above the material)',
    "Z fährt auf Materialdicke + Korrektur.\nDafuer muss unter 'Maschine' eine\nZ-Referenz gesetzt sein.":
        "Z moves to thickness + correction.\nThis needs a Z reference set\nunder 'Machine'.",
    'Z -> {z:.2f}':
        'Z -> {z:.2f}',
    'Z-Referenz: aktuelle Höhe = Fokus für {0:.2f} mm':
        'Z reference: this height = focus for {0:.2f} mm',
    'Kein serielles Gerät gefunden.':
        'No serial device found.',
    'verbunden: {0}':
        'connected: {0}',
    'lese Maschineneinstellungen ($$)':
        'reading machine settings ($$)',
    'Verfahrweg laut Maschine: {0:.0f} x {1:.0f} mm':
        'Machine travel per controller: {0:.0f} x {1:.0f} mm',
    'Verfahrweg {0:.0f} x {1:.0f} mm':
        'Machine travel {0:.0f} x {1:.0f} mm',
    'Werte zwischen 10 und 2000 mm.':
        'Values between 10 and 2000 mm.',
    'Noch keine $$-Antwort. Erst verbinden - die Werte werden\ndann automatisch gelesen.':
        'No $$ answer yet. Connect first - the values are\nread automatically then.',
    'Arbeitsbereich ({x:.0f} x {y:.0f} mm, Nullpunkt unten links)':
        'Work area ({x:.0f} x {y:.0f} mm, origin at bottom left)',
    '$30 = {ist:.0f} statt {soll}: Die Werte hier sind auf 0..{soll} bezogen und werden beim Senden umgerechnet (S{a:.0f} wird S{b:.0f}).':
        '$30 = {ist:.0f} instead of {soll}: values here refer to 0..{soll} and are converted when sent (S{a:.0f} becomes S{b:.0f}).',
    "$32 = 0: Der Lasermodus ist AUS. Der Strahl brennt dann auch im Stillstand weiter - mit '$32=1' einschalten.":
        "$32 = 0: laser mode is OFF. The beam then keeps burning while standing still - switch it on with '$32=1'.",
    '$20 = 1: Softlimits sind an. Ohne Referenzfahrt ($H) weist der Controller Fahrten ab.':
        '$20 = 1: soft limits are on. Without homing ($H) the controller refuses to move.',
    'Verfahrweg laut $130/$131 ist {x:.0f} x {y:.0f} mm, eingestellt sind {cx:.0f} x {cy:.0f} mm (Reiter Maschine).':
        '$130/$131 report {x:.0f} x {y:.0f} mm of travel, {cx:.0f} x {cy:.0f} mm are set (Machine tab).',
    'X -  Y -  Z -':
        'X -  Y -  Z -',
    'X{0:8.2f}  Y{1:8.2f}  Z{2:7.2f}':
        'X{0:8.2f}  Y{1:8.2f}  Z{2:7.2f}',
    '{port}  |  {zustand}  |  Vorschub {v:.0f}  Leistung {s:.0f}':
        '{port}  |  {zustand}  |  feed {v:.0f}  power {s:.0f}',
    'Nullpunkt: {null}   Z-Ref: {zref}':
        'Origin: {null}   Z ref: {zref}',
    'gesetzt':
        'set',
    'NICHT gesetzt':
        'NOT set',
    'gültig':
        'valid',
    'fehlt':
        'missing',
    'Nullpunkt XY gesetzt':
        'XY origin set',
    'In dieser Sitzung wurde noch kein Nullpunkt gesetzt.\nTrotzdem fortfahren?':
        'No origin has been set in this session.\nCarry on anyway?',
    'Es läuft gerade ein Job.':
        'A job is running.',
    'Während eines Jobs nicht möglich.':
        'Not possible while a job runs.',
    'Jog: {0}':
        'Jog: {0}',
    '{0} -> {1}':
        '{0} -> {1}',
    'Kreuz {mm:.1f} mm bei S{s}/F{f} (S/F {sf:.2f})':
        'Cross {mm:.1f} mm at S{s}/F{f} (S/F {sf:.2f})',
    'Kreuz {mm:.1f} mm bei S{s}':
        'Cross {mm:.1f} mm at S{s}',
    'Kreuz S{0} (Telegram)':
        'Cross S{0} (Telegram)',
    'S{s} bei F{f} ist S/F {sf:.2f}.\nUeber 0,20 brennt es sichtbar ein - bitte weniger.':
        'S{s} at F{f} is S/F {sf:.2f}.\nAbove 0.20 it burns visibly - please use less.',
    'S{s} bei F{f} ist S/F {sf:.2f} - ueber 0,20 brennt es ein. Am Rechner kleiner stellen.':
        'S{s} at F{f} is S/F {sf:.2f} - above 0.20 it burns in. Lower it at the computer.',
    'Rahmen X {x0:.1f}..{x1:.1f}  Y {y0:.1f}..{y1:.1f} ({b:.1f} x {h:.1f} mm)':
        'Frame X {x0:.1f}..{x1:.1f}  Y {y0:.1f}..{y1:.1f} ({b:.1f} x {h:.1f} mm)',
    'Rahmenfahrt (Laser schwach, S{s})':
        'Frame run (laser low, S{s})',
    'Rahmenfahrt (Laser aus)':
        'Frame run (laser off)',
    'Gravur':
        'Engraving',
    'Spanne {b:.0f} x {h:.0f} mm passt nicht in den Verfahrweg.':
        'A span of {b:.0f} x {h:.0f} mm does not fit the machine travel.',
    '{name} starten?\nBereich X {x0:.1f}..{x1:.1f}, Y {y0:.1f}..{y1:.1f} mm{zeit}\n\nSchutzbrille auf? Absaugung an? Daneben bleiben.':
        'Start {name}?\nArea X {x0:.1f}..{x1:.1f}, Y {y0:.1f}..{y1:.1f} mm{zeit}\n\nGoggles on? Extraction running? Stay with it.',
    '\n\nSCHNEIDEN: Brandgefahr - Material kann weiterglimmen!':
        '\n\nCUTTING: fire risk - the material can keep smouldering!',
    '\nLaufzeit ca. {min:.0f} min':
        '\nabout {min:.0f} min',
    '{0} gestartet':
        '{0} started',
    '{p} %   noch ~{min:.0f} min':
        '{p} %   ~{min:.0f} min left',
    '   {n} Fehler':
        '   {n} errors',
    'fertig':
        'finished',
    'abgebrochen (Laser aus)':
        'cancelled (laser off)',
    'ALARM - gestoppt':
        'ALARM - stopped',
    'Verbindung verloren':
        'connection lost',
    'zu viele Übertragungsfehler':
        'too many transmission errors',
    '{0}: {1}':
        '{0}: {1}',
    "Pause (Feed Hold) - Laser aus. 'Weiter' setzt fort.":
        "Pause (feed hold) - laser off. 'Resume' carries on.",
    'weiter':
        'resumed',
    'Controller neu gestartet - Nullpunkt und Z-Referenz neu setzen!':
        'Controller restarted - set origin and Z reference again!',
    'VERBINDUNG VERLOREN: {0}':
        'CONNECTION LOST: {0}',
    'Die USB-Verbindung ist abgerissen.\nIch versuche Halt + Laser aus zu senden.\n\nIm Zweifel: Laserschalter von Hand aus!':
        'The USB connection dropped.\nTrying to send halt + laser off.\n\nWhen in doubt: switch the laser off by hand!',
    'Halt + M5 an {0} gesendet. Neu verbinden, Nullpunkt neu setzen.':
        'Halt + M5 sent to {0}. Reconnect and set the origin again.',
    'Controller nicht erreichbar - LASERSCHALTER VON HAND AUS!':
        'Controller unreachable - SWITCH THE LASER OFF BY HAND!',
    'Controller nicht erreichbar.\nLaserschalter von Hand aus!':
        'Controller unreachable.\nSwitch the laser off by hand!',
    'Fehler: {e}':
        'Error: {e}',
    'Für den Z-Fokustest wird eine Z-Referenz gebraucht\n(Reiter Maschine).':
        'The Z focus test needs a Z reference\n(Machine tab).',
    'Fokustest {n} Striche':
        'Focus test, {n} lines',
    'Strich {i:>2}:  Z = {z:.2f} mm':
        'Line {i:>2}:  Z = {z:.2f} mm',
    'Fokuskorrektur = {0:+.2f} mm - im Reiter Material speichern':
        'Focus correction = {0:+.2f} mm - save it in the Material tab',
    'Werte mit Komma trennen, z.B. 200,400,600':
        'Separate values with commas, e.g. 200,400,600',
    'Materialtest {a}x{b}':
        'Material test {a}x{b}',
    'Laser aus (Telegram)':
        'Laser off (Telegram)',
    'STOPP (Telegram)':
        'STOP (Telegram)',
    'Entsperrt (Telegram)':
        'Unlocked (Telegram)',
    'Nullpunkt XY gesetzt (Telegram)':
        'XY origin set (Telegram)',
    'fahre zum Nullpunkt (Telegram)':
        'moving to the origin (Telegram)',
    'fahre zum Nullpunkt':
        'moving to the origin',
    'M5 gesendet - Laser aus.':
        'M5 sent - laser off.',
    'STOPP: Halt und Soft-Reset. Nullpunkt danach neu setzen.':
        'STOP: halt and soft reset. Set the origin again afterwards.',
    'Nicht verbunden.':
        'Not connected.',
    'Es laeuft ein Job - frei sind nur /status, /aus und /stopp.':
        'A job is running - only /status, /aus and /stopp are allowed.',
    '\nErst entsperren: /frei':
        '\nUnlock first: /frei',
    'Nullpunkt XY = hier.':
        'XY origin is here.',
    'Unbekannter Auftrag.':
        'Unknown request.',
    'verbunden':
        'connected',
    'Job laeuft':
        'job running',
    '{zustand} ({port}), {job}\n{pos}\nNullpunkt: {null}, Z-Ref: {zref}':
        '{zustand} ({port}), {job}\n{pos}\nOrigin: {null}, Z ref: {zref}',
    'Erst den Token vom BotFather eintragen -\nhier im Feld oder in\n':
        'Enter the BotFather token first -\nhere in the field or in\n',
    'Telegram: @{name} laeuft':
        'Telegram: @{name} is running',
    ' - jetzt /start im Chat senden':
        ' - now send /start in the chat',
    'Telegram: angehalten':
        'Telegram: stopped',
    'Telegram: Verknuepfung geloest - der naechste /start uebernimmt.':
        'Telegram: chat unlinked - the next /start takes over.',
    'wartet auf /start im Chat':
        'waiting for /start in the chat',
    'laeuft, Chat {chat}':
        'running, chat {chat}',
    '{0:.1f}x   Mausrad = Zoom, mittlere/rechte Taste = schieben':
        '{0:.1f}x   wheel = zoom, middle/right button = pan',
    "Achsen und Sichtkreuz vom Handy. Gravur und\n"
    "Schnitt starten absichtlich nur hier.":
        "Axes and sight cross from your phone. Engraving\n"
        "and cutting start here on purpose.",
    "VERBINDUNG VERLOREN - im Zweifel Laserschalter von Hand aus!":
        "CONNECTION LOST - when in doubt, switch the laser off by hand!",
    # ---- Module ausserhalb der Oberflaeche
    "nicht verbunden": "not connected",
    "Job laeuft": "job running",
    "Zeile nicht verstanden: {z!r} ({e})": "line not understood: {z!r} ({e})",
    "Datei öffnen": "Open file",
    "Speichern unter": "Save as",
    # ---- Telegram
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
    "Gravur und Schnitt werden absichtlich nur am Rechner gestartet.":
        "Laserwerk remote control\n\n"
        "/pad - send the control pad\n"
        "/pos - position\n"
        "/x 5   /y -2.5   /z 0.3 - single moves (50 mm at most)\n"
        "/schritt 1 - step size for the pad\n"
        "/kreuz - trace the sight cross where it stands\n"
        "/null - set the XY origin here\n"
        "/heim - move to the origin\n"
        "/aus - laser off (M5)\n"
        "/stopp - halt and soft reset\n"
        "/status - connection, state, job\n"
        "/zeiten - where the waiting time goes\n\n"
        "Engraving and cutting start at the computer on purpose.",
    "Verknuepft. ": "Linked. ",
    "Laserwerk ist da. /pad fuer das Steuerkreuz.":
        "Laserwerk is here. /pad for the control pad.",
    "Kein Token hinterlegt.": "No token stored.",
    "Schrittweite {mm:g} mm": "Step size {mm:g} mm",
    "Schritt {mm:g} mm": "Step {mm:g} mm",
    "So: /schritt 1": "Like this: /schritt 1",
    "So: /{c} 5": "Like this: /{c} 5",
    "Kenne ich nicht. /hilfe": "Do not know that one. /hilfe",
    "Letzte Laufzeiten:\n": "Recent timings:\n",
    "noch nichts gemessen": "nothing measured yet",
    "Mehr als {mm:g} mm am Stueck gibt es hier nicht.":
        "No more than {mm:g} mm in one go here.",
    "{achse} {mm:+g} mm": "{achse} {mm:+g} mm",
    "Keine Antwort vom Programm.": "No answer from the program.",
    "Kreuz": "Cross", "Position": "Position", "Nullpunkt": "Origin",
    "zum Nullpunkt": "to the origin", "Laser aus": "Laser off",
    "Schrittweite": "Step size", "Nullpunkt = hier": "Origin = here",
    "X {x:.2f}   Y {y:.2f}   Z {z:.2f}   [{zustand}]":
        "X {x:.2f}   Y {y:.2f}   Z {z:.2f}   [{zustand}]",
    "unterwegs {s:.1f}s, ": "in transit {s:.1f}s, ",
    "blind {b:.1f}s, Schlange {w:.1f}s, ": "blind {b:.1f}s, queue {w:.1f}s, ",
    "Quittung {s:.1f}s, ": "ack {s:.1f}s, ",
    "Maschine {s:.1f}s": "machine {s:.1f}s",
    ", Antwort {s:.1f}s": ", reply {s:.1f}s",
    "Telegram: verknuepft mit Chat {chat}": "Telegram: linked to chat {chat}",
    "Telegram: Meldung nicht zugestellt ({e}): {t}":
        "Telegram: message not delivered ({e}): {t}",
    "Telegram: 409 - der Bot wird anderswo schon "
    "abgefragt (zweites Laserwerk offen?)":
        "Telegram: 409 - the bot is already being polled elsewhere "
        "(a second Laserwerk open?)",
    "Sprache: {name} - gilt nach einem Neustart.":
        "Language: {name} - takes effect after a restart.",
    "Die Sprache gilt, sobald Laserwerk neu gestartet wird.":
        "The language applies once Laserwerk is restarted.",
    # ---- kurze Titel und Zustaende
    "DXF": "DXF", "G-Code": "G-code", "Telegram": "Telegram", "Token": "Token",
    "Eingabe": "Input", "Laser": "Laser", "Rahmen": "Frame", "Schneiden": "Cut",
    "Maschineneinstellungen": "Machine settings", "Verfahrweg": "Machine travel",
    "Telegram: {0}": "Telegram: {0}",
    "aus": "off",
}
