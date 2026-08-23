#!/usr/bin/env python3
"""Auxiliary receiver power/return/RF audit; never replaces native KiCad gates."""
from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

KICAD_BIN = Path(r"D:\Temp\KiCad10\bin")
KICAD_SITE = KICAD_BIN / "Lib" / "site-packages"
TARGET_WIDTH_MM = {"USB_VBUS_RAW": .80, "USB_VBUS_5V": .80, "SPK_PLUS": .60,
                   "SPK_MINUS": .60, "3V3": .50, "BUCK_SW": .50}
FINE_REFS = {"J1", "U1", "U2", "U3", "U4"}
KELVIN_SENSE_PADS = {("3V3", "U2", "6")}
MAX_NECK_CHAIN_MM = 1.00
MIN_COPPER_TO_EDGE_MM = .30
MIN_SPK_GAP = .20
MAX_SPK_RATIO = 1.15
# u-blox UBX-17056748 R15 §3.3.3: NINA-B302 metal PIFA requires full
# ground below the whole module, including antenna; B3x6 alone uses cutout.
NINA_ANTENNA_SECTION_MM = 3.4
NINA_NEIGHBOR_MM = 10.0
NINA_CASING_MM = 5.0
NINA_GND_STEP = .5
NINA_MIN_GND_COVERAGE = .98
NOISY_RE = re.compile(r"(?:BUCK_SW|USB_D|CLK|SCK|BCLK|LRCLK|QSPI)", re.I)
HIGH_REF_RE = re.compile(r"^(?:J|L|SW|M|H)", re.I)
HIGH_VALUE_RE = re.compile(r"(?:metal|shield|connector|inductor)", re.I)

class UnionFind:
    def __init__(self): self.parent, self.rank = {}, {}
    def add(self, x):
        if x not in self.parent: self.parent[x], self.rank[x] = x, 0
    def find(self, x):
        if self.parent[x] != x: self.parent[x] = self.find(self.parent[x])
        return self.parent[x]
    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a == b: return a
        if self.rank[a] < self.rank[b] or (self.rank[a] == self.rank[b] and a > b): a, b = b, a
        self.parent[b] = a
        if self.rank[a] == self.rank[b]: self.rank[a] += 1
        return a

def mm(pcbnew, value): return float(pcbnew.ToMM(value))
def point_key(p): return int(p.x), int(p.y)
def point_mm(pcbnew, p): return [round(mm(pcbnew, p.x), 6), round(mm(pcbnew, p.y), 6)]
def bbox_mm(pcbnew, b):
    x, y = mm(pcbnew, b.GetX()), mm(pcbnew, b.GetY())
    return x, y, x + mm(pcbnew, b.GetWidth()), y + mm(pcbnew, b.GetHeight())
def bbox_json(b): return [round(v, 6) for v in b]
def bbox_union(boxes):
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)
def bbox_distance(a, b):
    return math.hypot(max(a[0]-b[2], b[0]-a[2], 0), max(a[1]-b[3], b[1]-a[3], 0))
def bbox_to_rect_edge_clearance(a, b):
    return min(a[0]-b[0], b[2]-a[2], a[1]-b[1], b[3]-a[3])
def edge_extents(board, pcbnew):
    xs,ys=[],[]
    for item in board.GetDrawings():
        if item.GetLayer()!=pcbnew.Edge_Cuts: continue
        for getter in ("GetStart","GetEnd"):
            if hasattr(item,getter):
                point=getattr(item,getter)(); xs.append(mm(pcbnew,point.x)); ys.append(mm(pcbnew,point.y))
    if not xs: raise RuntimeError("no Edge.Cuts endpoints")
    return min(xs),min(ys),max(xs),max(ys)

def neck_threshold_applies(net,ref,pad):
    return (net,ref,pad) not in KELVIN_SENSE_PADS

def orient(a, b, c, eps=1e-9):
    v = (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
    return 1 if v > eps else -1 if v < -eps else 0
def on_segment(a, b, p, eps=1e-9):
    return orient(a,b,p,eps) == 0 and min(a[0],b[0])-eps <= p[0] <= max(a[0],b[0])+eps and min(a[1],b[1])-eps <= p[1] <= max(a[1],b[1])+eps
def segments_intersect(a,b,c,d):
    o1,o2,o3,o4 = orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b)
    return (o1 != o2 and o3 != o4) or (o1 == 0 and on_segment(a,b,c)) or (o2 == 0 and on_segment(a,b,d)) or (o3 == 0 and on_segment(c,d,a)) or (o4 == 0 and on_segment(c,d,b))
