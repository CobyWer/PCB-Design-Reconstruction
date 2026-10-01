# PCB Reconstruction Package

This program uses layer images and their CSV copper annotations to reconstruct a PCB. It produces an editable KiCad board, a raw coordinate netlist, and files for checking the reconstruction.

The source images and CSV files are read without being changed. Copper geometry comes from the CSV annotations; the program does **not** automatically extract missing tracks or planes from the X-ray images.

## Quick start on Windows

1. Put the matching layer CSV files and images in the `inputs` folder.
2. Double-click **run_program.bat**.
3. Enter the physical **board width**, **board length (height)** in millimetres, and **number of copper layers**.
4. Wait until the console says **Finished**.
5. Open **output/reviewed_tracks.kicad_pcb** in KiCad.
6. Find the raw netlist at **output/reviewed_netlist.txt** and review any warnings in **output/review_report.json**.

Pressing Enter at a question uses the default in `settings.json`. The current defaults are **100 × 100 mm and 6 layers**. They are defaults, not independently measured board dimensions. Your answers apply only to the current run; they do not change the saved defaults.

For the four-layer test board, select **4 layers** and supply `l0` through `l3`. For the six-layer X-ray board, select **6 layers** and supply `l0` through `l5`.

## Requirements

- **Python 3.10 or newer**, available through `py` or `python` on Windows.
- Internet access for the initial dependency installation if dependencies are not already installed in the package environment.
- KiCad to open and edit the generated board. KiCad is not required to run the reconstruction.

The launcher creates a local `.venv` environment and installs **Shapely, NetworkX, and Pillow** from `requirements.txt`. Later runs reuse that environment. This program does not require Centerline, Fiona, or GDAL.

## Required files and folders

Keep this structure when using the batch launcher:

```text
PCB_Reconstruction_Package/
  run_program.bat
  launch.py
  kicad_reconstruct_reviewed.py
  trace_tracks.py
  requirements.txt
  settings.json
  inputs/
    l0.csv
    l0.png
    l1.csv
    l1.png
    ...one CSV and image for each selected layer...
  output/                 created automatically if missing
  .venv/                  created automatically if missing
```

`input_checksums.json`, `README.md`, and `START_HERE.md` are not required for execution. The checksum file records the originally supplied input copies; it does **not** restrict the program to those inputs. Each run calculates fresh input hashes and records them in its report.

### Input rules

- Layer names start at `l0` and continue without gaps. The selected layer count must be an even number from **2 to 32**.
- Each layer needs `lN.csv` and `lN.png`. A matching `lN.jpg` is also supported when the PNG is absent.
- All layer images must have the same pixel dimensions. Their annotations must use the same aligned image coordinate system; the program does not automatically register misaligned layers.
- CSV files require the columns **Type** and **Vertices**. **Instance ID** is optional.
- Accepted Type values are `pad`, `via`, `trace`, `plane`, and `zone` (case-insensitive).
- Vertices contain JSON coordinate arrays in image pixels, representing one polygon ring or multiple rings. The program interprets nested rings as holes or islands and keeps separate contours separate.
- Enter the physical dimensions represented by the full image extent. Incorrect dimensions produce an incorrectly scaled KiCad board.

You can use another board's inputs. Place its complete matching set in `inputs` and choose the correct dimensions and layer count. Keep different boards' datasets in separate folders or package copies to avoid mixing their layers. Files above the selected layer count are not read.

## What each Python file does

| File | Purpose |
|---|---|
| `launch.py` | Sets up the local Python environment, reads settings, asks for dimensions and layer count, and starts reconstruction. |
| `kicad_reconstruct_reviewed.py` | Reads and checks annotations, matches via observations across layers, groups connected copper into candidate nets, and writes the board, raw netlist, report, and overlays. |
| `trace_tracks.py` | Converts annotated trace shapes into native editable KiCad track segments and connects those segments to the relevant pads and vias. |

