"""Conservative reconstruction from immutable X-ray annotation CSVs.

Connectivity uses original area geometry, independently of rendering. This
exporter generates native KiCad track segments with local widths, custom pads,
and deduplicated vias. The result is an
annotation-based reconstruction, not a verified manufacturing design.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import uuid

import networkx as nx
from PIL import Image, ImageDraw
from shapely import make_valid
from shapely.affinity import scale
from shapely.geometry import LineString, Polygon, box
from shapely.ops import nearest_points, triangulate, unary_union
from shapely.strtree import STRtree


@dataclass
class Feature:
    layer: int
    row: int                 # zero-based data-row index; stable even if IDs repeat
    instance: str
    kind: str
    part: int
    geometry: Polygon

    @property
    def key(self):
        return (self.layer, self.row, self.part)

    @property
    def label(self):
        return f'L{self.layer}:{self.kind}:row{self.row}:part{self.part}'


def polygon_parts(geom):
    if geom.geom_type == 'Polygon':
        if not geom.is_empty and geom.area > 0:
            yield geom
    elif hasattr(geom, 'geoms'):
        for child in geom.geoms:
            yield from polygon_parts(child)


def parse_vertices(value, context, warnings):
    """Parse rings without joining unrelated contours or dropping minus signs.

    Nesting is interpreted by containment: outer, hole, island, etc. Disjoint
    contours remain separate. Degenerate points/lines are reported, not copper.
    """
    rings = json.loads(value)
    if not isinstance(rings, list) or not rings:
        raise ValueError(f'{context}: expected a nonempty contour list')
    if isinstance(rings[0], list) and len(rings[0]) == 2 and all(
            isinstance(x, (int, float)) for x in rings[0]):
        rings = [rings]
    area_rings = []
    for i, ring in enumerate(rings):
        if not isinstance(ring, list) or any(
                not isinstance(p, list) or len(p) != 2 or
                any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in p)
                for p in ring):
            raise ValueError(f'{context}: malformed contour {i}')
        if len(set(map(tuple, ring))) < 3:
            warnings.append(f'{context}: ignored degenerate contour {i} ({len(ring)} points)')
            continue
        poly = Polygon(ring)
        if not poly.is_valid:
            warnings.append(f'{context}: repaired invalid contour {i} using make_valid')
            poly = make_valid(poly)
        parts = list(polygon_parts(poly))
        if not parts:
            warnings.append(f'{context}: contour {i} contains no area')
        area_rings.extend(parts)
    # Containment parity preserves holes; do not assume every later ring is a hole.
    area_rings.sort(key=lambda p: (-p.area, p.bounds))
    depths = [sum(q.covers(p) and q.area > p.area for q in area_rings[:i])
              for i, p in enumerate(area_rings)]
    result = Polygon()
    for depth in sorted(set(depths)):
        level = unary_union([p for p, d in zip(area_rings, depths) if d == depth])
        result = result.union(level) if depth % 2 == 0 else result.difference(level)
    return sorted(polygon_parts(result), key=lambda p: (p.bounds, p.area))


def load_inputs(directory, layer_count):
    directory = Path(directory)
    if layer_count < 2 or layer_count > 32 or layer_count % 2:
        raise ValueError('Use an even copper layer count from 2 to 32')
    layers, warnings, manifest, image_size = [], [], {}, None
    for li in range(layer_count):
        image_path = directory / f'l{li}.png'
        if not image_path.exists():
            image_path = directory / f'l{li}.jpg'
        csv_path = directory / f'l{li}.csv'
        for path in (image_path, csv_path):
            manifest[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(image_path) as image:
            image.load()  # Fail early for corrupt images; never invent a blank image.
            if image_size is None:
                image_size = image.size
            elif image.size != image_size:
                raise ValueError(f'{image_path}: image dimensions differ; registration is required')
        features = []
        with csv_path.open(newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if not {'Type', 'Vertices'}.issubset(reader.fieldnames or []):
                raise ValueError(f'{csv_path}: missing Type or Vertices column')
            for row_idx, row in enumerate(reader):
                kind = row['Type'].strip().lower()
                context = f'L{li} row {row_idx} ID {row.get("Instance ID", row_idx)}'
                if kind not in {'pad', 'via', 'trace', 'plane', 'zone'}:
                    raise ValueError(f'{context}: unrecognized Type {kind!r}')
                for pi, geom in enumerate(parse_vertices(row['Vertices'], context, warnings)):
                    if not box(0, 0, *image_size).covers(geom):
                        warnings.append(f'{context}: geometry extends outside the image')
                    features.append(Feature(li, row_idx, row.get('Instance ID', str(row_idx)), kind, pi, geom))
        if not any(f.kind in {'trace', 'plane', 'zone'} for f in features):
            warnings.append(f'L{li}: CSV has no trace/plane area; image copper is NOT inferred')
        layers.append(features)
    return layers, image_size, warnings, manifest


def match_vias(layers, tolerance_px, warnings):
    """Group aligned via observations conservatively, across any layer pair.

    One observation per layer, similar diameter, and every pair in a group must
    match. Ambiguous matches are left separate and reported. This assumes that
    matched annotations identify the same plated barrel, not arbitrary pads.
    """
    groups = []
    for feature in sorted((f for layer in layers for f in layer if f.kind == 'via'), key=lambda f: f.key):
        candidates = []
        for group in groups:
            if feature.layer in {m.layer for m in group}:
                continue
            if all(feature.geometry.centroid.distance(m.geometry.centroid) <= tolerance_px and
                   abs(math.sqrt(feature.geometry.area / m.geometry.area) - 1) <= 0.25
                   for m in group):
                candidates.append(group)
        if len(candidates) == 1:
            candidates[0].append(feature)
        else:
            if len(candidates) > 1:
                warnings.append(f'{feature.label}: ambiguous via match, kept separate')
            groups.append([feature])
    for group in groups:
        if len(group) < len(layers):
            warnings.append(f'{group[0].label}: via appears on {len(group)}/{len(layers)} layers; no full-stack via exported')
    return groups


def build_connectivity(layers, via_groups, contact_tolerance_px=0.0, near_gap_px=2.0):
    """Connect ALL touching copper objects on the SAME layer, then via barrels.

    A pad -> trace A -> trace B -> via -> trace C -> pad chain is one connected
    component. Artwork processing and skeleton failures cannot remove nodes.
    """
    if contact_tolerance_px < 0 or near_gap_px < contact_tolerance_px:
        raise ValueError('Require 0 <= contact tolerance <= near-gap reporting distance')
    graph = nx.Graph()
    contacts, near_gaps = [], []
    for layer in layers:
        graph.add_nodes_from(f.label for f in layer)
        if not layer:
            continue
        geoms = [f.geometry for f in layer]
        tree = STRtree(geoms)
        for i, f in enumerate(layer):
            query = f.geometry.envelope.buffer(near_gap_px)
            for j in sorted(int(j) for j in tree.query(query)):
                if j <= i:
                    continue
                g = layer[j]
                gap = f.geometry.distance(g.geometry)
                if gap <= contact_tolerance_px:
                    graph.add_edge(f.label, g.label, reason='copper contact', gap_px=gap)
                    contacts.append({'a': f.label, 'b': g.label, 'gap_px': gap,
                                     'assumed_gap_connection': gap > 0})
                elif gap <= near_gap_px:
                    near_gaps.append({'a': f.label, 'b': g.label, 'gap_px': gap})
    for group in via_groups:
        for feature in group[1:]:
            graph.add_edge(group[0].label, feature.label, reason='matched via barrel')
    features = {f.label: f for layer in layers for f in layer}
    components = sorted((sorted(c, key=lambda n: features[n].key)
                         for c in nx.connected_components(graph)),
                        key=lambda c: features[c[0]].key)
    net_map = {node: net for net, comp in enumerate(components, 1) for node in comp}
    return graph, components, net_map, contacts, near_gaps


def netlist_text(layers, via_groups, components):
    features = {f.label: f for layer in layers for f in layer}
    via_map = {f.label: f'V{i:03d}' for i, group in enumerate(via_groups, 1) for f in group}
    lines = ['ANNOTATION CONNECTIVITY — coordinate terminals, not component pin identities',
             'Strict polygon contacts unless a nonzero contact tolerance was requested.',
             'Missing plane annotations and unresolved gaps can split a physical net.', '']
    for ni, comp in enumerate(components, 1):
        lines.append(f'Net {ni} (Net-{ni}):')
        seen_vias, terminal_count = set(), 0
        for node in comp:
            f = features[node]
            x, y = f.geometry.centroid.coords[0]
            if f.kind == 'via':
                identity = via_map[node]
                if identity in seen_vias:
                    continue
                seen_vias.add(identity)
                ls = sorted(features[n].layer for n in comp if via_map.get(n) == identity)
                lines.append(f'  Via {identity} @ ({x:.3f}, {y:.3f}) px; layers {ls}')
                terminal_count += 1
            elif f.kind == 'pad':
                lines.append(f'  Pad {node} (Instance ID {f.instance}) @ ({x:.3f}, {y:.3f}) px')
                terminal_count += 1
        area_nodes = [n for n in comp if features[n].kind not in {'pad', 'via'}]
        lines.append('  Copper: ' + (', '.join(area_nodes) or '(none annotated)'))
        if terminal_count < 2:
            lines.append(f'  Status: {terminal_count} annotated terminal(s); retained for review')
        lines.append('')
    return '\n'.join(lines)


def layer_name(index, count):
    return 'F.Cu' if index == 0 else 'B.Cu' if index == count-1 else f'In{index}.Cu'


def hole_free_parts(poly):
    """Decompose polygons with holes for formats with additive polygon primitives."""
    if not poly.interiors:
        return [poly]
    parts = [p for triangle in triangulate(poly) for p in polygon_parts(triangle.intersection(poly))]
    if any(p.interiors for p in parts):
        raise ValueError('Hole decomposition failed; refusing to fill a clearance hole')
    return parts


def export_kicad(path, layers, via_groups, net_map, image_size, width_mm, height_mm, warnings, drill_ratio=0.6, contacts=(), track_diagnostics=None):
    """Native tracks, custom pads and vias, using KiCad 20221018 file syntax.

    Drill sizes are explicit estimates, because the CSV has no drill metadata.
    No unknown inner plane is invented. The rectangle is the calibrated image
    extent, not a measured physical Edge.Cuts outline.
    """
    if width_mm <= 0 or height_mm <= 0 or not (0 < drill_ratio < 1):
        raise ValueError('Positive dimensions and 0 < drill ratio < 1 are required')
    sx, sy = width_mm/image_size[0], height_mm/image_size[1]
    count = len(layers)
    def uid(label):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, 'xray-reconstruction/' + label))
    def pts(poly, offset=(0, 0)):
        return ' '.join(f'(xy {x-offset[0]:.6f} {y-offset[1]:.6f})' for x,y in list(poly.exterior.coords)[:-1])
    def mmgeom(poly):
        from shapely.affinity import translate
        return translate(scale(poly, sx, sy, origin=(0,0)), 12, 12)
    from trace_tracks import reconstruct_tracks
    tracks,track_features = reconstruct_tracks(layers,contacts,via_groups,net_map)
    features_by_label = {f.label:f for layer in layers for f in layer}
    exported_segments = []
    out = ['(kicad_pcb (version 20221018) (generator xray_reconstruction_review)',
           '  (general (thickness 1.6))', '  (paper "A4")', '  (layers', '    (0 "F.Cu" signal)']
    out.extend(f'    ({li} "In{li}.Cu" signal)' for li in range(1,count-1))
    out.extend(['    (31 "B.Cu" signal)', '    (44 "Edge.Cuts" user)',
                '    (32 "B.Adhes" user "B.Adhesive")', '    (33 "F.Adhes" user "F.Adhesive")',
                '    (34 "B.Paste" user)', '    (35 "F.Paste" user)',
                '    (38 "B.Mask" user)', '    (39 "F.Mask" user)', '  )',
                '  (setup (pad_to_mask_clearance 0))', '  (net 0 "")'])
    out.extend(f'  (net {n} "Net-{n}")' for n in sorted(set(net_map.values())))
    out.append(f'  (gr_rect (start 12 12) (end {12+width_mm:.6f} {12+height_mm:.6f}) '
               f'(stroke (width 0.1) (type solid)) (layer "Edge.Cuts") (tstamp {uid("image-extent")}))')
    exported_vias = set()
    physical_vias = 0
    for gi, group in enumerate(via_groups,1):
        if {f.layer for f in group} != set(range(count)):
            continue  # partial observations are exported below as per-layer copper
        f = group[0]
        # Inscribed diameter avoids widening the annotated circular area.
        diameters = [2*m.geometry.centroid.distance(m.geometry.boundary)*min(sx,sy) for m in group]
        diameter = min(diameters)
        if diameter <= 0:
            warnings.append(f'{f.label}: no positive via diameter; exported as layer copper')
            continue
        cx,cy = f.geometry.centroid.coords[0]
        net = net_map[f.label]
        out.append(f'  (via (at {12+cx*sx:.6f} {12+cy*sy:.6f}) (size {diameter:.6f}) '
                   f'(drill {diameter*drill_ratio:.6f}) (layers "F.Cu" "B.Cu") '
                   f'(net {net}) (tstamp {uid("via-"+str(gi))}))')
        exported_vias.update(m.label for m in group)
        physical_vias += 1
    for layer in layers:
        for f in layer:
            copper = layer_name(f.layer,count)
            geom = mmgeom(f.geometry)
            net = net_map[f.label]
            if f.kind == 'trace' or f.label in exported_vias:
                continue  # real track/via objects, never duplicate copper zones
            if f.kind == 'pad' and f.layer in {0,count-1}:
                anchor = geom.representative_point()
                size = min(0.01,anchor.distance(geom.boundary))
                if size <= 0:
                    raise ValueError(f'{f.label}: cannot place an interior pad anchor')
                side = 'F' if f.layer == 0 else 'B'
                out.append(f'  (footprint "Annotation_{f.label.replace(":", "_")}" (layer "{copper}") '
                           f'(at {anchor.x:.6f} {anchor.y:.6f}) (attr smd) (tstamp {uid(f.label+"-fp")})')
                out.append(f'    (pad "1" smd custom (at 0 0) (size {size:.6f} {size:.6f}) '
                           f'(layers "{copper}" "{side}.Paste" "{side}.Mask") (net {net} "Net-{net}") '
                           f'(tstamp {uid(f.label+"-pad")}) (options (clearance outline) (anchor circle)) (primitives')
                for part in hole_free_parts(geom):
                    out.append(f'      (gr_poly (pts {pts(part,(anchor.x,anchor.y))}) (width 0) (fill yes))')
                out.extend(['    ))','  )'])
            else:
                # Explicit plane/zone annotations (or an unmatched partial via)
                # remain areas. Trace annotations never take this branch.
                for pi,part in enumerate(hole_free_parts(geom)):
                    out.append(f'  (zone (net {net}) (net_name "Net-{net}") (layer "{copper}") '
                               f'(tstamp {uid(f.label+"-zone-"+str(pi))}) (name "{f.label}") '
                               '(hatch edge 0.5) (connect_pads yes (clearance 0)) (min_thickness 0.001) '
                               '(filled_areas_thickness no) (fill yes (thermal_gap 0.1) '
                               '(thermal_bridge_width 0.1) (island_removal_mode 1))')
                    out.extend([f'    (polygon (pts {pts(part)}))',
                                f'    (filled_polygon (layer "{copper}") (pts {pts(part)}))', '  )'])
    for ti,track in enumerate(tracks):
        start = (12+track['start'][0]*sx,12+track['start'][1]*sy)
        end = (12+track['end'][0]*sx,12+track['end'][1]*sy)
        width = track['width_px']*min(sx,sy)
        if track['kind']=='trace':
            source_poly=mmgeom(features_by_label[track['source']].geometry)
            clearance=LineString([start,end]).distance(source_poly.boundary)
            width=max(0.4*min(sx,sy),2*clearance-0.000002)
        segment_id=uid('track-'+str(ti))
        out.append(f'  (segment (start {start[0]:.6f} {start[1]:.6f}) '
                   f'(end {end[0]:.6f} {end[1]:.6f}) '
                   f'(width {width:.6f}) (layer "{layer_name(track["layer"],count)}") '
                   f'(net {track["net"]}) (tstamp {segment_id}))')
        exported_segments.append(dict(uuid=segment_id,source=track['source'],kind=track['kind'],
            layer=track['layer'],net=track['net'],start_mm=start,end_mm=end,width_mm=width))
    out.append(')')
    Path(path).write_text('\n'.join(out)+'\n',encoding='utf-8')
    if track_diagnostics is not None:
        track_diagnostics.update(track_features=track_features,exported_segments=exported_segments)
    return len(exported_vias), physical_vias


def export_overlays(directory, source, layers):
    for li, layer in enumerate(layers):
        image_path = Path(source)/f'l{li}.png'
        if not image_path.exists():
            image_path = Path(source)/f'l{li}.jpg'
        with Image.open(image_path) as source_image:
            image = source_image.convert('RGB')
        draw = ImageDraw.Draw(image)
        for f in layer:
            color = {'via':'#39bfff','pad':'#ffb84d'}.get(f.kind,'#55ff7e')
            for ring in [f.geometry.exterior,*f.geometry.interiors]:
                draw.line(list(ring.coords),fill=color,width=2)
        image.save(Path(directory)/f'overlay_l{li}.png')


def run(args):
    source, output = Path(args.input_dir).resolve(), Path(args.output_dir).resolve()
    if source == output or source in output.parents:
        raise ValueError('Choose an output directory outside the immutable input directory')
    layers,size,warnings,manifest = load_inputs(source,args.layers)
    groups = match_vias(layers,args.via_match_px,warnings)
    graph,components,net_map,contacts,gaps = build_connectivity(layers,groups,args.contact_tolerance_px,args.near_gap_px)
    output.mkdir(parents=True,exist_ok=True)
    warnings.extend([
        'Netlist describes annotated copper only; PNG plane copper is not inferred.',
        'Matched via observations are assumed to be the same plated barrel.',
        f'KiCad drill diameters are estimates ({args.drill_ratio:g} x observed diameter).',
        'Board outline is the image extent. Confirm physical dimensions and outline.',
        'CSV pads have no component reference or pin number: terminal labels use source rows.',
    ])
    track_diagnostics={}
    print('Generating native KiCad tracks and pad/via connections...',flush=True)
    export_kicad(output/'reviewed_tracks.kicad_pcb',layers,groups,net_map,size,args.width_mm,args.height_mm,
                 warnings,args.drill_ratio,contacts,track_diagnostics)
    (output/'reviewed_netlist.txt').write_text(netlist_text(layers,groups,components),encoding='utf-8')
    report = dict(image_size=size, width_mm=args.width_mm, height_mm=args.height_mm,
                  contact_tolerance_px=args.contact_tolerance_px, via_match_px=args.via_match_px,
                  feature_counts=[{kind:sum(f.kind==kind for f in layer) for kind in sorted({f.kind for f in layer})} for layer in layers],
                  nodes=graph.number_of_nodes(),edges=graph.number_of_edges(),nets=len(components),
                  via_groups=len(groups),inferred_stitches=sum(c['assumed_gap_connection'] for c in contacts),
                  contacts=contacts,near_gaps=gaps,warnings=warnings,
                  nets_to_features={f'Net-{i}':c for i,c in enumerate(components,1)},
                  input_sha256=manifest,**track_diagnostics)
    (output/'review_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    export_overlays(output,source,layers)
    # Verify source files were not changed, including by an unrelated process during the run.
    for name,digest in manifest.items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'Input changed during reconstruction: {name}')
    print(f'{graph.number_of_nodes()} copper observations, {len(groups)} via groups, {len(components)} candidate nets')
    print(f'{len(track_diagnostics["track_features"])} trace shapes converted to '
          f'{len(track_diagnostics["exported_segments"])} editable track segments (including contact connections).')
    print(f'{len(gaps)} unresolved near contacts; {len(warnings)} warnings. See review_report.json.')
    print(f'Output: {output}')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--layers',type=int,required=True)
    parser.add_argument('--width-mm',type=float,required=True)
    parser.add_argument('--height-mm',type=float,required=True)
    parser.add_argument('--via-match-px',type=float,default=3.0)
    parser.add_argument('--contact-tolerance-px',type=float,default=1.0,
                        help='1 px matches adjacent annotation boundaries in these inputs; use 0 for strict contacts')
    parser.add_argument('--near-gap-px',type=float,default=2.0)
    parser.add_argument('--drill-ratio',type=float,default=0.6)
    args=parser.parse_args()
    if args.via_match_px < 0:
        parser.error('--via-match-px must be nonnegative')
    run(args)


if __name__=='__main__':
    main()
