# Werkstatt

Prototypen. Was hier steht, lief am **7.11.2026** einmal richtig durch
und war die Vorlage fuer `lw_eichung.py`. Pfade und Maschinenname stehen
teils fest im Text, es gibt keine Tests, und die `*.nc` schreiben die
Skripte nur; **gestartet wird an der Maschine von Hand.**

> **Seit dem 10.11.2026 ist der Weg im Programm.** Reiter Kamera, Kasten
> *Eichen*: Raster erzeugen, brennen, Bild holen, Eichen, Pruefen. Die
> Skripte hier werden nicht mehr gebraucht und auch nicht mehr gepflegt;
> sie bleiben als Beleg dafuer, wie die Zahlen in `lw_eichung.py`
> entstanden sind.

## Warum es das gab

Die Kamera im Deckel liess sich benutzen, aber **nicht einrichten**. Alles,
was die Falcon2 am 6. und 7.11. brauchbar gemacht hat, lief ueber diese
Skripte. Im Kamerareiter gab es dafuer keinen einzigen Knopf — wer das
Programm neu aufsetzte, sah ein Bild und sonst nichts.

## Stand der Falcon2 Pro 22 W

| | |
|---|---|
| Kamera | `/dev/video2`, 2592 x 1944 (**nur in dieser Groesse holen** — 1280x720 ist ein Ausschnitt aus dem 4:3-Sensor) |
| Hoehe | 260 mm ueber dem Bett, **nachgemessen mit dem Bandmass, nicht aus Bildern bestimmt** |
| Lotpunkt | X 195 / Y 240 — dort ist der Hoehenversatz null und waechst nach aussen |
| Linse | k1, k2 aus elf Aufnahmen der Punktekarte (8 mm Punkte, 20 mm Mittenabstand) |
| Lage | 9 gebrannte Kreuze auf X/Y 30, 200, 370; Maszstab 1,00221, Drehung +0,036 Grad, Versatz 190,58 / 194,58 |
| Fehler | **1,58 mm** im Mittel ueber 340 x 340 mm; an einem zweiten, frischen Foto unabhaengig mit 1,42 mm nachgemessen |

Davor galt eine Lage aus neun Kreuzen auf nur **140 x 100 mm** in der
Bettmitte. Ihr Fehler stand mit 0,43 mm im Reiter und sah hervorragend aus
— ueber das ganze Bett gemessen waren es **2,91 mm im Mittel und 6,54 mm
vorn rechts**. Daher sagt `eichung_lesbar()` seit dem 7.11. die Flaeche
dazu: eine Fehlerzahl ohne ihre Flaeche ist eine Falle.

## Die Skripte, in der Reihenfolge ihrer Benutzung

| Datei | was sie tut |
|---|---|
| `muster_gross.py` | schreibt `muster_gross.nc`: neun Kreuze auf 340 x 340 mm, S200/F1000, das Kreuz links unten mit laengeren Armen als Richtungsmarke |
| `muster.py` | dasselbe kleiner, um einen frei waehlbaren Mittelpunkt — fuer den Fall, dass nur ein Blatt Papier da ist |
| `foto.py` | holt ein Bild in der geeichten Groesse und legt es ab. Liest nur die Kamera, schickt nichts an die Maschine |
| `kreuze_finden.py` | findet die neun Kreuze im Bild und legt Bildpunkte und Soll-Millimeter als `.npy` ab |
| `lage_neu.py` | rechnet, wie weit die *jetzige* Eichung ueber das Bett danebenliegt, und passt Maszstab, Drehung und Versatz neu an |

Die Werte schrieb am 7.11. ein eigenes Einsetz-Skript ins Maschinenprofil.
Es steht nicht mehr hier: ein Skript, das eine Eichung mit festen Zahlen
ueberschreibt, ist eine Falle, und die Zahlen stehen oben.

### Was bei der Kreuzsuche gelernt wurde

**Frei zu suchen geht nicht.** Die Spur auf Pappe ist dunkelbraun auf
braun, ein paar Graustufen tief; der Maschinenrahmen ringsum ist voller
harter Kanten und schlaegt jeden Formfilter. Drei Anlaeufe griffen daneben.

Was funktioniert:

- **Beleuchtung herausrechnen** (Bild minus stark verwischtes Bild), nicht
  schwellen. Danach ist der Kontrast ueberall gleich, egal wie hell die
  Stelle ausgeleuchtet war.
- **Nach der Form suchen:** ein Kreuz ist ein waagerechter *und* ein
  senkrechter Balken durch denselben Punkt. Das Minimum beider Antworten
  ist nur dort gross, wo beide liegen — eine einzelne Schramme oder eine
  Blattkante faellt durch.
- **Den Rand der Unterlage ausschliessen.** Er wirft einen harten
  Schattenstrich. Ein Saum von 20 Bildpunkten nimmt ihn mit und die
  aeusseren Kreuze nicht — 80 Punkte waren zu viel und haben sie
  mitgenommen.
- **Die alte Eichung als Wegweiser.** Sie ist nicht falsch, nur ungenau:
  sie sagt auf ein paar Millimeter, wo jedes Kreuz liegt, und gesucht wird
  nur in einem Fenster darum. Damit ist der Fund auch gleich zugeordnet.
  **Beim allerersten Eichen gibt es diesen Wegweiser nicht** — das ist der
  heikelste Punkt des ganzen Vorhabens.