def point_segment_distance(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    if dx == 0 and dy == 0: return math.hypot(p[0]-a[0],p[1]-a[1])
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(p[0]-(a[0]+t*dx),p[1]-(a[1]+t*dy))
def segment_distance(a,b,c,d):
    if segments_intersect(a,b,c,d): return 0.0
    return min(point_segment_distance(a,c,d),point_segment_distance(b,c,d),point_segment_distance(c,a,b),point_segment_distance(d,a,b))
def analyze_speaker_geometry(plus, minus):
    gaps,crossings=[],[]
    for i,p in enumerate(plus):
        for j,m in enumerate(minus):
            if segments_intersect(p["start"],p["end"],m["start"],m["end"]): crossings.append([i,j])
            gaps.append(segment_distance(p["start"],p["end"],m["start"],m["end"]) - (p["width_mm"]+m["width_mm"])/2)
    return {"minimum_copper_gap_mm":round(min(gaps),6) if gaps else None,"crossing_count":len(crossings),"crossing_segment_pairs":crossings}

def shortest_neck_distances(edges, seeds, targets):
    adj=defaultdict(list)
    for a,b,w in edges: adj[a].append((b,w)); adj[b].append((a,w))
    dist={}; q=[]; serial=0
    for s in seeds: dist[s]=0.; heapq.heappush(q,(0.,serial,s)); serial+=1
    while q:
        d,_,n=heapq.heappop(q)
        if d > dist.get(n,math.inf)+1e-12: continue
        for nxt,w in adj.get(n,[]):
            nd=d+w
            if nd+1e-12 < dist.get(nxt,math.inf): dist[nxt]=nd; heapq.heappush(q,(nd,serial,nxt)); serial+=1
    return {label:min((dist[x] for x in nodes if x in dist),default=None) for label,nodes in targets.items()}

def connected_wide_ratio(segments, main_root, target):
    yes=[x for x in segments if x["root"]==main_root]; no=[x for x in segments if x["root"]!=main_root]
    total=sum(x["length_mm"] for x in yes); wide=sum(x["length_mm"] for x in yes if x["width_mm"]+1e-9>=target)
    return {"basis":"largest-pad-component track length only","all_segment_count":len(segments),"all_total_length_mm":round(sum(x["length_mm"] for x in segments),6),"connected_segment_count":len(yes),"connected_total_length_mm":round(total,6),"connected_wide_length_mm":round(wide,6),"disconnected_segment_count":len(no),"disconnected_length_mm":round(sum(x["length_mm"] for x in no),6),"wide_ratio":round(wide/total,6) if total else 0.}

def zone_island_shape(pcbnew, polys, i):
    shape=pcbnew.SHAPE_POLY_SET(); out=shape.AddOutline(polys.COutline(i))
    for h in range(polys.HoleCount(i)): shape.AddHole(polys.CHole(i,h),out)
    return shape
def collide_nodes(a,b,clearance):
    return any(a["shapes"][layer].Collide(b["shapes"][layer],clearance) for layer in set(a["shapes"]) & set(b["shapes"]))

def build_copper_graph(board, pcbnew, target_nets):
    enabled=list(board.GetEnabledLayers().CuStack()); enabled_set=set(enabled)
    uf=UnionFind(); nodes={}; by_net=defaultdict(list)
    def add(net,kind,shapes,**meta):
        i=len(nodes); uf.add(i); nodes[i]={"id":i,"net":net,"kind":kind,"shapes":shapes,**meta}; by_net[net].append(i); return i
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            net=pad.GetNetname()
            if net not in target_nets: continue
            shapes={layer:pad.GetEffectiveShape(layer) for layer in enabled if pad.FlashLayer(layer)}
            if shapes: add(net,"pad",shapes,ref=fp.GetReference(),pad=str(pad.GetNumber()),item=pad)
    for item in board.GetTracks():
        net=item.GetNetname()
        if net not in target_nets: continue
        if isinstance(item,pcbnew.PCB_VIA):
            shapes={layer:item.GetEffectiveShape(layer) for layer in enabled if item.FlashLayer(layer)}
            add(net,"via",shapes,item=item,position=item.GetPosition(),at_mm=point_mm(pcbnew,item.GetPosition()),diameter_mm=round(mm(pcbnew,item.GetWidth(pcbnew.F_Cu)),6),drill_mm=round(mm(pcbnew,item.GetDrillValue()),6))
        else:
            layer=item.GetLayer(); add(net,"track",{layer:item.GetEffectiveShape()},item=item,layer=layer,layer_name=pcbnew.LayerName(layer),start=item.GetStart(),end=item.GetEnd(),start_mm=point_mm(pcbnew,item.GetStart()),end_mm=point_mm(pcbnew,item.GetEnd()),width_mm=round(mm(pcbnew,item.GetWidth()),6),length_mm=round(mm(pcbnew,item.GetLength()),6))
    for zi,zone in enumerate(board.Zones()):
        net=zone.GetNetname()
        if net not in target_nets or (hasattr(zone,"GetIsRuleArea") and zone.GetIsRuleArea()): continue
        for layer in set(zone.GetLayerSet().CuStack()) & enabled_set:
            if not zone.HasFilledPolysForLayer(layer): continue
            polys=zone.GetFilledPolysList(layer)
            for oi in range(polys.OutlineCount()):
                shape=zone_island_shape(pcbnew,polys,oi)
                add(net,"zone_island",{layer:shape},zone_index=zi,outline_index=oi,layer=layer,layer_name=pcbnew.LayerName(layer),is_island=bool(zone.IsIsland(layer,oi)),area_mm2=round(abs(float(shape.Area()))/1e12,6),bbox=bbox_json(bbox_mm(pcbnew,shape.BBox())))
    clearance=pcbnew.FromMM(.001)
    for ids in by_net.values():
        for ix,a in enumerate(ids):
            for b in ids[ix+1:]:
                if collide_nodes(nodes[a],nodes[b],clearance): uf.union(a,b)
    for node in nodes.values(): node["root"]=uf.find(node["id"])
    return {"uf":uf,"nodes":nodes,"by_net":dict(by_net),"enabled_layers":enabled}

def summarize_graph(graph):
    result={}
    for net,ids in graph["by_net"].items():
        rows=[graph["nodes"][i] for i in ids]; pads=[x for x in rows if x["kind"]=="pad"]; counts=defaultdict(int)
        for p in pads: counts[p["root"]]+=1
        main=min(counts,key=lambda r:(-counts[r],r)) if counts else None
        result[net]={"node_count":len(rows),"pad_roots":[{"ref":p["ref"],"pad":p["pad"],"root":p["root"]} for p in pads],"pad_root_ids":sorted({p["root"] for p in pads}),"copper_roots":sorted({x["root"] for x in rows}),"largest_pad_root":main,"largest_pad_component_pad_count":counts.get(main,0),"node_roots":{str(x["id"]):x["root"] for x in rows},"island_roots":[{"node":x["id"],"root":x["root"],"layer":x["layer_name"],"area_mm2":x["area_mm2"]} for x in rows if x["kind"]=="zone_island"]}
    return result

def node_hits_point(node,layer,point,clearance):
    return layer in node["shapes"] and node["shapes"][layer].Collide(point,clearance)

def analyze_necks(net,target,graph,summary,pcbnew,failures):
    main=summary[net]["largest_pad_root"]; rows=[graph["nodes"][i] for i in graph["by_net"].get(net,[])]; tracks=[x for x in rows if x["kind"]=="track"]
    result=connected_wide_ratio(tracks,main,target); minimum=.30 if net=="BUCK_SW" else .60
    if not result["connected_total_length_mm"]: failures.append(f"{net}: no tracks in largest-pad component")
    elif result["wide_ratio"]+1e-9 < minimum: failures.append(f"{net}: connected wide ratio {result['wide_ratio']:.4f} below {minimum:.2f}")
    if result["disconnected_segment_count"]: failures.append(f"{net}: {result['disconnected_segment_count']} disconnected track segments")
    narrow=[x for x in tracks if x["root"]==main and x["width_mm"]+1e-9<target]
    trunks=[x for x in rows if x["root"]==main and ((x["kind"]=="track" and x["width_mm"]+1e-9>=target) or x["kind"] in {"via","zone_island"})]
    edges=[]; endpoints={}
    for x in narrow:
        a=(x["layer"],)+point_key(x["start"]); b=(x["layer"],)+point_key(x["end"]); endpoints[a]=x["start"]; endpoints[b]=x["end"]; edges.append((a,b,x["length_mm"]))
    tol=pcbnew.FromMM(.001); seeds={k for k,p in endpoints.items() if any(node_hits_point(t,k[0],p,tol) for t in trunks)}
    fine=[x for x in rows if x["kind"]=="pad" and x["ref"] in FINE_REFS]; targets={}; direct=set()
    for pad in fine:
        label=f"{pad['ref']}.{pad['pad']}"; targets[label]={k for k,p in endpoints.items() if node_hits_point(pad,k[0],p,tol)}
        if any(collide_nodes(pad,t,tol) for t in trunks): direct.add(label)
    distances=shortest_neck_distances(edges,seeds,targets)
    for label in direct: distances[label]=0.
    paths=[]
    for pad in fine:
        label=f"{pad['ref']}.{pad['pad']}"; d=distances.get(label); applies=neck_threshold_applies(net,pad["ref"],pad["pad"]); paths.append({"pad":label,"root":pad["root"],"direct_trunk_contact":label in direct,"shortest_neck_mm":round(d,6) if d is not None else None,"current_carrying_neck_limit_applies":applies,"exception_basis":"TPS62162 VOS Kelvin sense; connectivity still mandatory" if not applies else None})
        if d is None: failures.append(f"{net}: {label} has no path to a wide trunk")
        elif applies and d>MAX_NECK_CHAIN_MM+1e-9: failures.append(f"{net}: {label} neck {d:.3f}mm exceeds {MAX_NECK_CHAIN_MM:.2f}mm")
    result.update({"target_width_mm":target,"minimum_ratio":minimum,"neckdown_segment_count":len(narrow),"neckdown_total_mm":round(sum(x["length_mm"] for x in narrow),6),"neckdown_pad_paths":paths,"neckdown_chain_max_mm":round(max((x["shortest_neck_mm"] for x in paths if x["shortest_neck_mm"] is not None),default=0),6),"dijkstra_basis":"per-pad shortest path to nearest main-root wide track/via/filled-zone"})
    return result

def analyze_plane(net,minimum,graph,summary,pcbnew,failures):
    islands=[graph["nodes"][i] for i in graph["by_net"].get(net,[]) if graph["nodes"][i]["kind"]=="zone_island" and graph["nodes"][i]["layer"]==pcbnew.In2_Cu]
    vias=[graph["nodes"][i] for i in graph["by_net"].get(net,[]) if graph["nodes"][i]["kind"]=="via"]; rows=[]
    for island in islands:
        entries=[{"node":v["id"],"at_mm":v["at_mm"],"root":v["root"]} for v in vias if pcbnew.In2_Cu in v["shapes"] and v["shapes"][pcbnew.In2_Cu].Collide(island["shapes"][pcbnew.In2_Cu],pcbnew.FromMM(.001))]
        rows.append({"node":island["id"],"root":island["root"],"area_mm2":island["area_mm2"],"bbox":island["bbox"],"is_island":island["is_island"],"direct_entry_vias":entries,"direct_entry_count":len(entries)})
    winner=max(rows,key=lambda x:(x["direct_entry_count"],x["area_mm2"]),default=None); enough=bool(winner and winner["direct_entry_count"]>=minimum); pad_roots=summary[net]["pad_root_ids"]; contains=bool(winner and pad_roots and all(r==winner["root"] for r in pad_roots))
    if not islands: failures.append(f"{net}: no actual filled In2 island")
    if not enough: failures.append(f"{net}: needs {minimum} direct via entries into one filled island")
    if not contains: failures.append(f"{net}: winning plane island does not contain all pad roots")
    return {"minimum_required":minimum,"filled_island_count":len(rows),"islands":rows,"winning_island_node":winner["node"] if winner else None,"count":winner["direct_entry_count"] if winner else 0,"vias":winner["direct_entry_vias"] if winner else [],"all_required_entries_same_island":enough,"winning_island_contains_all_pad_roots":contains}

def analyze_returns(graph,pcbnew,failures):
    rows=[graph["nodes"][i] for i in graph["by_net"].get("GND",[])]; pads=[x for x in rows if x["kind"]=="pad"]; vias=[x for x in rows if x["kind"]=="via"]; checks={}
    for ref,required in (("U3",2),("U4",3),("U2",2),("J1",1)):
        rp=[p for p in pads if p["ref"]==ref]; qualifying=[]
        for via in vias:
            if any(via["root"]==pad["root"] and any(node_hits_point(pad,layer,via["position"],pcbnew.FromMM(3.)) for layer in set(pad["shapes"])&set(via["shapes"])) for pad in rp): qualifying.append({"node":via["id"],"at_mm":via["at_mm"],"root":via["root"]})
        checks[ref]={"basis":"same-root GND via position within 3mm of actual GND pad copper","gnd_pad_count":len(rp),"gnd_vias_within_3mm":len(qualifying),"required_within_3mm":required,"qualifying_vias":qualifying}
        if len(qualifying)<required: failures.append(f"{ref}: needs {required} same-root local GND vias, found {len(qualifying)}")
    u1=[p for p in pads if p["ref"]=="U1"]; roots=sorted({p["root"] for p in u1}); report={"pad_count":len(u1),"component_count":len(roots),"roots":roots,"pads":[{"pad":p["pad"],"root":p["root"]} for p in u1]}
    if not u1 or len(roots)!=1: failures.append(f"GND: U1 pads span {len(roots)} copper components")
    return checks,report

def analyze_speaker(graph,summary,board,pcbnew,failures):
    tracks={n:[graph["nodes"][i] for i in graph["by_net"].get(n,[]) if graph["nodes"][i]["kind"]=="track"] for n in ("SPK_PLUS","SPK_MINUS")}
    pure={n:[{"start":x["start_mm"],"end":x["end_mm"],"width_mm":x["width_mm"]} for x in v] for n,v in tracks.items()}; geo=analyze_speaker_geometry(pure["SPK_PLUS"],pure["SPK_MINUS"])
    lengths={n:round(sum(x["length_mm"] for x in v),6) for n,v in tracks.items()}; low,high=sorted(lengths.values()); ratio=high/low if low else math.inf; delta=high-low
    vias=[graph["nodes"][i] for n in ("SPK_PLUS","SPK_MINUS") for i in graph["by_net"].get(n,[]) if graph["nodes"][i]["kind"]=="via"]
    zones=sorted({z.GetNetname() for z in board.Zones() if z.GetNetname() in {"SPK_PLUS","SPK_MINUS"}}); layers=sorted({x["layer_name"] for v in tracks.values() for x in v})
    if geo["minimum_copper_gap_mm"] is None or geo["minimum_copper_gap_mm"]+1e-9<MIN_SPK_GAP: failures.append(f"SPK gap {geo['minimum_copper_gap_mm']} below {MIN_SPK_GAP}")
    if geo["crossing_count"]: failures.append(f"SPK centerlines cross {geo['crossing_count']} time(s)")
    if ratio>MAX_SPK_RATIO+1e-9: failures.append(f"SPK length ratio {ratio:.4f} exceeds {MAX_SPK_RATIO}")
    if delta>5.+1e-9: failures.append(f"SPK length delta {delta:.3f}mm exceeds 5mm")
    if vias: failures.append("SPK nets have vias")
    if zones: failures.append("SPK nets have zones")
    if len(layers)!=1: failures.append(f"SPK nets do not share one layer: {layers}")
    return {**geo,"minimum_gap_required_mm":MIN_SPK_GAP,"maximum_length_ratio":MAX_SPK_RATIO,"zones":zones,"vias":[{"net":x["net"],"at_mm":x["at_mm"]} for x in vias],"layers":layers,"length_mm":lengths,"length_delta_mm":round(delta,6),"length_ratio":round(ratio,6) if math.isfinite(ratio) else None,"connectivity":{n:{"pad_roots":summary[n]["pad_root_ids"],"all_pads_single_root":len(summary[n]["pad_root_ids"])==1} for n in ("SPK_PLUS","SPK_MINUS")}}

def analyze_edge(graph,board_box,pcbnew,failures):
    result={}
    for net in TARGET_WIDTH_MM:
        limiting=None
        for i in graph["by_net"].get(net,[]):
            node=graph["nodes"][i]
            for layer,shape in node["shapes"].items():
                box=bbox_mm(pcbnew,shape.BBox()); clearance=bbox_to_rect_edge_clearance(box,board_box)
                if limiting is None or clearance<limiting[0]: limiting=(clearance,node,layer,box)
        value=limiting[0] if limiting else -math.inf; result[net]={"minimum_clearance_mm":round(value,6) if math.isfinite(value) else None,"required_mm":MIN_COPPER_TO_EDGE_MM,"limiting_node":limiting[1]["id"] if limiting else None,"limiting_kind":limiting[1]["kind"] if limiting else None,"limiting_layer":pcbnew.LayerName(limiting[2]) if limiting else None,"limiting_bbox":bbox_json(limiting[3]) if limiting else None}
        if value+1e-9<MIN_COPPER_TO_EDGE_MM: failures.append(f"{net}: copper-edge {value:.4f}mm below {MIN_COPPER_TO_EDGE_MM}")
    return result

def rect_shape(pcbnew,b):
    return pcbnew.SHAPE_RECT(pcbnew.VECTOR2I(pcbnew.FromMM(b[0]),pcbnew.FromMM(b[1])),pcbnew.VECTOR2I(pcbnew.FromMM(b[2]),pcbnew.FromMM(b[3])))
def noisy_shapes(board,pcbnew):
    enabled=list(board.GetEnabledLayers().CuStack())
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if not NOISY_RE.search(pad.GetNetname() or ""): continue
            for layer in enabled:
                if pad.FlashLayer(layer): yield pad.GetNetname(),"pad",f"{fp.GetReference()}.{pad.GetNumber()}",layer,pad.GetEffectiveShape(layer)
    for item in board.GetTracks():
        net=item.GetNetname() or ""
        if not NOISY_RE.search(net): continue
        if isinstance(item,pcbnew.PCB_VIA):
            for layer in enabled:
                if item.FlashLayer(layer): yield net,"via",str(point_mm(pcbnew,item.GetPosition())),layer,item.GetEffectiveShape(layer)
        else: yield net,"track",str(point_mm(pcbnew,item.GetStart())),item.GetLayer(),item.GetEffectiveShape()
    for zi,z in enumerate(board.Zones()):
        net=z.GetNetname() or ""
        if not NOISY_RE.search(net) or (hasattr(z,"GetIsRuleArea") and z.GetIsRuleArea()): continue
        for layer in set(z.GetLayerSet().CuStack())&set(enabled):
            if not z.HasFilledPolysForLayer(layer): continue
            polys=z.GetFilledPolysList(layer)
            for oi in range(polys.OutlineCount()): yield net,"zone_island",f"{zi}.{oi}",layer,zone_island_shape(pcbnew,polys,oi)

def analyze_nina(board,pcbnew,graph,board_box,failures):
    fps={x.GetReference():x for x in board.GetFootprints()}; u1=fps.get("U1")
    if not u1: failures.append("NINA-B302: U1 missing"); return {"present":False}
    fab=[bbox_mm(pcbnew,x.GetBoundingBox()) for x in u1.GraphicalItems() if x.GetLayer()==pcbnew.F_Fab]
    if not fab: failures.append("NINA-B302: F.Fab body missing"); return {"present":True,"fab_bbox_missing":True}
    body=bbox_union(fab); feed_pads=[p for p in u1.Pads() if str(p.GetNumber()) in {"15","16"}]
    if len(feed_pads)!=2: failures.append("NINA-B302: pads15/16 missing"); return {"present":True,"body_bbox":bbox_json(body)}
    feed=(sum(mm(pcbnew,p.GetPosition().x) for p in feed_pads)/2,sum(mm(pcbnew,p.GetPosition().y) for p in feed_pads)/2)
    fd={"left":feed[0]-board_box[0],"right":board_box[2]-feed[0],"top":feed[1]-board_box[1],"bottom":board_box[3]-feed[1]}; edge=min(fd,key=fd.get)
    bd={"left":body[0]-board_box[0],"right":board_box[2]-body[2],"top":body[1]-board_box[1],"bottom":board_box[3]-body[3]}; outward=fd[edge]<=3.+1e-9 and bd[edge]<=.5+1e-9; near=[k for k,v in bd.items() if v<=3.+1e-9]; placement="corner_preferred" if len(near)>=2 else "edge_allowed_reduced_performance"
    if not outward: failures.append(f"NINA-B302 not outward at {edge} edge")
    if edge=="left": antenna=(body[0],body[1],min(body[2],body[0]+NINA_ANTENNA_SECTION_MM),body[3])
    elif edge=="right": antenna=(max(body[0],body[2]-NINA_ANTENNA_SECTION_MM),body[1],body[2],body[3])
    elif edge=="top": antenna=(body[0],body[1],body[2],min(body[3],body[1]+NINA_ANTENNA_SECTION_MM))
    else: antenna=(body[0],max(body[1],body[3]-NINA_ANTENNA_SECTION_MM),body[2],body[3])
    inset=(board_box[0]+MIN_COPPER_TO_EDGE_MM,board_box[1]+MIN_COPPER_TO_EDGE_MM,board_box[2]-MIN_COPPER_TO_EDGE_MM,board_box[3]-MIN_COPPER_TO_EDGE_MM); bounds=(max(body[0],inset[0]),max(body[1],inset[1]),min(body[2],inset[2]),min(body[3],inset[3]))
    nx=max(0,int(math.floor((bounds[2]-bounds[0])/NINA_GND_STEP+1e-9))); ny=max(0,int(math.floor((bounds[3]-bounds[1])/NINA_GND_STEP+1e-9)))
    islands=[graph["nodes"][i] for i in graph["by_net"].get("GND",[]) if graph["nodes"][i]["kind"]=="zone_island" and graph["nodes"][i]["layer"]==pcbnew.In1_Cu]; covered=0; covering=set()
    for ix in range(nx):
        for iy in range(ny):
            point=pcbnew.VECTOR2I(pcbnew.FromMM(bounds[0]+(ix+.5)*NINA_GND_STEP),pcbnew.FromMM(bounds[1]+(iy+.5)*NINA_GND_STEP)); hits=[z for z in islands if z["shapes"][pcbnew.In1_Cu].Collide(point,0)]
            if hits: covered+=1; covering.update(z["id"] for z in hits)
    total=nx*ny; coverage=covered/total if total else 0.
    if coverage+1e-12<NINA_MIN_GND_COVERAGE: failures.append(f"NINA-B302 In1 GND coverage {coverage:.4f} below {NINA_MIN_GND_COVERAGE}")
    if len(covering)!=1: failures.append(f"NINA-B302 body uses {len(covering)} actual In1 GND islands")
    neighbors=[]
    for ref,fp in fps.items():
        if ref=="U1": continue
        box=bbox_mm(pcbnew,fp.GetBoundingBox(False,False)); distance=bbox_distance(box,antenna)
        if distance>NINA_NEIGHBOR_MM+1e-9: continue
        w,h=box[2]-box[0],box[3]-box[1]; value=fp.GetValue() or ""; automatic=max(w,h)>=5 or w*h>=25 or bool(HIGH_REF_RE.search(ref)) or bool(HIGH_VALUE_RE.search(value))
        neighbors.append({"ref":ref,"value":value,"bbox":bbox_json(box),"distance_mm":round(distance,6),"max_dimension_mm":round(max(w,h),6),"area_mm2":round(w*h,6),"classification":"automatic_blocker" if automatic else "low_profile_manual_review"})
        if automatic: failures.append(f"NINA-B302: {ref} high/large/metal heuristic within {distance:.3f}mm")
    antenna_shape=rect_shape(pcbnew,antenna); noisy={}
    for net,kind,label,layer,shape in noisy_shapes(board,pcbnew):
        distance=bbox_distance(bbox_mm(pcbnew,shape.BBox()),antenna)
        if distance>NINA_NEIGHBOR_MM+1e-9: continue
        row=noisy.setdefault(net,{"net":net,"minimum_distance_mm":distance,"crosses_antenna_rect":False,"item_count":0,"kinds":set(),"items":[]}); row["minimum_distance_mm"]=min(row["minimum_distance_mm"],distance); row["crosses_antenna_rect"] |= bool(shape.Collide(antenna_shape,pcbnew.FromMM(.001))); row["item_count"]+=1; row["kinds"].add(kind)
        if len(row["items"])<12: row["items"].append({"kind":kind,"id":label,"layer":pcbnew.LayerName(layer),"distance_mm":round(distance,6)})
    noisy_rows=[]; advisory=[]
    for net in sorted(noisy):
        row=noisy[net]; row["minimum_distance_mm"]=round(row["minimum_distance_mm"],6); row["kinds"]=sorted(row["kinds"]); automatic=bool(re.search("BUCK_SW",net,re.I)) or row["crosses_antenna_rect"]; row["classification"]="automatic_blocker" if automatic else "advisory"; noisy_rows.append(row)
        if automatic: failures.append(f"NINA-B302: noisy net {net} is BUCK_SW within 10mm or crosses antenna rectangle")
        else: advisory.append(net)
    return {"present":True,"datasheet_basis":"u-blox UBX-17056748 R15 §3.3.3; B302 metal PIFA needs full ground and is not a cutout antenna","body_bbox":bbox_json(body),"feed_point_mm":[round(feed[0],6),round(feed[1],6)],"nearest_edge":edge,"feed_edge_distance_mm":round(fd[edge],6),"body_edge_distance_mm":round(bd[edge],6),"outward":outward,"near_edges_within_3mm":near,"placement_class":placement,"placement_note":"edge placement allowed with moderately reduced performance" if placement!="corner_preferred" else "preferred corner placement","antenna_section_bbox":bbox_json(antenna),"in1_ground_coverage":{"bounds":bbox_json(bounds),"grid_origin_mm":[round(bounds[0]+NINA_GND_STEP/2,6),round(bounds[1]+NINA_GND_STEP/2,6)] if total else None,"grid_step_mm":NINA_GND_STEP,"boundary_rule":"deterministic cell centers; floor(width/step)*floor(height/step); Edge.Cuts inset .30mm","covered":covered,"total":total,"coverage":round(coverage,9),"minimum_required":NINA_MIN_GND_COVERAGE,"covering_island_nodes":sorted(covering),"covering_island_roots":sorted({graph['nodes'][i]['root'] for i in covering}),"covering_actual_island_count":len(covering)},"neighbor_clearance_mm":NINA_NEIGHBOR_MM,"neighbor_footprints":sorted(neighbors,key=lambda x:(x['distance_mm'],x['ref'])),"noisy_copper":noisy_rows,"advisory_noisy_nets":advisory,"mechanical_contract":{"status":"OPEN_MANUAL_REVIEW","non_metallic_casing_required":True,"minimum_casing_clearance_mm":NINA_CASING_MM,"outward_unobstructed_required":True,"height_material_and_casing_review_required":True}}

def ground_islands(graph,pcbnew):
    nodes=graph["nodes"]; pads=[nodes[i] for i in graph["by_net"].get("GND",[]) if nodes[i]["kind"]=="pad"]; rows=[]
    for i in graph["by_net"].get("GND",[]):
        z=nodes[i]
        if z["kind"]!="zone_island": continue
        touching=sorted(f"{p['ref']}.{p['pad']}" for p in pads if collide_nodes(z,p,pcbnew.FromMM(.001)))
        rows.append({"node":z["id"],"layer":z["layer_name"],"area_mm2":z["area_mm2"],"bbox":z["bbox"],"is_island":z["is_island"],"root":z["root"],"directly_touching_pads":touching})
    return sorted(rows,key=lambda x:(x["layer"],-x["area_mm2"],x["node"]))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--board",type=Path,required=True); ap.add_argument("--output",required=True,help="JSON file or '-' for stdout only"); args=ap.parse_args()
    if hasattr(os,"add_dll_directory"): os.add_dll_directory(str(KICAD_BIN))
    sys.path.insert(0,str(KICAD_SITE)); import pcbnew
    board=pcbnew.LoadBoard(str(args.board.resolve(strict=True))); failures=[]; board_box=edge_extents(board,pcbnew); graph=build_copper_graph(board,pcbnew,set(TARGET_WIDTH_MM)|{"GND"}); summary=summarize_graph(graph)
    for net in TARGET_WIDTH_MM:
        row=summary.setdefault(net,{"pad_roots":[],"pad_root_ids":[],"copper_roots":[],"largest_pad_root":None,"node_roots":{},"island_roots":[]})
        if len(row["pad_root_ids"])!=1: failures.append(f"{net}: pads span {len(row['pad_root_ids'])} copper roots")
        disconnected=[i for i in graph["by_net"].get(net,[]) if graph["nodes"][i]["kind"] in {"track","via","zone_island"} and graph["nodes"][i]["root"]!=row["largest_pad_root"]]
        if disconnected: failures.append(f"{net}: copper nodes {disconnected} outside largest-pad component")
    nets={n:analyze_necks(n,w,graph,summary,pcbnew,failures) for n,w in TARGET_WIDTH_MM.items()}; planes={"USB_VBUS_5V":analyze_plane("USB_VBUS_5V",3,graph,summary,pcbnew,failures),"3V3":analyze_plane("3V3",2,graph,summary,pcbnew,failures)}; returns,u1=analyze_returns(graph,pcbnew,failures); speaker=analyze_speaker(graph,summary,board,pcbnew,failures); edge=analyze_edge(graph,board_box,pcbnew,failures); nina=analyze_nina(board,pcbnew,graph,board_box,failures)
    vias=[x for x in graph["nodes"].values() if x["kind"]=="via"]
    for x in vias:
        if x["diameter_mm"]+1e-9<.60: failures.append(f"via {x['net']} at {x['at_mm']} diameter below .60mm")
        if x["drill_mm"]+1e-9<.30: failures.append(f"via {x['net']} at {x['at_mm']} drill below .30mm")
    payload={"schema":"magic-wand.receiver-effects.power-return-audit.v3","board":str(args.board),"board_origin_mm":[round(board_box[0],6),round(board_box[1],6)],"board_size_mm":[round(board_box[2]-board_box[0],6),round(board_box[3]-board_box[1],6)],"copper_layers":board.GetCopperLayerCount(),"native_drc_required":{"violations":0,"unconnected":0,"parity":0,"evaluated_by_this_script":False,"note":"Auxiliary only; does not replace native DRC/unrouted/parity or USB impedance/reference-plane/length proof."},"requirements":{"max_neck_path_mm":MAX_NECK_CHAIN_MM,"minimum_via_diameter_mm":.60,"minimum_via_drill_mm":.30,"minimum_trunk_ratio":.60,"buck_minimum_trunk_ratio":.30,"minimum_copper_to_edge_mm":MIN_COPPER_TO_EDGE_MM,"minimum_speaker_gap_mm":MIN_SPK_GAP,"maximum_speaker_ratio":MAX_SPK_RATIO,"plane_entry_minimum":{"USB_VBUS_5V":3,"3V3":2}},"copper_graph":{"enabled_layers":[pcbnew.LayerName(x) for x in graph["enabled_layers"]],"nets":summary},"nets":nets,"via_count":len(vias),"gnd_via_count":sum(x["net"]=="GND" for x in vias),"plane_entries":planes,"local_return_paths":returns,"u1_ground_connectivity":u1,"speaker_output":speaker,"copper_to_edge":edge,"nina_b302_rf":nina,"gnd_filled_islands":ground_islands(graph,pcbnew),"failure_count":len(failures),"failures":failures,"passed":not failures}
    encoded=json.dumps(payload,indent=2,ensure_ascii=False)+"\n"
    if args.output=="-": sys.stdout.write(encoded)
    else:
        out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(encoded,encoding="utf-8"); print(json.dumps({"passed":payload["passed"],"failure_count":len(failures),"output":str(out)}))
    return 0 if payload["passed"] else 1
if __name__=="__main__": raise SystemExit(main())
