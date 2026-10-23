# Laserwerk

*[English](README.md) · **Deutsch***

Ein Steuerprogramm für Diodenlaser an GRBL-Controllern, für Linux, auf Deutsch.
Bild oder SVG hineinwerfen, auf dem simulierten Werkstück platzieren, Achsen
fahren, Fokus suchen, gravieren oder schneiden — in einem Fenster, ohne
Abonnement und ohne Cloud.

![Motiv auf dem Werkstück platzieren](bilder/01-platzieren.png)

Entstanden, weil es auf Linux wenig dazwischen gibt: LightBurn kostet Geld,
LaserGRBL läuft nur unter Windows, und der Weg über Inkscape-Erweiterungen und
einen reinen G-Code-Sender ist umständlich, sobald man Graustufen rastern oder
Material ausprobieren will.

> **Die Oberfläche gibt es auf Deutsch und Englisch** (Reiter *Maschine* →
> *Sprache*). Kommentare und Bezeichner im Quelltext sind deutsch.

## Kann

- **Anlauf aus der Maschine** — im Lasermodus skaliert GRBL mit `M4` die
  Leistung mit der Geschwindigkeit. Ist der Anlauf kürzer als der
  Beschleunigungsweg, brennt der Zeilenanfang zu schwach. Laserwerk rechnet
  ihn aus Vorschub und `$120` aus: bei F1000 und 30 mm/s² sind das 4,6 mm,
  nicht die 1,5 mm, die man üblicherweise einstellt.
- **Gravieren** — Bilder (PNG, JPG, WEBP, BMP) und SVG als Raster, zeilenweise:
  schwarzweiß mit Schwelle, Graustufen mit veränderlicher Leistung oder
  Rasterung nach Floyd-Steinberg, bei der alle Punkte gleich stark brennen und
  der Tonwert aus der Punktdichte kommt — das Mittel für Material mit scharfer
  Schwelle. Dazu ein Tonwertregler für die Mitten und Anlauf (Overscan) an den
  Zeilenenden.
- **Schneiden** — Konturen aus SVG und DXF, innen vor außen, mehrere Durchgänge,
  Originalgröße 1:1 für Schablonen aus dem CAD.
- **Platzieren** — Werkstück mit Länge und Breite angeben, Motiv mit der Maus
  darauf schieben und an den Ecken skalieren, mit Einrasten auf Kanten, Ecken
  und Mitte. Drehen in beliebigen Winkeln, nicht nur in 90er-Schritten.
