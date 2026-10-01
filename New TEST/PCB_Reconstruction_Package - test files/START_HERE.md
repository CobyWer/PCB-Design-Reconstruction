# Run the PCB reconstruction — native track version

This folder contains the revised program and byte-for-byte copies of all twelve
real input files. Your originals are untouched.

## Easiest way on Windows

1. Double-click **run_program.bat**.
2. Enter the **board width**, **board length (height)** in millimetres, and
   **number of copper layers**. These questions appear every time you run it.
   Press Enter at a question to use its default from `settings.json`: initially
   **100 × 100 mm** and **6 layers**. The dimensions have not been independently
   measured. Your answers apply to that run without changing the defaults.
   Layer counts must be even, from 2 to 32. For 4 layers, the program uses
   `inputs/l0` through `inputs/l3`; for 6 layers, it uses `l0` through `l5`.
   Each selected layer needs its CSV and matching PNG (or JPG).
3. On the first run, the launcher creates a local `.venv` and installs Shapely,
   NetworkX and Pillow. This requires Internet access. Later runs reuse it.
4. Wait for **Finished**. The console stays open so you can read any messages.
5. Open **output/reviewed_tracks.kicad_pcb** in KiCad. Read
   **output/reviewed_netlist.txt** for the coordinate-based netlist.

Python 3.10 or newer must be installed. Your existing Python 3.14 can run this
version; it does not require Centerline, Fiona or GDAL. KiCad is needed only to
view/edit the board, not to run the converter.

## Run from VS Code or PowerShell

Open this package folder in VS Code, open a terminal, and run:

```powershell
python .\launch.py
```

If `python` selects the wrong interpreter, use:

```powershell
py -3 .\launch.py
```

To use the values in `settings.json` without prompts:

```powershell
python .\launch.py --non-interactive
```

After the first run, select `.venv\Scripts\python.exe` as VS Code's Python
interpreter if you want to run the converter directly. No terminal activation
or PowerShell execution-policy change is needed.

## What's in the folder

- `run_program.bat`: double-click launcher for Windows.
- `launch.py`: creates the local environment and runs the converter.
- `kicad_reconstruct_reviewed.py`: the revised reconstruction program.
- `trace_tracks.py`: generates editable track segments and their pad/via connections.
- `requirements.txt`: the three required packages.
- `settings.json`: default dimensions, layer count and reconstruction tolerances.
- `inputs/`: unchanged copies of `l0.csv`–`l5.csv` and `l0.png`–`l5.png`.
- `input_checksums.json`: SHA-256 hashes used to verify the copies.
- `output/`: generated board, netlist, report and six annotation overlays.
- `.venv/`: created automatically; local Python environment.

Every run replaces the generated files in `output/`. Save that folder elsewhere
before rerunning if you want to keep an earlier result. The program reads the
input files without modifying them.

## Settings and interpretation

`contact_tolerance_px` is 1 pixel by default, matching the repeated small gaps
between annotations in these inputs. Inferred connections are recorded in the
report and receive small copper stitches in the generated board. Set it to 0
for strict geometric contact. Other settings can be left at their defaults.

This version imports trace annotations as **native KiCad track segments** with
locally estimated widths. Pads remain pads and vias remain vias. You can select,
move, drag and change track widths in KiCad using its normal track tools.

If you already have the earlier board open, close that tab and open
**reviewed_tracks.kicad_pcb**. The older **reviewed_contours.kicad_pcb** contains
zones and is not the updated output. The program preserves that old file.

The track representation approximates irregular copper outlines with straight
segments and round ends; it does not reproduce every boundary pixel exactly.
The netlist is still a partial reconstruction: some copper visible in the
X-rays is absent from the CSV annotations and is not extracted automatically.
Via drill sizes are estimates, and the rectangular outline represents the image
extent. The coordinate labels are not component reference/pin identifiers.

If moving this folder to a different location or computer after setup, move the
program and inputs, but leave `.venv` behind; the launcher will create a new
environment. Python virtual environments are not portable between locations.
