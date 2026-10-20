# Laserwerk

***English** · [Deutsch](README.de.md)*

Control software for diode lasers on GRBL controllers, for Linux. Drop in an
image or SVG, place it on a simulated workpiece, jog the axes, find the focus,
engrave or cut — in one window, without a subscription and without a cloud.

![Placing the artwork on the workpiece](bilder/en-01-platzieren.png)

It exists because Linux leaves a gap: LightBurn costs money, LaserGRBL is
Windows-only, and going through an Inkscape extension plus a plain G-code
sender gets tedious as soon as you want to raster greyscales or work out
settings for a new material.

> **The interface speaks English and German** (*Machine* tab → *Language*).
> Comments and identifiers in the source are German — the project grew that
> way, and the comments carry hard-won detail that would lose its edge in
> translation. Pull requests in either language are welcome.

## What it does

- **Engrave** — images (PNG, JPG, WEBP, BMP) and SVG as a raster, row by row,
  either black and white with a threshold or greyscale with varying power.
  Overscan at the row ends keeps the edges even.
- **Cut** — contours from SVG and DXF, inner before outer, several passes,
  original size 1:1 for templates straight out of CAD.
- **Place** — enter the length and width of your workpiece, then drag the
  artwork onto it with the mouse and resize it by its corners, snapping to
  edges, corners and centre.
- **Drive the machine** — jog the axes, set the origin, set a Z reference,
  trace a frame around the artwork, show where the head stands with a short
  sight cross at low power, unlock, send single G-code commands.
- **Find material settings** — a focus test along Z, a material test as a grid
  of power and feed values, and presets holding thickness, focus correction,
  power, feed and row pitch.
- **Engrave both sides** — mirror about a flip axis, with a check that the
  mirrored artwork still lands in positive coordinates.
- **Remote control via Telegram** — jog the axes and trace the sight cross from
  your phone while you stand at the workpiece. It reports back when a job
  finishes or runs into an alarm.
- **Resume** — `fortsetzen.py` finds the exact stopping point of a stalled job
  by matching the position, then streams the rest.

## How it looks

Generated G-code with a runtime estimate — the artwork lies on the simulated
board like a burn mark, and the frame with its handles can be dragged and
resized with the mouse:

![G-code generated](bilder/en-02-gcode.png)

Material values as a preset, jogging, and the tests:

| | |
|---|---|
| ![Material](bilder/en-03-material.png) | ![Machine](bilder/en-04-maschine.png) |

![Tests](bilder/en-05-tests.png)

## What it needs

- Python 3.10 or newer, with tkinter (`apt install python3-tk`)
- `pip install -r requirements.txt` — pyserial, Pillow, numpy
- optionally `zenity` for native GTK dialogs; without it the Tk ones are used
- a GRBL 1.1 controller on USB, and your user in the `dialout` group

```sh
git clone https://github.com/eutervogel/laserwerk
cd laserwerk
pip install -r requirements.txt
./laserwerk.sh
```

Settings, presets and the Telegram token live in `~/.config/laserwerk/`, not in
the project folder.

## Safety

A diode laser burns material, skin and retinas, and it sets fire to chips,
paper and dust. This program takes none of that off your hands.

- **Never leave it running unattended.** An engraving takes an hour; a
  smouldering nest takes less than a minute.
- **Wear goggles matched to the wavelength**, and so should anyone watching.
  Scattered blue light from the burn spot is enough to do harm.
- **Extract the fumes or work in the open.** Wood smoke is unpleasant; some
  other materials are toxic.
- **No PVC, no imitation leather, no TPU** — they release hydrogen chloride or
  hydrogen cyanide. They eat the mechanics too.
- **Keep something to put out a fire within reach.**
- The remote control only jogs the axes and traces the sight cross. It will not
  start a job, on purpose: full power belongs where somebody is watching. Even
  jogging deserves your eyes on the machine.

## The material settings are not yours

The presets shipped here were measured on **one** machine: 450 nm, 5.5 W
optical. A different laser, lens or focus means different values. Treat them as
a starting point for your own material test, not as a recipe. Too much power at
too little feed does not mean "darker", it eventually means "on fire".

What does carry over is the **S/F ratio**: power divided by feed, that is the
energy per millimetre. On the reference machine wood works at S830/F1000 =
0.83, suede at 0.25, and the sight cross runs at 0.08. Above roughly 0.20 the
beam burns in visibly — which is why the program refuses to trace a sight cross
beyond that.

All power values in the interface refer to a **0…1000** scale. On connecting,
Laserwerk reads `$30` from the controller and converts when sending; if yours
says 255, S830 goes out as S212 — the same fraction. It also warns when
`$32 = 0`, meaning laser mode is off: the beam then keeps burning while the
head stands still, and every pause eats a hole.

## Tested with

GRBL 1.1f on a CH340 board, a 450 nm diode laser of 5.5 W optical power,
200 × 200 mm of travel, motorised Z axis. Run on it: plywood, slate, suede,
paper (cut). White PLA cannot be marked with a blue laser — the light is
reflected.

Machine travel is set in the *Machine* tab and can be taken from `$130`/`$131`.

## Layout

| File | Purpose |
|---|---|
| `laserwerk.py` | interface, workflow, job control |
| `lw_grbl.py` | serial link, streaming, status reports |
| `lw_job.py` | raster G-code, runtime estimate, preview images, tests |
| `lw_vector.py` | SVG and DXF readers, contours, cutting G-code |
| `lw_presets.py` | material values and settings |
| `lw_style.py` | light and dark colour schemes |
| `lw_text.py` | German and English interface texts |
| `lw_dialog.py` | native dialogs through zenity, falling back to Tk |
| `lw_telegram.py` | remote control |
| `fortsetzen.py` | resume an interrupted job at its stopping point |
| `bilder/mach_bilder.py` | makes the screenshots above, on a hidden display |

No third-party libraries beyond pyserial, Pillow and numpy. The SVG and DXF
readers and the Telegram client are written from scratch, so nothing has to be
installed afterwards and nothing opens dialogs behind your back.

## Translations

`lw_text.py` maps each German source string to its English counterpart. A
missing entry simply falls back to German, so nothing breaks. To add a
language, copy the table and extend `SPRACHEN`.

## Licence

MIT, see [LICENSE](LICENSE). Without any warranty — in particular for whatever
your machine does with it.
