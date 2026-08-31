import xml.etree.ElementTree as ET
import csv
import math
import datetime
import json
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

# ==========================================
# CONFIGURATION
# ==========================================
# Exact image resolution
IMG_WIDTH_PX = 2560
IMG_HEIGHT_PX = 2550

# Physical board dimensions
BOARD_WIDTH_MM = 100.0  
BOARD_HEIGHT_MM = 100.0

# The CAD file's board profile starts at 25.4mm instead of 0mm.
OFFSET_X_MM = 25.4 
OFFSET_Y_MM = 25.4

def mm_to_pixels(poly_mm, board_w, board_h, img_w, img_h):
    """Converts raw millimeters to exact integer pixel coordinates and flips the Y-axis."""
    poly_px = []
    scale_x = img_w / board_w
    scale_y = img_h / board_h
    
    for x, y in poly_mm:
        # 1. Apply offset and scale to get the raw pixel coordinate
        px = int(round((x - OFFSET_X_MM) * scale_x))
        py = int(round((y - OFFSET_Y_MM) * scale_y))
        
        # 2. FLIP THE Y-AXIS to match the top-down image space
        py = img_h - py
        
        poly_px.append([px, py])
        
    return poly_px

def generate_circle_vertices(cx, cy, diameter, num_points=32):
    """Generates a 32-point polygon for vias, holes, and circular pads."""
    radius = diameter / 2.0
    vertices = []
    for i in range(num_points):
        angle = 2 * math.pi * i / num_points
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        vertices.append([x, y])
    vertices.append(vertices[0])
    return vertices

def generate_line_polygon(x1, y1, x2, y2, width):
    """Converts a 1D line segment into a 2D rectangular polygon."""
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length == 0: return []
        
    nx = dx / length
    ny = dy / length
    px = -ny * (width / 2.0)
    py = nx * (width / 2.0)
    
    p1 = [x1 + px, y1 + py]
    p2 = [x1 - px, y1 - py]
    p3 = [x2 - px, y2 - py]
    p4 = [x2 + px, y2 + py]
    return [p1, p2, p3, p4, p1]

def get_rotated_point(local_x, local_y, global_cx, global_cy, angle_deg):
    """Rotates a local pin coordinate around a component's center."""
    rad = math.radians(angle_deg)
    rot_x = local_x * math.cos(rad) - local_y * math.sin(rad)
    rot_y = local_x * math.sin(rad) + local_y * math.cos(rad)
    return global_cx + rot_x, global_cy + rot_y

def generate_rotated_polygon_pad(global_cx, global_cy, local_poly_points, angle_deg):
    """Takes local points, rotates them, and maps them to the global board."""
    poly = []
    for px, py in local_poly_points:
        nx, ny = get_rotated_point(px, py, global_cx, global_cy, angle_deg)
        poly.append([nx, ny])
    if poly and poly[0] != poly[-1]:
        poly.append(poly[0])
    return poly

