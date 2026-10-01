"""Convert annotated copper polygons to native, editable KiCad track segments.

The boundary Voronoi graph supplies a medial axis. Short unconnected corner
spokes can be pruned, but contact anchors, branches, loops and a central core
are retained. Widths are limited by the polygon along each entire segment.
"""
import math

import networkx as nx
from shapely.geometry import LineString, MultiPoint, Point
from shapely.ops import nearest_points, unary_union, voronoi_diagram


def node_key(point):
    return tuple(round(float(v), 8) for v in point)


def _medial_graph_at_spacing(polygon, spacing):
    samples = set()
    for ring in [polygon.exterior, *polygon.interiors]:
        n = max(8, math.ceil(ring.length/spacing))
        samples.update(node_key(ring.interpolate(i*ring.length/n).coords[0]) for i in range(n))
    diagram = voronoi_diagram(MultiPoint(sorted(samples)), edges=True)
    graph = nx.Graph()
    allowed = polygon.buffer(1e-7)
    def add_lines(geom):
        if geom.geom_type == 'LineString':
            for a,b in zip(geom.coords, list(geom.coords)[1:]):
                a,b = node_key(a),node_key(b)
                line = LineString([a,b])
                if a != b and allowed.covers(line):
                    graph.add_edge(a,b,length=line.length)
        elif hasattr(geom,'geoms'):
            for part in geom.geoms:
                add_lines(part)
    add_lines(diagram)
    if not graph:
        # Very small shapes still become a finite native track, not a dropped row.
        p = polygon.representative_point()
        radius = p.distance(polygon.boundary)
        if radius <= 0:
            raise ValueError('Cannot construct a track inside a zero-width polygon')
        a,b = (p.x-radius/4,p.y),(p.x+radius/4,p.y)
        graph.add_edge(node_key(a),node_key(b),length=radius/2)
    return graph


def medial_graph(polygon, spacing=2.0):
    """Retry finer boundary sampling when coarse Voronoi edges disconnect.

    Each retry is computed from the same unmodified polygon. We never discard a
    component or bridge through a clearance gap just to make a graph connected.
    """
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError('Boundary sampling spacing must be positive and finite')
    for attempt in range(4):
        current_spacing=spacing/(2**attempt)
        graph=_medial_graph_at_spacing(polygon,current_spacing)
        if nx.is_connected(graph):
            graph.graph.update(sampling_spacing_px=current_spacing,sampling_attempts=attempt+1)
            return graph
    raise ValueError(f'Medial graph remains disconnected after 4 sampling attempts '
                     f'(down to {current_spacing:g} px); no copper was silently discarded')


def attach_anchor(graph, position, polygon):
    """Insert the closest visible projection on an edge, then the contact point."""
    anchor = node_key(position)
    if anchor in graph:
        return anchor
    target = Point(anchor)
    allowed = polygon.buffer(1e-6)
    candidates = []
    for a,b in graph.edges:
        edge = LineString([a,b])
        projection = node_key(edge.interpolate(edge.project(target)).coords[0])
        line = LineString([anchor,projection])
        candidates.append((line.length,a,b,projection,line))
    for _,a,b,projection,line in sorted(candidates):
        if not allowed.covers(line):
            continue
        if projection not in (a,b):
            graph.remove_edge(a,b)
            graph.add_edge(a,projection,length=math.dist(a,projection))
            graph.add_edge(projection,b,length=math.dist(projection,b))
        if anchor != projection:
            graph.add_edge(projection,anchor,length=line.length)
        return anchor
    raise ValueError(f'Cannot attach contact {anchor} without crossing outside its copper polygon')


def prune_corner_spokes(graph, polygon, protected):
    """Remove short corner artifacts, never contact paths or the central core."""
    graph = graph.copy()
    protected = set(protected)
    # A longest-distance approximation protects a core even for small rectangles.
    seed = max(graph, key=lambda n: Point(n).distance(polygon.boundary))
    lengths = nx.single_source_dijkstra_path_length(graph,seed,weight='length')
    far = max(lengths,key=lengths.get)
    lengths,paths = nx.single_source_dijkstra(graph,far,weight='length')
    other = max(lengths,key=lengths.get)
    core_path = paths[other]
    # Preserve the interior core; terminal corner spokes can still be trimmed.
    internal = [n for n in core_path if graph.degree(n) != 1]
    if internal:
        center = max(internal,key=lambda n: Point(n).distance(polygon.boundary))
        protected.add(center)
    else:
        protected.update(core_path)
    while True:
        removals = []
        for leaf in sorted(n for n in graph if graph.degree(n)==1 and n not in protected):
            path = [leaf]
            previous,current = None,leaf
            length = 0.0
            while True:
                neighbors = [n for n in graph[current] if n != previous]
                if not neighbors:
                    break
                nxt = neighbors[0]
                length += graph[current][nxt]['length']
                path.append(nxt)
                previous,current = current,nxt
                if current in protected or graph.degree(current) != 2:
                    break
            # Once a graph has only one path left, its endpoints are useful.
            if graph.degree(current) < 3 or any(n in protected for n in path[:-1]):
                continue
            radius = Point(current).distance(polygon.boundary)
            if length <= max(2.0,1.65*radius):
                removals.extend(path[:-1])
        if not removals:
            break
        # Keep at least one finite edge, even if every spoke meets at one node.
        surviving = set(graph)-set(removals)
        if graph.subgraph(surviving).number_of_edges()==0:
            break
        graph.remove_nodes_from(removals)
    return graph