- **Maschine fahren** — Achsen tippen, Nullpunkt setzen, Z-Referenz,
  Rahmenfahrt um das Motiv, Sichtkreuz mit schwacher Leistung („wo steht er
  gerade?"), Entsperren, einzelne G-Code-Befehle.
- **Material finden** — Fokustest über Z, Materialtest als Feldraster aus
  Leistungen und Vorschüben, Graustufentest mit einem Tonwertkeil je
  Leistung, Presets mit Materialdicke, Fokuskorrektur, Leistung, Vorschub,
  Zeilenabstand und Tonwert.
- **Zweiseitig gravieren** — Spiegeln an einer Wendeachse, mit Prüfung, ob das
  gespiegelte Motiv noch im positiven Bereich liegt.
- **Fernsteuerung über Telegram** — Achsen und Sichtkreuz vom Handy, während man
  am Werkstück steht. Meldet sich, wenn ein Job fertig ist oder in Alarm geht.
- **Fortsetzen** — `fortsetzen.py` findet nach einem hängengebliebenen Job die
  genaue Stoppstelle über die Position und streamt den Rest.
- **Nullpunkt übersteht STOPP** — der Abbruch setzt den Controller zurück und
  löscht dabei dessen G92-Versatz. Laserwerk merkt ihn sich vorher und setzt
  ihn danach neu, damit „Zum Nullpunkt fahren" weiter das Werkstück meint und
  nicht den Nullpunkt der Maschine.

## So sieht das aus

Erzeugter G-Code mit Laufzeitschätzung — das Motiv liegt als Brandspur auf dem
simulierten Brettchen, der Rahmen mit den Anfassern lässt sich mit der Maus
schieben und skalieren:

![G-Code erzeugt](bilder/02-gcode.png)

Materialwerte als Preset, Achsensteuerung und die Tests:

| | |
|---|---|
| ![Material](bilder/03-material.png) | ![Maschine](bilder/04-maschine.png) |

![Tests](bilder/05-tests.png)

## Braucht

- Python 3.10 oder neuer, mit tkinter (`apt install python3-tk`)
- `pip install -r requirements.txt` — pyserial, Pillow, numpy
- optional `zenity` für native GTK-Dialoge; fehlt es, nimmt das Programm die
  Tk-eigenen
- einen GRBL-1.1-Controller am USB-Port, Benutzer in der Gruppe `dialout`

```sh
git clone https://github.com/eutervogel/laserwerk
cd laserwerk
pip install -r requirements.txt
./laserwerk.sh
```

Einstellungen, Presets und der Telegram-Token liegen unter
`~/.config/laserwerk/`, nicht im Projektordner.

## Sicherheit

Ein Diodenlaser verbrennt Material, Haut und Netzhaut, und er entzündet Späne,
Papier und Staub. Dieses Programm nimmt einem davon nichts ab.

- **Nie unbeaufsichtigt laufen lassen.** Eine Gravur läuft eine Stunde; ein
  Glimmnest braucht keine Minute.
- **Schutzbrille für die Wellenlänge des Lasers**, auch für alle, die zusehen.
  Blaues Streulicht an der Brennstelle reicht.
- **Absaugen oder ins Freie lüften.** Holzrauch ist unangenehm, manches andere
  giftig.
- **Kein PVC, kein Kunstleder, kein TPU** — dabei entsteht Chlorwasserstoff
  beziehungsweise Blausäure. Sie fressen auch die Mechanik.
- **Löschmittel in Reichweite.**
- Die Fernsteuerung fährt nur Achsen und das Sichtkreuz. Einen Job startet sie
  mit Absicht nicht: Volle Leistung gehört dorthin, wo jemand hinsieht. Auch
  Achsen bitte nur fahren, während man die Maschine im Blick hat.

## Die Materialwerte sind nicht deine

Die mitgelieferten Presets wurden auf **einer** Maschine gemessen: 450 nm,
5,5 W optisch. Anderer Laser, andere Linse, anderer Fokus, andere Werte. Sie
sind ein Startpunkt für einen eigenen Materialtest, kein Rezept. Zu viel
Leistung bei zu wenig Vorschub heißt nicht „dunkler", sondern irgendwann
„brennt".

Hat dein Material eine **scharfe Schwelle** — Buche etwa zeichnet erst ab
einer Leistung und verkohlt kurz darüber —, dann trag im Reiter *Material*
unter **Leistung ab** ein, wo es anfängt zu zeichnen. Die Tonwerte werden
dann zwischen diesem Wert und S verteilt statt zwischen 30 % und S. Ohne das
liegt die halbe Tonskala unter der Schwelle und macht gar nichts, während
die andere Hälfte einheitlich schwarz ist. Beide Werte liest du aus dem
Graustufentest ab. 0 heißt: wie bisher, 30 % von S.

Für **Graustufen** gilt das doppelt: Dort brennt jede Zeile über die ganze
Fläche, und die Nachbarzeile trifft schon vorgewärmtes Material. Gemessen
wurden auf der Referenzmaschine S175 auf Pappe und S130 auf Schichtplatte —
ein Sechstel dessen, was dasselbe Holz als Strichgrafik verträgt. Der S-Wert
ist dabei das Maximum, erreicht bei reinem Schwarz; darunter liegt ein Boden
bei 30 %, und fast weiße Stellen bleiben ganz aus. Läuft ein Motiv trotzdem
zu, hilft der Regler **Mitten** mehr als weniger Leistung: Er senkt nur die
Mitteltöne, Schwarz bleibt schwarz.

Was übertragbar ist, ist das **Verhältnis S/F**: Leistung geteilt durch
Vorschub, also die Energie je Millimeter. Auf der Referenzmaschine hat sich
Holz bei S830/F1000 = 0,83 bewährt, Wildleder bei 0,25, das Sichtkreuz läuft bei
0,08. Über etwa 0,20 brennt der Strahl sichtbar ein — deshalb weigert sich das
Programm, ein Sichtkreuz oberhalb davon zu fahren.

Alle Leistungen in der Oberfläche beziehen sich auf die Skala **0…1000**. Beim
Verbinden liest Laserwerk `$30` aus dem Controller und rechnet beim Senden um;
steht dort 255, wird aus S830 eben S212 — derselbe Anteil. Es warnt außerdem,
wenn `$32 = 0` ist, also der Lasermodus aus: dann brennt der Strahl auch im
Stillstand weiter, und jede Pause frisst ein Loch.

## Getestet mit

GRBL 1.1f auf einem CH340-Board, Diodenlaser mit 450 nm und 5,5 W optischer
Leistung, 200 × 200 mm Verfahrweg, Z-Achse mit Motor. Dort gelaufen:
Schichtplatte, Schiefer, Wildleder, Papier (geschnitten). Weißes PLA ist mit
einem blauen Laser nicht zu markieren — das Licht wird reflektiert.

Der Verfahrweg steht im Reiter *Maschine* und lässt sich aus `$130`/`$131`
übernehmen.

## Aufbau

| Datei | wofür |
|---|---|
| `laserwerk.py` | Oberfläche, Ablauf, Jobsteuerung |
| `lw_grbl.py` | serielle Anbindung, Streaming, Statusberichte |
| `lw_job.py` | Raster-G-Code, Laufzeitschätzung, Vorschaubilder, Tests |
| `lw_vector.py` | SVG- und DXF-Einleser, Konturen, Schnitt-G-Code |
| `lw_presets.py` | Materialwerte und Einstellungen |
| `lw_style.py` | helles und dunkles Farbschema |
| `lw_text.py` | deutsche und englische Texte der Oberfläche |
| `lw_dialog.py` | native Dialoge über zenity, mit Tk als Rückfall |
| `lw_telegram.py` | Fernsteuerung |
| `fortsetzen.py` | abgebrochenen Job an der Stoppstelle fortsetzen |
| `bilder/mach_bilder.py` | erzeugt die Bildschirmfotos, auf unsichtbarem Schirm |

Keine Fremdbibliotheken außer pyserial, Pillow und numpy. SVG, DXF und die
Telegram-Anbindung sind selbst geschrieben, damit nichts nachinstalliert werden
muss und nichts im Hintergrund Dialoge öffnet.

## Übersetzungen

`lw_text.py` ordnet jedem deutschen Text seine englische Entsprechung zu.
Fehlt ein Eintrag, erscheint einfach das Deutsche — nichts bricht. Für eine
weitere Sprache die Tabelle kopieren und `SPRACHEN` ergänzen.

## Tests

```sh
python3 -m unittest discover -s tests -t tests
```

105 Tests mit Bordmitteln, ohne Installation. Die Oberflächentests brauchen
eine Anzeige und werden ohne eine solche übersprungen; `xvfb-run -a` davor
lässt sie auf einem unsichtbaren Bildschirm laufen. Einzelheiten in
[tests/README.md](tests/README.md).

## Lizenz

MIT, siehe [LICENSE](LICENSE). Ohne jede Gewährleistung — besonders für das,
was deine Maschine damit anstellt.
