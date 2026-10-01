import xml.etree.ElementTree as ET
import re
import math
import argparse
from pathlib import Path

class XMLNetlistMapper:
    def __init__(self, board_width_mm, board_height_mm, img_width_px=2560, img_height_px=2550):
        # Configuration identical to your 2txt.py
        self.board_width = board_width_mm
        self.board_height = board_height_mm
        self.img_width = img_width_px
        self.img_height = img_height_px
        self.offset_x = 25.4 
        self.offset_y = 25.4
        self.scale_x = self.img_width / self.board_width
        self.scale_y = self.img_height / self.board_height

    def get_rotated_point(self, local_x, local_y, global_cx, global_cy, angle_deg):
        """Rotates a local pin coordinate around a component's center."""
        rad = math.radians(angle_deg)
        rot_x = local_x * math.cos(rad) - local_y * math.sin(rad)
        rot_y = local_x * math.sin(rad) + local_y * math.cos(rad)
        return global_cx + rot_x, global_cy + rot_y

    def mm_to_pixel(self, x, y):
        """Converts mm to pixels with offset and Y-flip."""
        px = int(round((x - self.offset_x) * self.scale_x))
        py = int(round((y - self.offset_y) * self.scale_y))
        py = self.img_height - py # Flip Y-Axis
        return px, py

    def parse_vcu_xml(self, vcu_path):
        """Parses the IPC-2581 XML to find Component Pins and their exact pixel locations."""
        print(f"Parsing IPC-2581 VCU file: {vcu_path}...")
        namespace = {'ipc': 'http://webstds.ipc.org/2581'}
        vcu_pins = []
        
        try:
            tree = ET.parse(vcu_path)
            root = tree.getroot()
            
            # 1. Extract Packages and local pin locations
            packages = {}
            for pkg in root.findall('.//ipc:Package', namespace):
                pkg_name = pkg.attrib.get('name')
                pins = {}
                for pin in pkg.findall('.//ipc:Pin', namespace):
                    pin_num = pin.attrib.get('number')
                    loc = pin.find('ipc:Location', namespace)
                    if loc is not None and pin_num is not None:
                        pins[pin_num] = (float(loc.attrib.get('x', 0)), float(loc.attrib.get('y', 0)))
                packages[pkg_name] = pins

            # 2. Extract Components and calculate global pin coordinates
            comp_count = 0
            for comp in root.findall('.//ipc:Component', namespace):
                ref_des = comp.attrib.get('refDes')
                pkg_name = comp.attrib.get('packageRef')
                if not ref_des or pkg_name not in packages: continue
                
                comp_loc = comp.find('ipc:Location', namespace)
                if comp_loc is None: continue
                cx, cy = float(comp_loc.attrib.get('x', 0)), float(comp_loc.attrib.get('y', 0))
                
                xform = comp.find('ipc:Xform', namespace)
                comp_rot = float(xform.attrib.get('rotation', 0)) if xform is not None else 0.0
                
                # 3. Apply rotation and translate to pixels for every pin
                for pin_num, (local_x, local_y) in packages[pkg_name].items():
                    global_x, global_y = self.get_rotated_point(local_x, local_y, cx, cy, comp_rot)
                    px, py = self.mm_to_pixel(global_x, global_y)
                    
                    vcu_pins.append({
                        'ref': ref_des,
                        'pin': pin_num,
                        'px': px,
                        'py': py
                    })
                comp_count += 1
                
            print(f"  -> Successfully extracted {len(vcu_pins)} pins from {comp_count} components.")
            return vcu_pins
            
        except Exception as e:
            print(f"Error parsing VCU XML: {e}")
            return []

    @staticmethod
    def read_raw_nets(raw_data):
        """Read original or reviewed coordinate nets; metadata is not a pin."""
        number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
        header = re.compile(r"^Net\s+(\d+)(?:\s+\([^\r\n]*\))?:$")
        old_pad = re.compile(
            rf"^Pad \[Layer \d+ @ \(\s*({number})\s*,\s*({number})\s*\)\]$")
        new_pad = re.compile(
            rf"^Pad L\d+:pad:row\d+:part\d+ \(Instance ID .*?\) @ "
            rf"\(\s*({number})\s*,\s*({number})\s*\) px$")
        nets = []
        seen = set()
        current = None
        for line_number, line in enumerate(raw_data.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            match = header.fullmatch(line)
            if match:
                net_id = match.group(1)
                if net_id in seen:
                    raise ValueError(f"Line {line_number}: duplicate Net {net_id}")
                seen.add(net_id)
                current = []
                nets.append((net_id, current))
                continue
            if line.startswith('Net '):
                raise ValueError(f"Line {line_number}: unrecognized net heading: {line}")
            if line.startswith('<--->'):
                line = line[len('<--->'):].strip()
            match = old_pad.fullmatch(line) or new_pad.fullmatch(line)
            if match:
                if current is None:
                    raise ValueError(f"Line {line_number}: pad appears before its net")
                current.append((float(match.group(1)), float(match.group(2))))
            elif line.startswith('Pad '):
                raise ValueError(f"Line {line_number}: unrecognized pad format: {line}")
            elif current is not None and not line.startswith(('Via ', 'Copper:', 'Status:')):
                raise ValueError(f"Line {line_number}: unrecognized net record: {line}")
        if not nets:
            raise ValueError('No coordinate nets found in the input file')
        return nets

    def translate_netlist(self, netlist_path, vcu_pins, output_filename):
        """Use the original mapping and output rules with either raw format."""
        print(f"Mapping coordinates in {netlist_path}...")
        raw_data = Path(netlist_path).read_text(encoding='utf-8-sig')
        nets = self.read_raw_nets(raw_data)
        cleaned_nets = []
        matched = unmatched = 0
        for net_name, coordinates in nets:
            pins = set()
            for x, y in coordinates:
                closest = min(vcu_pins,
                              key=lambda p: math.hypot(x - p['px'], y - p['py']),
                              default=None)
                # Preserve original nearest-pin rule: strictly less than 30 px.
                if closest and math.hypot(x - closest['px'], y - closest['py']) < 30:
                    pins.add(f"{closest['ref']}-{closest['pin']}")
                    matched += 1
                else:
                    # Original TP_ entries are removed from the final output.
                    unmatched += 1
            unique_pins = sorted(pins)
            if len(unique_pins) > 1:
                net_str = f"Net {net_name}:\n  " + "\n  <--->  ".join(unique_pins) + "\n"
                cleaned_nets.append(net_str)
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write("PCB LOGICAL NETLIST (Cleaned & Mapped)\n")
            f.write("==================================================\n\n")
            f.write("\n".join(cleaned_nets))
        print(f"Read {len(nets)} raw nets; matched {matched} pad observations; "
              f"excluded {unmatched} unmatched observations.")
        print(f"Success! Wrote {len(cleaned_nets)} logical nets to: {output_filename}")


def positive_float(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError('Value must be a positive finite number')
    return value


def main():
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description='Map raw pad coordinates to Altium component pins; preserve the original logical-netlist format.')
    parser.add_argument('--netlist', type=Path, default=base / 'reviewed_netlist.txt')
    parser.add_argument('--altium', type=Path, default=base / 'IPC_2581_VCU.txt')
    parser.add_argument('--output', type=Path, default=base / 'COMPLETE_LOGICAL_NETLIST.txt')
    parser.add_argument('--width', type=positive_float, help='Board width in mm')
    parser.add_argument('--height', type=positive_float, help='Board height in mm')
    parser.add_argument('--image-width', type=positive_float, default=2560, help='Input image width in pixels')
    parser.add_argument('--image-height', type=positive_float, default=2550, help='Input image height in pixels')
    args = parser.parse_args()
    try:
        print('--- IPC-2581 Logical Netlist Mapper ---')
        width = args.width or positive_float(input('Enter board width in mm (e.g., 100): '))
        height = args.height or positive_float(input('Enter board height in mm (e.g., 100): '))
        if args.output.resolve() in (args.netlist.resolve(), args.altium.resolve()):
            raise ValueError('Output must be a different file from both inputs')
        mapper = XMLNetlistMapper(width, height, args.image_width, args.image_height)
        pins = mapper.parse_vcu_xml(args.altium)
        if not pins:
            raise ValueError('No component pins could be read from the Altium file')
        mapper.translate_netlist(args.netlist, pins, args.output)
    except (OSError, ValueError, argparse.ArgumentTypeError) as exc:
        parser.exit(1, f'Could not create logical netlist: {exc}\n')


if __name__ == '__main__':
    main()