def main():
    input_file = 'IPC_2581_VCU.txt'
    namespace = {'ipc': 'http://webstds.ipc.org/2581'}
    
    print(f"Parsing {input_file}...")
    try:
        tree = ET.parse(input_file)
        root = tree.getroot()
    except FileNotFoundError:
        print(f"Error: {input_file} not found.")
        return

    timestamp = datetime.datetime.now().strftime('%m/%d/%Y %H:%M')

    # ==========================================
    # 0. BUILD SHAPE DICTIONARY
    # ==========================================
    shape_dict = {}
    for entry in root.findall('.//ipc:DictionaryStandard/ipc:EntryStandard', namespace):
        entry_id = entry.attrib.get('id')
        
        # Check 1: Rectangles
        rect = entry.find('ipc:RectCenter', namespace)
        if rect is not None:
            w = float(rect.attrib['width'])
            h = float(rect.attrib['height'])
            shape_dict[entry_id] = {'type': 'polygon', 'points': [(-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)]}
            continue

        # Check 2: Circles
        circle = entry.find('ipc:Circle', namespace)
        if circle is not None:
            shape_dict[entry_id] = {'type': 'circle', 'diameter': float(circle.attrib.get('diameter', 0))}
            continue

        # Check 3: Complex Custom Polygons
        poly_begin = entry.find('.//ipc:PolyBegin', namespace)
        if poly_begin is not None:
            pts = [(float(poly_begin.attrib['x']), float(poly_begin.attrib['y']))]
            for step in entry.findall('.//ipc:PolyStepSegment', namespace):
                pts.append((float(step.attrib['x']), float(step.attrib['y'])))
            shape_dict[entry_id] = {'type': 'polygon', 'points': pts}
            continue

        # Check 4: Ovals / Slotted Pads 
        oval = entry.find('ipc:Oval', namespace)
        if oval is not None:
            w = float(oval.attrib['width'])
            h = float(oval.attrib['height'])
            pts = []
            num_points = 32
            
            if w >= h:
                r = h / 2.0
                dx = (w - h) / 2.0
                for i in range(num_points // 2 + 1):
                    angle = -math.pi/2 + math.pi * i / (num_points // 2)
                    pts.append((dx + r * math.cos(angle), r * math.sin(angle)))
                for i in range(num_points // 2 + 1):
                    angle = math.pi/2 + math.pi * i / (num_points // 2)
                    pts.append((-dx + r * math.cos(angle), r * math.sin(angle)))
            else:
                r = w / 2.0
                dy = (h - w) / 2.0
                for i in range(num_points // 2 + 1):
                    angle = 0 + math.pi * i / (num_points // 2)
                    pts.append((r * math.cos(angle), dy + r * math.sin(angle)))
                for i in range(num_points // 2 + 1):
                    angle = math.pi + math.pi * i / (num_points // 2)
                    pts.append((r * math.cos(angle), -dy + r * math.sin(angle)))
            
            shape_dict[entry_id] = {'type': 'polygon', 'points': pts}

    # ==========================================
    # 1. EXTRACT ALL HOLES/VIAS (Global)
    # ==========================================
    global_vias = []
    seen_vias = set()
    for hole in root.findall('.//ipc:Hole', namespace):
        try:
            x, y = float(hole.attrib['x']), float(hole.attrib['y'])
            dia = float(hole.attrib['diameter'])
            
            # Deduplicate holes that are exported multiple times
            via_sig = (round(x, 2), round(y, 2))
            if via_sig not in seen_vias:
                seen_vias.add(via_sig)
                vertices = generate_circle_vertices(x, y, dia, 32)
                global_vias.append({'Vertices_MM': vertices, 'Timestamp': timestamp, 'Type': 'via'})
        except KeyError: continue
    print(f"Extracted {len(global_vias)} unique vias/holes.")

    # ==========================================
    # 2. EXTRACT PADS (Surface Mount + PadStacks)
    # ==========================================
    pads_by_layer = {'Top Layer': [], 'PWR': [], 'GND': [], 'Bottom Layer': []}
    
    packages = {}
    for pkg in root.findall('.//ipc:Package', namespace):
        pkg_name = pkg.attrib.get('name')
        pins = []
        for pin in pkg.findall('.//ipc:Pin', namespace):
            loc = pin.find('ipc:Location', namespace)
            spr = pin.find('ipc:StandardPrimitiveRef', namespace)
            if loc is not None and spr is not None:
                pins.append({
                    'x': float(loc.attrib.get('x', 0)), 'y': float(loc.attrib.get('y', 0)),
                    'shape': spr.attrib.get('id')
                })
        packages[pkg_name] = pins

    for comp in root.findall('.//ipc:Component', namespace):
        layer = comp.attrib.get('layerRef')
        pkg_name = comp.attrib.get('packageRef')
        if layer not in pads_by_layer or pkg_name not in packages: continue
            
        comp_loc = comp.find('ipc:Location', namespace)
        if comp_loc is None: continue
        cx, cy = float(comp_loc.attrib.get('x', 0)), float(comp_loc.attrib.get('y', 0))
        
        xform = comp.find('ipc:Xform', namespace)
        comp_rot = float(xform.attrib.get('rotation', 0)) if xform is not None else 0.0
        
        for pin in packages[pkg_name]:
            pad_cx, pad_cy = get_rotated_point(pin['x'], pin['y'], cx, cy, comp_rot)
            shape = shape_dict.get(pin['shape'])
            if shape:
                if shape['type'] == 'polygon':
                    poly = generate_rotated_polygon_pad(pad_cx, pad_cy, shape['points'], comp_rot)
                elif shape['type'] == 'circle':
                    poly = generate_circle_vertices(pad_cx, pad_cy, shape['diameter'], 32)
                pads_by_layer[layer].append({'Vertices_MM': poly, 'Timestamp': timestamp, 'Type': 'pad'})

    for ps in root.findall('.//ipc:PadStack', namespace):
        for lp in ps.findall('ipc:LayerPad', namespace):
            layer = lp.attrib.get('layerRef')
            if layer not in pads_by_layer: continue
                
            loc = lp.find('ipc:Location', namespace)
            spr = lp.find('ipc:StandardPrimitiveRef', namespace)
            if loc is not None and spr is not None:
                px, py = float(loc.attrib.get('x', 0)), float(loc.attrib.get('y', 0))
                shape = shape_dict.get(spr.attrib.get('id'))
                if shape:
                    if shape['type'] == 'polygon':
                        poly = generate_rotated_polygon_pad(px, py, shape['points'], 0) 
                    elif shape['type'] == 'circle':
                        poly = generate_circle_vertices(px, py, shape['diameter'], 32)
                    pads_by_layer[layer].append({'Vertices_MM': poly, 'Timestamp': timestamp, 'Type': 'pad'})

    # ==========================================
    # 3. DEDUPLICATE, EXTRACT TRACES & COMPILE
    # ==========================================
    layers_to_extract = ['Top Layer', 'PWR', 'GND', 'Bottom Layer']
    headers = ['Instance ID', 'Source Image Filename', 'Vertices', 'Timestamp', 'Type']
    
    for i, layer_name in enumerate(layers_to_extract):
        output_filename = f"l{i}.csv"
        img_filename = f"{layer_name}.png"
        
        # --- DEDUPLICATE PADS ---
        unique_pads = []
        seen_centroids = set()
        for pad in pads_by_layer[layer_name]:
            poly = pad['Vertices_MM']
            
            # Calculate the exact center point (centroid) of the pad
            cx = sum(p[0] for p in poly[:-1]) / (len(poly) - 1)
            cy = sum(p[1] for p in poly[:-1]) / (len(poly) - 1)
            
            # Round to 2 decimal places to catch identical pads placed by two different CAD systems
            centroid_sig = (round(cx, 2), round(cy, 2))
            
            if centroid_sig not in seen_centroids:
                seen_centroids.add(centroid_sig)
                unique_pads.append(pad)
                
        pads_by_layer[layer_name] = unique_pads
        # ------------------------
        
        layer_data = list(global_vias) + pads_by_layer[layer_name]
        
        raw_trace_polygons = []
        for feature in root.findall(f'.//ipc:LayerFeature[@layerRef="{layer_name}"]', namespace):
            for line in feature.findall('.//ipc:Line', namespace):
                try:
                    x1, y1 = float(line.attrib['startX']), float(line.attrib['startY'])
                    x2, y2 = float(line.attrib['endX']), float(line.attrib['endY'])
                    width = 0.1 
                    desc = line.find('ipc:LineDesc', namespace)
                    if desc is not None and 'lineWidth' in desc.attrib:
                        width = float(desc.attrib['lineWidth'])
                        
                    vertices = generate_line_polygon(x1, y1, x2, y2, width)
                    if vertices:
                        poly = Polygon(vertices)
                        if poly.is_valid: raw_trace_polygons.append(poly)
                except: continue

        trace_count = 0
        if raw_trace_polygons:
            merged_geometry = unary_union(raw_trace_polygons)
            geometries = []
            if isinstance(merged_geometry, Polygon): geometries.append(merged_geometry)
            elif isinstance(merged_geometry, MultiPolygon): geometries.extend(list(merged_geometry.geoms))
                
            for geom in geometries:
                # Get exterior coordinates
                coords = list(geom.exterior.coords)
                layer_data.append({'Vertices_MM': coords, 'Timestamp': timestamp, 'Type': 'trace'})
                trace_count += 1
        
        with open(output_filename, mode='w', newline='') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=headers)
            writer.writeheader()
            
            for idx, item in enumerate(layer_data):
                pixel_coords = mm_to_pixels(
                    item['Vertices_MM'], 
                    BOARD_WIDTH_MM, 
                    BOARD_HEIGHT_MM, 
                    IMG_WIDTH_PX, 
                    IMG_HEIGHT_PX
                )
                
                writer.writerow({
                    'Instance ID': idx,
                    'Source Image Filename': img_filename,
                    'Vertices': json.dumps([pixel_coords]),
                    'Timestamp': item['Timestamp'],
                    'Type': item['Type']
                })
                
        pad_count = len(pads_by_layer[layer_name])
        print(f"Generated {output_filename} ({layer_name}): {len(global_vias)} vias, {pad_count} pads, {trace_count} traces.")

if __name__ == "__main__":
    main()