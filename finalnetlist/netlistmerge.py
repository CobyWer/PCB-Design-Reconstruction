import xml.etree.ElementTree as ET
import re
import math
import os

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

    def translate_netlist(self, netlist_path, vcu_pins, output_filename):
        """Maps the raw coordinate netlist to the VCU components and cleans the output."""
        print(f"Mapping coordinates in {netlist_path}...")
        try:
            with open(netlist_path, 'r', encoding='utf-8') as f:
                raw_data = f.read()

            # Find every instance of a Pad coordinate in the raw netlist
            pad_pattern = re.compile(r'Pad \[Layer \d+ @ \(\s*(\d+)\s*,\s*(\d+)\s*\)\]')
            
            def replace_pad_with_comp(match):
                net_px_x = int(match.group(1))
                net_px_y = int(match.group(2))
                
                closest_pin = None
                min_dist = float('inf')
                
                # Find the closest physical pin using Pixel Distance
                for vpin in vcu_pins:
                    dist = math.hypot(net_px_x - vpin['px'], net_px_y - vpin['py'])
                    if dist < min_dist:
                        min_dist = dist
                        closest_pin = vpin
                
                # If a pin is found within ~30 pixels (~1.2mm), replace it
                if closest_pin and min_dist < 30:
                    return f"{closest_pin['ref']}-{closest_pin['pin']}"
                else:
                    return f"TP_(X:{net_px_x}, Y:{net_px_y})"

            # Swap all coordinates for actual component names
            final_netlist = pad_pattern.sub(replace_pad_with_comp, raw_data)

            print("Cleaning up duplicates and Test Points...")
            cleaned_nets = []
            
            # Split the text by 'Net X:'
            raw_nets = final_netlist.split("Net ")
            
            for raw_net in raw_nets[1:]: # Skip the header
                lines = raw_net.strip().split('\n')
                if not lines: continue
                net_name = lines[0].replace(':', '').strip()
                
                # Extract all pins
                pins = []
                for line in lines[1:]:
                    line = line.strip()
                    if not line: continue
                    if line.startswith('<--->'):
                        pins.append(line.replace('<--->', '').strip())
                    else:
                        pins.append(line)
                
                # 1. Remove all the Vias/Test Points (TP_)
                pins = [p for p in pins if not p.startswith('TP_')]
                
                # 2. Deduplicate the remaining pins
                unique_pins = sorted(list(set(pins)))
                
                # Only keep nets that actually connect 2 or more component pins
                if len(unique_pins) > 1:
                    net_str = f"Net {net_name}:\n  " + "\n  <--->  ".join(unique_pins) + "\n"
                    cleaned_nets.append(net_str)

            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write("PCB LOGICAL NETLIST (Cleaned & Mapped)\n")
                f.write("==================================================\n\n")
                f.write("\n".join(cleaned_nets))
                
            print(f"Success! Final logical netlist saved to: {output_filename}")
            
        except Exception as e:
            print(f"Error reading/writing netlist: {e}")

def main():
    print("--- IPC-2581 Logical Netlist Mapper ---")
    w = float(input("Enter board width in mm (e.g., 100): "))
    h = float(input("Enter board height in mm (e.g., 100): "))
    
    mapper = XMLNetlistMapper(board_width_mm=w, board_height_mm=h)
    
    # 1. Parse the VCU using xml.etree
    vcu_pins = mapper.parse_vcu_xml("IPC_2581_VCU.txt")
    
    if vcu_pins:
        # 2. Map those components, clean duplicates, and export
        mapper.translate_netlist("finaltets_netlist.txt", vcu_pins, "COMPLETE_LOGICAL_NETLIST.txt")

if __name__ == "__main__":
    main()