- Mit dem Handy von der Seite leuchten. Die Gehaeuse-LED ueberstrahlt
  helles Material, und auf Pappe ist die Spur auch eine Rille: flaches
  Licht wirft einen Schatten hinein. Das Kreuz vorn links liegt in der
  dunkelsten Ecke dicht an der Schiene und war zweimal nur von Hand zu
  finden.

## Was daraus geworden ist: `lw_eichung.py`

Gebaut am **10.11.2026**, mit 44 Tests. Die Punktekarte faellt weg: ein
Raster aus 25 gebrannten Kreuzen ueber das ganze Bett liefert Linse,
Homographie und Lage aus *einem* Foto in *einem* Anpassungsschritt — kein
Ausdruck, keine elf Aufnahmen, keine Frage, ob die Karte flach lag.

Der Ablauf im Reiter Kamera, Kasten *Eichen*:

1. **Raster erzeugen** — fragt nach, welche Ebene gemeint ist
   (Materialstaerke + Unterlage), schreibt den Brennauftrag und laedt ihn
   als ganz gewoehnlichen Job. Gestartet wird er wie jeder andere.
2. **Bild holen** (der Knopf von vorher).
3. **Eichen** — sucht die Kreuze, passt an, zeigt den Fehler mit seiner
   Flaeche und uebernimmt erst auf Zusage.
4. **Pruefen** — frisches Bild, Kreuze suchen, Fehler gegen die
   *gespeicherte* Eichung. Der Knopf, der den Fehler Wochen frueher
   gezeigt haette.

Beim allerersten Eichen gibt es keinen Wegweiser, der sagt, wo die Kreuze
liegen. Dann oeffnet sich ein Fenster mit dem Bild und fragt nach vier
Eckkreuzen — nach Maschinenkoordinaten, nicht nach "oben links": wie herum
die Kamera im Bild liegt, weiss das Programm an der Stelle ja gerade noch
nicht. Das erste Kreuz hat laengere Arme und ist daran zu erkennen.

### Was die Rechnung traegt

**Stehen k1, k2 und die Verzeichnungsmitte fest, ist die Homographie
linear zu bestimmen.** Damit bleibt eine Suche ueber vier Zahlen statt
ueber zwoelf. Gemessen wird der Fehler dabei in Millimetern, nicht in
Bildpunkten: die Tonne staucht den Bildrand, dort sind Millimeter weniger
Bildpunkte wert, und wer in Bildpunkten anpasst, gewichtet ausgerechnet
die Mitte hoch, an der ohnehin alles stimmt.

### Der Hebel ist die Mitte, nicht die Zahl der Kreuze

Am kuenstlichen Modell gemessen, Fehler ueber das ganze Bett:

| | Mitte fest in der Bildmitte | Mitte mitgesucht |
|---|---|---|
| 9 Kreuze | 1,49 / 3,14 mm | 0 |
| 25 Kreuze | 1,31 / 3,40 mm | 0 |

Mehr Kreuze bringen **nichts**, solange die Verzeichnungsmitte auf der
Bildmitte festgenagelt ist — die Linse sitzt bei dieser Kamera 100
Bildpunkte daneben. Genau dort steckten die 1,4 mm, die am 7.11. nach der
Neuanpassung uebrig blieben.

Mit Messrauschen und freier Mitte (25 Kreuze): 0,5 Bildpunkte Rauschen →
0,10 mm im Mittel, 0,38 mm groesster. **Unter einem halben Millimeter ist
erreichbar.**

## Offen

**Die Kamerahoehe ist ungeprueft.** 260 mm sind mit dem Bandmass gemessen,
bis ans Gehaeuse — die Linse sitzt ein Stueck darin. Aus *einem* Foto ist
sie grundsaetzlich nicht zu bestimmen: ein anderes H aendert die Stauchung
um (H−d)/H, und die wird vom Maszstab exakt verschluckt, der Restfehler
bleibt gleich.

Zu messen ist sie mit **zwei Fotos derselben Kreuze aus zwei Hoehen**. Die
scheinbare Groesse waechst mit 1/(H−d); aus dem Verhaeltnis r zweier Hoehen
mit Abstand D folgt `H = d + D·r/(r−1)`. Bei 260 mm und 6 mm Unterschied
sind das 2,4 % Groessenunterschied — gut messbar. Dafuer reicht es, die
schon gebrannte Pappe um ein bekanntes Mass anzuheben und ein zweites Mal
zu fotografieren; nichts verschieben, nur heben.

**Die 1,4 mm Rest sassen in der Linse, nicht in der Lage** — genauer: in
ihrer *Mitte*. Siehe die Tabelle oben. Am Modell faellt der Fehler damit
unter einen halben Millimeter; an der echten Maschine ist das noch nicht
nachgemessen. Dafuer gibt es jetzt den Knopf **Pruefen**.

**Nachgemessen am Werkstueck, 9./10.11.2026.** Ein Schild von 136,3 x 72,2
mm auf einem Brettchen: die Kamera zeigte das Brett 2,3 mm breiter, als es
war, und die Gravur kam gegenueber der Brettmitte 0,7 mm weiter links und
0,7 mm weiter vorn heraus. An der linken Kante summierte sich das auf 1,8
mm. Groessenordnung und Richtung passen zu den 1,58 mm, die die damalige
Eichung fuer sich auswies.

**Ein Teil der 1,4 mm kann auch die Pappe sein.** Sie lag nicht
hundertprozentig flach, und 1 mm Woelbung sind bei 200 mm Abstand vom
Lotpunkt 0,8 mm Versatz.
