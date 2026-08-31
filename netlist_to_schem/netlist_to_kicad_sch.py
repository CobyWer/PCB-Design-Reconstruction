#!/usr/bin/env python3
"""
netlist_to_kicad_sch.py  (v2 -- component-aware)
================================================
Generate a valid KiCad (v7/v8) .kicad_sch from a LOGICAL netlist whose nodes
are real "REFDES-PIN" tokens, e.g.

    Net 14:
      C1-1
      <--->  U4-25
      <--->  K1-1

Each distinct REFDES becomes one component symbol carrying its real pins
(C1 -> 1,2 ; U4 -> 7,8,...,64 ; J1 -> A12_B1, SH3, ...). Pins are split across
the left/right edges so large ICs stay readable. Connectivity uses GLOBAL
LABELS (one per pin, named by net): same-named labels are one net in KiCad.
No schematic auto-router needed; electrically exact, just not auto-arranged.

Also accepts JSON {"components":[...], "nets":{...}} for hand-built inputs.

Usage:
    python netlist_to_kicad_sch.py COMPLETE_LOGICAL_NETLIST.txt out.kicad_sch
    python netlist_to_kicad_sch.py mynet.json out.kicad_sch
"""

import sys, json, uuid, math, re
from collections import defaultdict

PITCH = 2.54
PIN_LEN = 2.54
BODY_HALF_W = 6.35
TIP = BODY_HALF_W + PIN_LEN
LABEL_GAP = 3.81

PREFIX_TYPE = {
    'R': 'R', 'C': 'C', 'L': 'L', 'D': 'D', 'Q': 'Q', 'U': 'IC', 'J': 'CONN',
    'SW': 'SW', 'S': 'SW', 'K': 'RELAY', 'X': 'XTAL', 'FB': 'FERRITE',
    'B': 'CONN', 'ARRAY': 'ARRAY', 'm': 'MISC',
}


def uid():
    return str(uuid.uuid4())


def pin_sort_key(p):
    return (0, int(p)) if p.isdigit() else (1, p)


def parse_logical_netlist(path):
    nets = {}
    cur = None
    for line in open(path):
        m = re.match(r'\s*Net\s+(\S+):', line)
        if m:
            cur = f"Net-{m.group(1)}"; nets[cur] = []; continue
        tok = re.sub(r'^\s*<--->\s*', '', line.strip()).strip()
        if not tok or cur is None or 'NETLIST' in tok or tok.startswith('='):
            continue
        m = re.match(r'^(.*)-([^-]+)$', tok)
        if m:
            nets[cur].append((m.group(1), m.group(2)))

    comp_pins = defaultdict(set)
    for members in nets.values():
        for ref, pin in members:
            comp_pins[ref].add(pin)

    components = []
    for ref in sorted(comp_pins):
        pref = re.match(r'^([A-Za-z_]+)', ref)
        value = PREFIX_TYPE.get(pref.group(1) if pref else '', ref)
        components.append({"ref": ref, "value": value,
                           "pins": sorted(comp_pins[ref], key=pin_sort_key)})
    nets_named = {net: [f"{r}.{p}" for (r, p) in members]
                  for net, members in nets.items() if len(members) >= 2}
    return {"components": components, "nets": nets_named}


def load_input(path):
    if path.lower().endswith('.json'):
        return json.load(open(path))
    return parse_logical_netlist(path)


def pin_layout(pins):
    n = len(pins)
    nL = (n + 1) // 2
    left, right = pins[:nL], pins[nL:]
    rows = max(len(left), len(right), 1)
    height = rows * PITCH + PITCH
    half = height / 2.0
    layout = {}
    for i, p in enumerate(left):
        layout[p] = ('L', -TIP, round(half - PITCH * (i + 1), 3))
    for i, p in enumerate(right):
        layout[p] = ('R', TIP, round(half - PITCH * (i + 1), 3))
    return layout, height


def make_lib_symbol(ref, pins, value):
    layout, height = pin_layout(pins)
    half = height / 2.0
    s = [f'    (symbol "GEN:{ref}"',
         '      (pin_numbers hide) (pin_names (offset 1.016))',
         '      (in_bom yes) (on_board yes)',
         f'      (property "Reference" "{ref}" (at {-BODY_HALF_W} {round(half+1.27,2)} 0)',
         '        (effects (font (size 1.27 1.27)) (justify left)))',
         f'      (property "Value" "{value}" (at {-BODY_HALF_W} {round(-half-1.27,2)} 0)',
         '        (effects (font (size 1.27 1.27)) (justify left)))',
         '      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
         '      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
         f'      (symbol "{ref}_0_1"',
         f'        (rectangle (start {-BODY_HALF_W} {round(half,2)}) (end {BODY_HALF_W} {round(-half,2)})',
         '          (stroke (width 0.254) (type default)) (fill (type background))))',
         f'      (symbol "{ref}_1_1"']
    for p in pins:
        side, x, y = layout[p]
        rot = 180 if side == 'L' else 0
        s.append(f'        (pin passive line (at {x} {y} {rot}) (length {PIN_LEN})')
        s.append(f'          (name "{p}" (effects (font (size 1.0 1.0))))')
        s.append(f'          (number "{p}" (effects (font (size 1.0 1.0)))))')
    s.append('      )')
    s.append('    )')
    return "\n".join(s), layout, height


