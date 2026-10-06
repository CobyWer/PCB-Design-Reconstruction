#PCB Comparison Tests
These 4 programs conduct 4 different tests to compare the reconstructed board to the ground truth board to examine the quality of the reconstruction the 4 tests are summarized below.


##1. Netlist / connectivity comparison

This is usually the most valuable check, since it verifies function rather than appearance.

Net-to-net diff: Extract netlists from both designs (KiCad: .net files or via kicad-cli/pcbnew Python API; Altium: netlist export or the Scripting API) and diff pin-to-pin connectivity. This tells you if your reverse-engineered board is electrically equivalent even if the layout differs.
Ratsnest/airwire comparison: If you import your RE'd netlist into the same tool as the original schematic, unrouted/unmatched nets show up immediately as ratsnest errors.
Component-to-net mapping: Confirms each part is tied to the same signal, even if reference designators differ.


##2. Physical layout comparison

Footprint/placement diff: Compare X/Y coordinates, rotation, and layer of each component between board files. Both tools expose this via scripting (KiCad's pcbnew Python module, Altium's IPCB_Board COM/scripting objects).
Trace geometry: Compare copper polygons/segments per layer — width, layer count, via placement, stackup. Useful for spotting impedance-relevant differences (trace width changes suggest a different controlled-impedance target).
Layer stackup comparison: Copper layer count, dielectric thickness, material — importable from Gerber job files or ODB++/IPC-2581 if you have them.


##3. Design rule / manufacturing-level comparison

Run DRC on both designs with the same rule set and compare violation counts/types.
Compare clearance, via size, and annular ring specs extracted from each design.
If you have Gerbers for the original, tools like Gerbv, CAM350, or scripted image-diff-on-Gerber-primitives (not raster images, but vector primitive diffs) can catch geometric drift layer by layer.


##4. Electrical/simulation-level comparison

If both have SPICE-capable models attached, compare simulated behavior (Altium's mixed-signal simulation, or export to ngspice from KiCad) rather than just topology — useful when you suspect a functionally-equivalent-but-differently-implemented sub-circuit.
Impedance profile comparison via stackup + trace width, if you're validating a RE'd high-speed design.