from __future__ import annotations
import hashlib, json
from pathlib import Path

RUN = Path(__file__).resolve().parent
LOCKS = {"reviewOnly": True, "accepted": False, "ruleEnabled": False, "packagingGated": True}
FEATURES = ["base_plate", "bearing_boss", "bearing_seat", "shaft_clearance", "seal_recess", "indexer_hole_pattern", "cover_hole_pattern", "frame_mount_holes", "frame_counterbores", "dowel_holes", "rib_pads", "lightening_pockets", "manufacturing_drawing", "selectable_2d_reviewer", "selectable_3d_reviewer"]
OUTPUTS = ["plan.json", "aicad", "scr", "dxf", "audit.md", "manifest.json"]
DIMENSIONS = [
    ("BASE_W",220,210,230), ("BASE_H",180,170,190), ("BASE_T",20,18,20), ("TOTAL_H",56,56,60),
    ("BOSS_D",130,125,135), ("SEAT_D",80,78,82), ("SEAT_DEPTH",36,34,36), ("SHAFT_D",50,48,52),
    ("SEAL_D",92,90,94), ("SEAL_DEPTH",6,5,7), ("INDEXER_PCD",108,104,110), ("INDEXER_HOLE_D",9,8,10),
    ("COVER_PCD",104,100,106), ("COVER_HOLE_D",7,6,8), ("FRAME_HOLE_D",14,13,15), ("FRAME_CB_D",24,23,25),
    ("FRAME_CB_DEPTH",10,9,11), ("DOWEL_D",8,7.8,8.2), ("RIB_W",42,40,44), ("RIB_H",72,70,74),
    ("RIB_DEPTH",12,10,14), ("POCKET_W",36,34,38), ("POCKET_H",34,32,36), ("POCKET_DEPTH",10,8,12),
]

def dump(name, payload):
    (RUN/name).write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

def canonical_sha(payload):
    raw=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def chk(cid,purpose,lhs,op,rhs):
    return {"id":cid,"purpose":purpose,"lhs":lhs,"operator":op,"rhs":rhs}

def edge(eid,start,end,purpose):
    length=((end[0]-start[0])**2+(end[1]-start[1])**2)**0.5
    return {"id":eid,"type":"line","purpose":purpose,"reasoning":"Frozen envelope parameters and named vertices determine this proof edge.","start":{"point":list(start)},"construction":{"kind":"to_point","target":{"point":list(end)}},"constraints":[{"kind":"start_offset","target":"origin","dx":start[0],"dy":start[1]},{"kind":"length","value":length}]}