def merge_shorted_nets(nets):
    """If a pin appears on >1 net, those nets are electrically one (the pin
    shorts them). Union such nets so every pin maps to exactly one net.
    Returns (merged_nets, warnings)."""
    parent = {n: n for n in nets}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a

    def union(a, b):
        parent[find(a)] = find(b)

    pin_to_nets = defaultdict(list)
    for net, refs in nets.items():
        for pr in refs:
            pin_to_nets[pr].append(net)

    warnings = []
    for pin, ns in pin_to_nets.items():
        if len(ns) > 1:
            warnings.append((pin, sorted(set(ns))))
            for other in ns[1:]:
                union(ns[0], other)

    merged = defaultdict(list)
    for net, refs in nets.items():
        root = find(net)
        merged[root].extend(refs)
    # dedupe pins within a merged net, keep order
    out = {}
    for net, refs in merged.items():
        seen, uniq = set(), []
        for r in refs:
            if r not in seen:
                seen.add(r); uniq.append(r)
        out[net] = uniq
    return out, warnings


def generate(netlist, out_path, project_name="generated"):
    comps = netlist["components"]
    nets, warnings = merge_shorted_nets(netlist["nets"])
    if warnings:
        print("WARNING: pins found on multiple nets (treated as shorted -> nets merged):")
        for pin, ns in warnings:
            print(f"   {pin} appears on {ns}")
    pin_net = {}
    for net_name, refs in nets.items():
        for pr in refs:
            pin_net[pr] = net_name

    lib_blocks, layouts, heights = [], {}, {}
    for c in comps:
        block, layout, h = make_lib_symbol(c["ref"], c["pins"], c.get("value", ""))
        lib_blocks.append(block); layouts[c["ref"]] = layout; heights[c["ref"]] = h

    out = ['(kicad_sch', '  (version 20230121)',
           '  (generator "netlist_to_kicad_sch")', f'  (uuid "{uid()}")',
           '  (paper "A4")', '  (lib_symbols']
    out += lib_blocks
    out.append('  )')

    COL_W = 2 * (TIP + LABEL_GAP + 14)
    SHEET_W = COL_W * max(1, int(math.ceil(math.sqrt(len(comps)))))
    x_cursor, y_cursor, row_h = 40.0, 40.0, 0.0
    placements = []
    for c in comps:
        h = heights[c["ref"]]
        if x_cursor > 40.0 + SHEET_W:
            x_cursor = 40.0; y_cursor += row_h + 12.0; row_h = 0.0
        placements.append((c, round(x_cursor + TIP + LABEL_GAP + 6, 2),
                           round(y_cursor + h / 2 + 4, 2)))
        x_cursor += COL_W; row_h = max(row_h, h + 8)

    wires, labels = [], []
    for c, cx, cy in placements:
        ref, h = c["ref"], heights[c["ref"]]
        out.append(f'  (symbol (lib_id "GEN:{ref}") (at {cx} {cy} 0) (unit 1)')
        out.append('    (in_bom yes) (on_board yes) (dnp no)')
        out.append(f'    (uuid "{uid()}")')
        out.append(f'    (property "Reference" "{ref}" (at {cx-BODY_HALF_W} {round(cy-h/2-1.27,2)} 0)')
        out.append('      (effects (font (size 1.27 1.27)) (justify left)))')
        out.append(f'    (property "Value" "{c.get("value","")}" (at {cx-BODY_HALF_W} {round(cy+h/2+1.27,2)} 0)')
        out.append('      (effects (font (size 1.27 1.27)) (justify left)))')
        for p in c["pins"]:
            out.append(f'    (pin "{p}" (uuid "{uid()}"))')
        out.append('    (instances')
        out.append(f'      (project "{project_name}"')
        out.append(f'        (path "/" (reference "{ref}") (unit 1))))')
        out.append('  )')
        for p in c["pins"]:
            net = pin_net.get(f"{ref}.{p}")
            if net is None:
                continue
            side, lx, ly = layouts[ref][p]
            tx, ty = round(cx + lx, 2), round(cy + ly, 2)
            if side == 'L':
                ex = round(tx - LABEL_GAP, 2); just = 'right'
            else:
                ex = round(tx + LABEL_GAP, 2); just = 'left'
            wires.append((tx, ty, ex, ty))
            labels.append((ex, ty, net, just, side))

    for (x1, y1, x2, y2) in wires:
        out.append(f'  (wire (pts (xy {x1} {y1}) (xy {x2} {y2}))')
        out.append(f'    (stroke (width 0) (type default)) (uuid "{uid()}"))')
    for (lx, ly, net, just, side) in labels:
        rot = 0 if side == 'R' else 180
        out.append(f'  (global_label "{net}" (shape input) (at {lx} {ly} {rot}) (fields_autoplaced)')
        out.append(f'    (effects (font (size 1.27 1.27)) (justify {just}))')
        out.append(f'    (uuid "{uid()}"))')
    out.append(')')

    text = "\n".join(out) + "\n"
    with open(out_path, "w") as f:
        f.write(text)
    return text, comps, nets


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python netlist_to_kicad_sch.py <netlist.txt|.json> <out.kicad_sch>")
        sys.exit(1)
    nl = load_input(sys.argv[1])
    _, comps, nets = generate(nl, sys.argv[2])
    print(f"Wrote {sys.argv[2]}: {len(comps)} components, {len(nets)} nets, "
          f"{sum(len(c['pins']) for c in comps)} pins")
