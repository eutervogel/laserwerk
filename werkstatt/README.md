# Werkstatt

Prototypen, die noch kein Programmteil sind. Was hier steht, lief am
**7.11.2026** einmal richtig durch und ist die Vorlage fuer `lw_eichung.py`
— nicht mehr. Pfade und Maschinenname stehen teils fest im Text, es gibt
keine Tests, und die `*.nc` schreiben die Skripte nur; **gestartet wird an
der Maschine von Hand.**

## Warum es das gibt

Die Kamera im Deckel laesst sich benutzen, aber **nicht einrichten**. Alles,
was die Falcon2 am 6. und 7.11. brauchbar gemacht hat, lief ueber diese
Skripte. Im Kamerareiter gibt es dafuer keinen einzigen Knopf — wer das
Programm neu aufsetzt, sieht ein Bild und sonst nichts.

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

## Der Plan: `lw_eichung.py`

### Die Punktekarte faellt weg

Bisher zwei Schritte mit zwei Datensaetzen: elf Aufnahmen einer gedruckten
Karte fuer die Linse, danach gebrannte Kreuze fuer die Lage. Beide lagen
nur in der Bildmitte — daher die 6,5 mm aussen.

Fuer andere Nutzer kommt dazu, dass sie die Karte erst masshaltig
ausdrucken muessten. Ein Tintenstrahldrucker trifft 20 mm Mittenabstand
nicht auf ein Zehntel.

**Die Maschine ist das bessere Lineal.** Sie weiss auf Hundertstel, wo ihr
Kopf steht. Ein Raster aus 25 gebrannten Kreuzen ueber das ganze Bett
belegt jede Bildecke und liefert k1/k2, Homographie und Lage aus *einem*
Foto in *einem* Anpassungsschritt — kein Ausdruck, keine elf Aufnahmen,
keine Frage, ob die Karte flach lag.

### Der Ablauf im Reiter Kamera

1. **Eichen** — "Leg etwas Flaches und Helles ein, das das Bett fuellt."
2. Materialstaerke eintragen; sie wird als `dicke` in der Eichung vermerkt.
3. **Raster erzeugen** — wird ein ganz normaler Job. Gestartet wird er wie
   jeder andere vom Benutzer; der Laser brennt.
4. **Bild holen** — 25 Kreuze gesucht, angepasst, Fehler angezeigt.
5. **Uebernehmen.**

Dazu, und fast wichtiger, ein zweiter Knopf: **Pruefen.** Frisches Bild,
Kreuze suchen, Fehler gegen die gespeicherte Eichung ausrechnen. Am 7.11.
von Hand gemacht; als Knopf haette er den Fehler Wochen frueher gezeigt.

### Was zu bauen ist

| Teil | Umfang |
|---|---|
| `lw_eichung.py`: Raster erzeugen, Kreuze finden, gemeinsame Anpassung von k1/k2, Homographie und Lage (Gauss-Newton wie in `lw_kamera`) | ~350 Zeilen |
| Ablauf im Reiter Kamera | ~150 Zeilen |
| Tests gegen ein kuenstlich verzeichnetes Bild: Kreuze durch ein bekanntes Modell rechnen, anpassen, die bekannten Werte muessen zurueckkommen | ~150 Zeilen |

Der kuenstliche Test ist der Kern. Nur er prueft die Anpassung, ohne dass
eine Maschine laeuft.

**Rueckfalltuer fuer die Kreuzsuche:** findet sie nicht alle, zeigt das
Programm das Bild und laesst die vier Eckkreuze anklicken. Daraus kommt
der Wegweiser, der beim ersten Eichen fehlt — danach greift die
fenstergefuehrte Suche fuer alle 25. Die Gittererkennung, die
`lw_kamera` fuer die Punktekarte schon kann (Basis aus den haeufigsten
kurzen Verschiebungen), ist der zweite Anlauf.

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

**Die 1,4 mm Rest sitzen in der Linse, nicht mehr in der Lage.** Ein
starres Anpassen von Maszstab, Drehung und Versatz kann nicht besser
werden. Das Bild zeigt deutliche Tonnenverzeichnung — die Bettkanten sind
sichtbar gebogen —, und k1/k2 stammen aus der Punktekarte in der
Bildmitte. Das 25er-Raster sollte unter einen halben Millimeter kommen.

**Ein Teil der 1,4 mm kann auch die Pappe sein.** Sie lag nicht
hundertprozentig flach, und 1 mm Woelbung sind bei 200 mm Abstand vom
Lotpunkt 0,8 mm Versatz.