## Output files

| File | Contents |
|---|---|
| `output/reviewed_tracks.kicad_pcb` | Reconstructed KiCad board with native track segments. |
| `output/reviewed_netlist.txt` | Candidate nets containing coordinate-based pad and via identifiers, plus copper and review information. |
| `output/review_report.json` | Warnings, unresolved nearby contacts, geometry diagnostics, inferred connections, settings, and input hashes. |
| `output/overlay_lN.png` | Annotation overlay for inspecting each selected input layer. |

Successful runs replace the generated files with the same names. Copy previous results elsewhere before running if you need to retain them. The output folder is not cleared: older files, including overlays for layers no longer selected, can remain. If a run fails, existing output files may belong to an earlier run or be only partially updated; use the final **Finished** message to confirm completion.

If an older `reviewed_contours.kicad_pcb` is present, open **reviewed_tracks.kicad_pcb** for the native-track result.

## Raw netlist versus logical netlist

The reconstruction netlist identifies annotated terminals by layer, source row, and coordinates. It does not identify actual component references and pin numbers, and it does not create a schematic.

The separate **Netlist_Merger** program can map these coordinates to component pins using an Altium IPC-2581 export. To use it, copy the latest `output/reviewed_netlist.txt` into the merger folder or pass its path to that program. The merger generates `COMPLETE_LOGICAL_NETLIST.txt`; it does not repair missing or incorrect raw connectivity.

## Settings

Edit `settings.json` to change saved defaults:

| Setting | Current default | Meaning |
|---|---:|---|
| `width_mm` | 100.0 | Physical width represented by the image. |
| `height_mm` | 100.0 | Physical length/height represented by the image. |
| `layers` | 6 | Number of copper layers to read. |
| `via_match_px` | 3.0 | Pixel tolerance used to match via observations between layers. |
| `contact_tolerance_px` | 1.0 | Allows nearby annotated copper to be treated as touching within this pixel tolerance. Use 0 for strict geometric contact. |
| `near_gap_px` | 2.0 | Distance threshold for reporting nearby unresolved contacts. |
| `drill_ratio` | 0.6 | Estimates drill diameter as a fraction of observed diameter. |

Increasing contact tolerance can join copper that should be separate. Inferred gap connections are recorded in the report and receive connecting copper in the generated board. Review these assumptions rather than increasing tolerances simply to reduce the number of nets.

## Run from PowerShell or VS Code

Open a terminal in this package folder and run:

```powershell
py -3 .\launch.py
```

To use the saved settings without questions:

```powershell
py -3 .\launch.py --non-interactive
```

After initial setup, you can run the package interpreter directly:

```powershell
.\.venv\Scripts\python.exe .\launch.py
```

In VS Code, select `.venv\Scripts\python.exe` as the Python interpreter for this package. No environment activation or PowerShell execution-policy change is necessary for the commands above.

## Interpreting results and troubleshooting

- **Missing input or CSV-column error:** check the layer count, filenames, matching images, and CSV columns. The originals can remain unchanged; supply the correct files to the package.
- **Dependency installation error:** read the installation message and check Internet access and the selected Python version. The batch launcher reuses the package's environment when it exists.
- **Track reconstruction or geometry error:** the program could not safely reconstruct a shape. Read the layer/row identifier in the error. Reinstalling Python dependencies is not a geometry fix.
- **Unresolved near contacts or warnings:** a completed run can still need review. Consult `review_report.json` and the overlays. A candidate net count is not proof that all physical connections were recovered.
- **Moving to another computer or folder:** copy the program and inputs, but leave `.venv` behind. Let the launcher build a fresh environment at the new location.

The tracks approximate irregular copper outlines with straight segments and estimated widths. Drill sizes are estimates, and the board outline is the rectangular image extent. Missing plane annotations, inaccurate contours, and uncertain contacts can produce disconnected or incorrectly joined nets. Review the result before using it as a final electrical design.