def build():
    parameters=[{"id":pid,"role":"independent","unit":"mm","default":value,"min":low,"max":high,"purpose":f"controlled {pid.lower()} dimension"} for pid,value,low,high in DIMENSIONS]
    parameters += [
        {"id":"BOSS_H","role":"derived","unit":"mm","formula":"TOTAL_H-BASE_T","purpose":"boss height above base"},
        {"id":"RESIDUAL_WALL","role":"derived","unit":"mm","formula":"(BOSS_D-SEAT_D)/2","purpose":"bearing housing radial wall"},
        {"id":"POCKET_FLOOR","role":"derived","unit":"mm","formula":"BASE_T-POCKET_DEPTH","purpose":"remaining pocket floor"},
        {"id":"BASE_AREA","role":"derived","unit":"mm","formula":"BASE_W*BASE_H","purpose":"base plan area"},
    ]
    template={
        "schema":"aicad_normality_template_v1","profileId":"SIFC_BOUNDED_ENVELOPE","profileVersion":"1.0.0","productType":"servo_indexer_bearing_cartridge","majorFeatures":FEATURES,
        "structureName":"SIFC-220 prebuild bounded-envelope and parameter-domain review",
        "closureSystem":{"top":"bearing_side","bottom":"mounting_side","asymmetric":True,"standard":"ISO GPS plus GB/T mechanical drawing controlled design basis"},
        "toleranceMm":0.000001,"parameters":parameters,"excludedEntityIds":["ORIGIN_BOOTSTRAP"],"productionEntityIds":["ENV_BOTTOM","ENV_RIGHT","ENV_TOP","ENV_LEFT"],"expectedLayerCounts":{"OUTLINE":4},
        "vertices":[
            {"id":"V0","purpose":"lower-left corner","x":"0","y":"0","refs":["ENV_BOTTOM.start","ENV_LEFT.end"]},
            {"id":"V1","purpose":"lower-right corner","x":"BASE_W","y":"0","refs":["ENV_BOTTOM.end","ENV_RIGHT.start"]},
            {"id":"V2","purpose":"upper-right corner","x":"BASE_W","y":"BASE_H","refs":["ENV_RIGHT.end","ENV_TOP.start"]},
            {"id":"V3","purpose":"upper-left corner","x":"0","y":"BASE_H","refs":["ENV_TOP.end","ENV_LEFT.start"]},
        ],
        "outerContour":["ENV_BOTTOM","ENV_RIGHT","ENV_TOP","ENV_LEFT"],
        "features":[{"id":"BASE_ENVELOPE_FACE","kind":"face","purpose":"bounded base-envelope proof face","countsAsFace":True,"entityIds":["ENV_BOTTOM","ENV_RIGHT","ENV_TOP","ENV_LEFT"],"polygonVertexIds":["V0","V1","V2","V3"],"rules":{"simple":True,"convex":True,"minAreaMm2":35000}}],
        "measurements":[{"id":"WIDTH_MEASURED","kind":"abs_dx","a":"V0","b":"V1"},{"id":"HEIGHT_MEASURED","kind":"abs_dy","a":"V0","b":"V3"},{"id":"AREA_MEASURED","kind":"feature_area","featureId":"BASE_ENVELOPE_FACE"}],
        "domainAssertions":[
            chk("BASE_LANDSCAPE","base remains wider than tall","BASE_W",">","BASE_H"), chk("BOSS_HEIGHT","boss contains bearing-seat depth","BOSS_H",">=","SEAT_DEPTH"),
            chk("NEST_1","boss contains seal recess","BOSS_D",">","SEAL_D"), chk("NEST_2","seal contains seat","SEAL_D",">","SEAT_D"), chk("NEST_3","seat contains shaft","SEAT_D",">","SHAFT_D"),
            chk("WALL","housing retains radial wall","RESIDUAL_WALL",">=","21.5"), chk("INDEXER_INSIDE","indexer holes stay inside boss","INDEXER_PCD/2+INDEXER_HOLE_D/2","<=","BOSS_D/2"),
            chk("COVER_INSIDE","cover holes stay inside boss","COVER_PCD/2+COVER_HOLE_D/2","<=","BOSS_D/2"), chk("CB_SIZE","counterbore exceeds through-hole","FRAME_CB_D",">","FRAME_HOLE_D"),
            chk("CB_FLOOR","counterbore retains floor","FRAME_CB_DEPTH","<","BASE_T"), chk("POCKET_FLOOR","pocket retains floor","POCKET_FLOOR",">=","6"),
        ],
        "assertions":[chk("WIDTH_EXACT","measured width follows parameter","WIDTH_MEASURED","==","BASE_W"),chk("HEIGHT_EXACT","measured height follows parameter","HEIGHT_MEASURED","==","BASE_H"),chk("AREA_EXACT","face area follows parameters","AREA_MEASURED","==","BASE_AREA"),chk("BBOX_W","bbox width follows parameter","ACTUAL_BBOX_WIDTH","==","BASE_W"),chk("BBOX_H","bbox height follows parameter","ACTUAL_BBOX_HEIGHT","==","BASE_H")],
        "expectedBBox":{"minX":"0","minY":"0","maxX":"BASE_W","maxY":"BASE_H"},
        "sampling":{"randomSeed":22018056,"randomCases":64,"explicitCases":[{"id":"minimum_envelope","values":{"BASE_W":210,"BASE_H":170}},{"id":"maximum_envelope","values":{"BASE_W":230,"BASE_H":190}}]},"locks":dict(LOCKS),
    }
    values={pid:value for pid,value,_low,_high in DIMENSIONS}
    instance={"schema":"aicad_normality_instance_v1","profileId":template["profileId"],"profileVersion":template["profileVersion"],"values":values,"locks":dict(LOCKS)}
    points=[(0,0),(220,0),(220,180),(0,180)]; ids=template["productionEntityIds"]; purposes=["base lower edge","base right edge","base upper edge","base left edge"]
    bootstrap=edge("ORIGIN_BOOTSTRAP",(0,0),(1,1),"excluded origin anchor proving the plan starts from the global datum")
    plan={"schema_version":"2.0","drawing":{"name":"SIFC_220_prebuild_normality","units":"mm","origin":[0,0],"tolerance":0.000001,"domain":"mechanical"},"steps":[bootstrap]+[edge(ids[i],points[i],points[(i+1)%4],purposes[i]) for i in range(4)]}
    geometry={"schema":"aicad.prebuild-normality-geometry.v1","design":dict(LOCKS),"entities":[{"id":ids[i],"type":"LINE","layer":"OUTLINE","start":list(points[i]),"end":list(points[(i+1)%4]),"purpose":purposes[i],"reasoning":"Resolved from frozen prebuild envelope parameters.","dependencies":["BASE_W","BASE_H","GLOBAL_ORIGIN"]} for i in range(4)]}
    contract={
        "schema":"aicad_drawing_requirement_contract_v1","contractId":"REQ.SIFC.220.REV.A","revision":1,
        "requestSummary":"Prebuild, review-only intent contract for a complex native SolidWorks servo-indexer bearing cartridge and selectable 2D/3D review evidence.",
        "productType":template["productType"],"useCase":"prebuild requirement freeze; not geometry, manufacturing, fabrication, or acceptance evidence","domain":"mechanical","deliveryStage":"review",
        "selectedRulePacks":["normative_governance","mechanical","native_solidworks_topology","canonical_v3_generation_preflight","post_generation_evidence_contract_v3"],
        "applicableStandards":[{"id":"STD.ISO.GPS","title":"ISO GPS dimensional and geometrical specification","edition":"controlled design basis","scope":"datums, fits, tolerances and inspection intent","sourceId":"STANDARD"},{"id":"STD.GBT.DRAWING","title":"GB/T mechanical drawing convention","edition":"controlled design basis","scope":"drawing presentation intent","sourceId":"STANDARD"}],
        "units":"mm","sources":[
            {"id":"STANDARD","kind":"selected_standard","description":"ISO GPS and GB/T controlled design basis.","path":"standards-authority.md","dimensionalAuthority":True},
            {"id":"ENGINEERING","kind":"approved_engineering_input","description":"7075-T651","path":"design-basis.md","dimensionalAuthority":True},
            {"id":"ANALYSIS","kind":"approved_engineering_input","description":"Preliminary load and life calculations.","path":"analysis-basis.md","dimensionalAuthority":True},
            {"id":"PREFLIGHT","kind":"approved_engineering_input","description":"Passed 54-gate pre-geometry report.","path":"mechanical-preflight.report.json","dimensionalAuthority":True},
            {"id":"USER","kind":"user_explicit_semantic","description":"Complex drawing, 3D review and token-accounting request.","dimensionalAuthority":False},
            {"id":"IMAGE","kind":"reference_image","description":"Visual topology reference only; no pixel-derived dimensions.","path":"C:/Users/刘佳明/.codex/attachments/a74454bb-fc8d-4578-8b65-74f155bcbe5d/image-1.jpg","dimensionalAuthority":False}],
        "authorityOrder":["STANDARD","ENGINEERING","ANALYSIS","PREFLIGHT","USER","IMAGE"],"requirements":[],
        "assumptions":[{"id":"ASM.NATIVE.EDGE_BREAK","statement":"Native fillet/chamfer is outside the released matrix; edge break is drawing intent only.","impact":"high","status":"confirmed","sourceIds":["ENGINEERING","PREFLIGHT"]}],
        "conflicts":[],"requiredMajorFeatures":FEATURES,"allowedMajorFeatures":FEATURES,"forbiddenMajorFeatures":["native_fillet","native_chamfer","assembly_mates"],"requiredOutputs":OUTPUTS,"locks":dict(LOCKS),
    }
    evidence={}
    def add(rid,category,statement,expected,sources,observed,binding,method):
        contract["requirements"].append({"id":rid,"category":category,"statement":statement,"priority":"hard","sourceIds":sources,"mustConfirm":False,"expected":expected}); evidence[rid]=(observed,binding,method)
    add("REQ.PRODUCT","overall_shape","Freeze the cartridge product family.",{"kind":"exact","value":template["productType"]},["USER","ENGINEERING"],template["productType"],{"source":"normality_template","transform":"identity","jsonPointer":"/productType"},"typed_identity")
    add("REQ.STRUCTURE","structure_family","Freeze the exact SIFC-220 profile.",{"kind":"exact","value":template["profileId"]},["STANDARD","ENGINEERING"],template["profileId"],{"source":"normality_template","transform":"identity","jsonPointer":"/profileId"},"typed_identity")
    add("REQ.MATERIAL","material","Freeze 7075-T651 as material intent.",{"kind":"exact","value":"7075-T651"},["ENGINEERING"],"7075-T651",{"source":"contract","transform":"identity","jsonPointer":"/sources/1/description"},"exact_value")
    add("REQ.DIMENSIONS","dimensions","Freeze the controlled dimension vector.",{"kind":"exact","value":list(values.values()),"tolerance":0.000001},["ENGINEERING"],list(values.values()),{"source":"normality_instance","transform":"normality_parameters","parameterIds":list(values)},"formula")
    add("REQ.FEATURE_INTENT","overall_shape","Freeze the planned major-feature inventory.",{"kind":"set_contains","values":FEATURES},["USER","ENGINEERING"],FEATURES,{"source":"normality_template","transform":"identity","jsonPointer":"/majorFeatures"},"entity_query")
    add("REQ.LOCKS","safety","Keep review and packaging locks closed.",{"kind":"exact","value":True},["PREFLIGHT"],True,{"source":"normality_instance","transform":"all_review_locks_closed","jsonPointer":"/locks"},"entity_query")
    rows=[]
    for req in contract["requirements"]:
        observed,binding,method=evidence[req["id"]]
        rows.append({"requirementId":req["id"],"status":"satisfied","observed":observed,"actualBinding":binding,"evidence":[{"method":method,"sourcePath":f"prebuild-intent/{req['id']}","note":"Satisfied means source-bound prebuild intent; it does not assert generated geometry or manufacturing acceptance."}]})
    trace={"schema":"aicad_drawing_requirement_trace_v1","contractId":contract["contractId"],"contractSha256":canonical_sha(contract),"designIdentity":{"productType":template["productType"],"structureFamily":template["profileId"],"standard":template["closureSystem"]["standard"],"topClosure":template["closureSystem"]["top"],"bottomClosure":template["closureSystem"]["bottom"],"units":"mm"},"requirementEvidence":rows,"declaredMajorFeatures":FEATURES,"dimensionSources":[{"dimensionId":pid,"sourceId":"ENGINEERING","derivedFromImagePixels":False} for pid in values],"outputsPlanned":OUTPUTS,"locks":dict(LOCKS)}
    for name,payload in [("requirements.prebuild.contract.json",contract),("requirements.prebuild.trace.json",trace),("normality.template.json",template),("normality.instance.json",instance),("normality.plan.json",plan),("normality.geometry.json",geometry)]: dump(name,payload)

if __name__ == "__main__": build()
