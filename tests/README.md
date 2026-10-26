# Tests

Laufen mit Bordmitteln, ohne Fremdbibliotheken und ohne Installation:

```sh
python3 -m unittest discover -s tests -t tests
```

Mit `-v` einzeln aufgelistet, oder gezielt:

```sh
python3 -m unittest discover -s tests -t tests -v
python3 -m unittest discover -s tests -t tests -k Nullpunkt
```

Die Oberflächentests brauchen eine Anzeige. Ohne eine solche werden sie
übersprungen; auf einem Rechner ohne Bildschirm oder wenn kein Fenster
aufspringen soll:

```sh
xvfb-run -a python3 -m unittest discover -s tests -t tests
```

## Was geprüft wird

| Datei | Inhalt |
|---|---|
| `test_job.py` | Rastern, Anlauf, Tonwertkurve, Rasterung, Laufzeitmodell, Testmuster |
| `test_vector.py` | SVG und DXF einlesen, einpassen, drehen, spiegeln, innen vor außen |
| `test_grbl.py` | Statusberichte, auch die, an denen der Lesethread einmal starb |
| `test_text.py` | Vollständigkeit und Platzhalter beider Sprachen |
| `test_projekt.py` | Projektdateien hin und zurück, auch ohne Originalvorlage |
| `test_oberflaeche.py` | Platzieren, Grenzen, Leistungsumrechnung, Nullpunkt nach STOPP, Schnitttiefe |
| `test_fortsetzen.py` | Stopp-Stelle wiederfinden, mit Tiefe auch bei mehreren Zustellungen |

## Regeln

**Die Maschine wird nie angefasst.** Kein Test öffnet einen seriellen Port;
wo eine Maschine gebraucht wird, steht die `Attrappe` aus `hilfe.py`. Sie
verhält sich wie GRBL 1.1 — ein Soft-Reset löscht dort den G92-Versatz,
damit genau der Fall geprüft werden kann, der im Betrieb wehgetan hat.

**Einstellungen bleiben unberührt.** `hilfe.py` biegt Presets, Konfiguration
und Telegram-Token auf ein Wegwerfverzeichnis um, bevor irgendetwas geladen
wird. Ohne das verstellen Tests dem Benutzer die Maschine — beim Bauen ist
genau das passiert.

**Der Bot schweigt.** `TG.Fern.start` wird stillgelegt, sonst fragt jeder
Testlauf gegen den echten Bot und streitet sich mit einem laufenden
Laserwerk um die Nachrichten.
