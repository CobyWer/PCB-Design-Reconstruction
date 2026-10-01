HOW TO RUN
==========
Double-click RUN_MERGER.bat, then enter board width and height in millimetres.
For the included four-layer test board, enter 100 and 100.
Python 3 is required. No pip packages are needed.

FILES
=====
Keep netlistmerge.py and RUN_MERGER.bat together.
By default, the program reads reviewed_netlist.txt and IPC_2581_VCU.txt from
that same folder. Copies of your current test-board inputs are included.
Replace reviewed_netlist.txt with your latest raw netlist when needed.
The merger does not automatically refresh this copy after reconstruction.

The output is COMPLETE_LOGICAL_NETLIST.txt in this folder. Each successful
run replaces that output. Your original files elsewhere are not modified.

To choose files elsewhere, use PowerShell from this folder:
py -3 .\netlistmerge.py --netlist "C:\path\reviewed_netlist.txt" --altium "C:\path\IPC_2581_VCU.txt" --output "C:\path\COMPLETE_LOGICAL_NETLIST.txt" --width 100 --height 100

Input image dimensions default to 2560 x 2550 pixels, as in the original
merger. For different dimensions, also pass --image-width and --image-height.

WHAT CHANGED
============
The reader accepts both the original and reviewed raw netlist formats.
It reads decimal pad coordinates and skips explicit Via and Copper records.
Malformed pad records cause an error before output is written.

OUTPUT FORMAT IS UNCHANGED
==========================
PCB LOGICAL NETLIST (Cleaned & Mapped)
==================================================

Net 1:
  J501-5
  <--->  R12-2
  <--->  SW202-3

As before: retain raw net numbers, sort and deduplicate component-pin names,
remove unmatched coordinates, and omit nets with fewer than two unique pins.
No extra metadata is added to the output text file.

MATCHING BEHAVIOUR
==================
The original Altium package/component coordinate calculation, 25.4 mm origin
offset, Y flip, and nearest-pin threshold of less than 30 pixels are retained.
Altium supplies component/pin identities; its net names do not overwrite or
repair reconstructed connectivity. This format update does not fix false
connections or missing planes in the raw netlist. The original matcher also
does not filter pins by copper layer and may misidentify nearby pads.