def graph_paths(graph, anchors):
    """Degree-two chains with shared endpoints; closed cycles are also emitted."""
    anchors = set(anchors)
    visited = set()
    paths = []
    stops = {n for n in graph if graph.degree(n)!=2 or n in anchors}
    def walk(start,nxt):
        path = [start,nxt]
        visited.add(frozenset((start,nxt)))
        prev,current = start,nxt
        while current not in stops and current != start:
            options = [n for n in graph[current] if n!=prev]
            if not options:
                break
            nxt = options[0]
            edge = frozenset((current,nxt))
            if edge in visited:
                break
            visited.add(edge)
            path.append(nxt)
            prev,current = current,nxt
        paths.append(path)
    for start in sorted(stops):
        for nxt in sorted(graph[start]):
            if frozenset((start,nxt)) not in visited:
                walk(start,nxt)
    for a,b in sorted(graph.edges):
        if frozenset((a,b)) not in visited:
            walk(a,b)
    return paths


def path_segments(path, polygon, tolerance=0.65):
    """Simplify a chain while bounding lateral error, clearance and width change."""
    if len(path)<2:
        return []
    radii = [Point(p).distance(polygon.boundary) for p in path]
    segments = []
    allowed = polygon.buffer(1e-6)
    def recurse(lo,hi):
        a,b = path[lo],path[hi]
        line = LineString([a,b])
        if a==b:
            middle=(lo+hi)//2
            recurse(lo,middle)
            recurse(middle,hi)
            return
        errors=[Point(path[i]).distance(line) for i in range(lo,hi+1)]
        rmin,rmax=min(radii[lo:hi+1]),max(radii[lo:hi+1])
        # Geometric safety takes precedence over simplifying a concave turn.
        split = (not allowed.covers(line) or max(errors)>tolerance or
                 rmax-rmin>max(0.75,0.18*rmax))
        if hi-lo>1 and split:
            offset=max(range(1,hi-lo),key=lambda i: errors[i]) if max(errors)>tolerance else (hi-lo)//2
            middle=lo+offset
            recurse(lo,middle)
            recurse(middle,hi)
            return
        radius = line.distance(polygon.boundary)
        # A small width is required at an exact boundary anchor; cap overlap
        # makes the resulting native track electrically touch its target.
        segments.append({'start':a,'end':b,'width_px':max(0.4,2*radius)})
    recurse(0,len(path)-1)
    return segments


def polygon_tracks(polygon, anchors=(), diagnostics=None):
    graph = medial_graph(polygon)
    if diagnostics is not None:
        diagnostics.update(sampling_spacing_px=graph.graph['sampling_spacing_px'],
                           sampling_attempts=graph.graph['sampling_attempts'])
    protected = [attach_anchor(graph,p,polygon) for p in anchors]
    graph = prune_corner_spokes(graph,polygon,protected)
    segments = [s for path in graph_paths(graph,protected) for s in path_segments(path,polygon)]
    if not segments:
        raise ValueError('No track segments generated; source feature was not silently dropped')
    return segments


def reconstruct_tracks(layers, contacts, via_groups, net_map):
    """Create per-feature routes plus explicit connections to real pads/vias."""
    features={f.label:f for layer in layers for f in layer}
    trace_features=[f for layer in layers for f in layer if f.kind=='trace']
    anchors={f.label:[] for f in trace_features}
    # Use the same centre as the actual, deduplicated via object in the exporter.
    via_centers={f.label:group[0].geometry.centroid.coords[0] for group in via_groups for f in group}
    joins=[]
    for ci,contact in enumerate(contacts):
        a,b=features[contact['a']],features[contact['b']]
        pa,pb=nearest_points(a.geometry,b.geometry)
        pa,pb=pa.coords[0],pb.coords[0]
        if a.kind=='trace':
            anchors[a.label].append(pa)
        if b.kind=='trace':
            anchors[b.label].append(pb)
        start=via_centers.get(a.label,pa)
        end=via_centers.get(b.label,pb)
        if math.dist(start,end)>1e-7:
            support=unary_union([a.geometry,b.geometry,LineString([pa,pb]).buffer(0.3)])
            line=LineString([start,end])
            width=max(0.4,min(2.0,2*line.distance(support.boundary)))
            joins.append(dict(start=start,end=end,width_px=width,layer=a.layer,
                              net=net_map[a.label],source=f'contact-{ci}',kind='contact'))
    tracks=[]
    report=[]
    for f in trace_features:
        sampling={}
        try:
            segments=polygon_tracks(f.geometry,anchors[f.label],sampling)
        except Exception as error:
            raise ValueError(f'{f.label}: track reconstruction failed: {error}') from error
        for s in segments:
            tracks.append(dict(**s,layer=f.layer,net=net_map[f.label],source=f.label,kind='trace'))
        shape=unary_union([LineString([s['start'],s['end']]).buffer(s['width_px']/2) for s in segments])
        report.append(dict(label=f.label,instance=f.instance,layer=f.layer,segment_count=len(segments),
                           contact_anchors=len(anchors[f.label]),
                           source_area_coverage=shape.intersection(f.geometry).area/f.geometry.area,
                           outside_source_area=shape.difference(f.geometry).area,
                           source_area=f.geometry.area,**sampling))
    return tracks+joins,report
