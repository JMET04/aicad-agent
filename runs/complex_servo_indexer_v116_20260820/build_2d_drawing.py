from __future__ import annotations
import json, math
from pathlib import Path

RUN = Path(__file__).resolve().parent
REASON = "This drawing entity is source-dimensioned, origin-anchored and independently constrained for selectable review."

class Drawing:
    def __init__(self):
        self.steps = []
        self.points = {}

    def line(self, eid, p1, p2, layer, purpose, roles=("drawing",)):
        x1,y1=p1; x2,y2=p2; length=math.hypot(x2-x1,y2-y1)
        constraints=[{"kind":"start_offset","target":"origin","dx":x1,"dy":y1},{"kind":"length","value":length}]
        if abs(y2-y1)<1e-9: constraints.append({"kind":"horizontal"})
        if abs(x2-x1)<1e-9: constraints.append({"kind":"vertical"})
        self.steps.append({"id":eid,"type":"line","purpose":purpose,"reasoning":REASON,"start":{"point":[x1,y1]},"construction":{"kind":"vector","dx":x2-x1,"dy":y2-y1},"constraints":constraints,"layer":layer,"roles":list(roles),"editable":True})
        self.points[eid+".start"]=(x1,y1); self.points[eid+".end"]=(x2,y2)
        return eid

    def circle(self, eid, center, diameter, layer, purpose, roles=("drawing",)):
        x,y=center
        self.steps.append({"id":eid,"type":"circle","purpose":purpose,"reasoning":REASON,"center":{"point":[x,y]},"radius":diameter/2,"constraints":[{"kind":"center_offset","target":"origin","dx":x,"dy":y},{"kind":"diameter","value":diameter}],"layer":layer,"roles":list(roles),"editable":True})
        self.points[eid+".center"]=(x,y)
        return eid

    def rectangle(self, prefix, center, width, height, layer, purpose, roles=("drawing",)):
        x,y=center; l=x-width/2; r=x+width/2; b=y-height/2; t=y+height/2
        return [
            self.line(prefix+"B",(l,b),(r,b),layer,purpose,roles), self.line(prefix+"R",(r,b),(r,t),layer,purpose,roles),
            self.line(prefix+"T",(r,t),(l,t),layer,purpose,roles), self.line(prefix+"L",(l,t),(l,b),layer,purpose,roles),
        ]

    def text(self, eid, insert, value, height, purpose, layer="TEXT", rotation=0):
        x,y=insert
        self.steps.append({"id":eid,"type":"text","purpose":purpose,"reasoning":REASON,"insert":{"point":[x,y]},"value":value,"height":height,"rotation_deg":rotation,"constraints":[{"kind":"position_offset","target":"origin","dx":x,"dy":y},{"kind":"text_height","value":height},{"kind":"rotation","value":rotation}],"layer":layer,"roles":["annotation","review_selectable"],"editable":True})

    def dimension(self, eid, first_ref, second_ref, base, kind, purpose):
        p1=self.points[first_ref]; p2=self.points[second_ref]
        value=abs(p2[0]-p1[0]) if kind=="horizontal" else abs(p2[1]-p1[1])
        orientation=0 if kind=="horizontal" else 90
        self.steps.append({"id":eid,"type":"dimension","purpose":purpose,"reasoning":REASON,"first":{"ref":first_ref},"second":{"ref":second_ref},"base":{"point":list(base)},"dimension_kind":kind,"dimension_purpose":"overall" if "overall" in purpose else "general","style_name":"AICAD_MECH","constraints":[{"kind":"dimension_measurement","value":value},{"kind":"dimension_orientation","value":orientation},{"kind":"base_offset","target":first_ref,"dx":base[0]-p1[0],"dy":base[1]-p1[1]}],"layer":"DIMENSION","roles":["dimension","inspection_intent"],"editable":True})

def build():
    d=Drawing()
    d.line("TOP_CL_Y_HI",(0,0),(0,145),"CENTER","origin-anchored upper bearing-axis centreline",("centerline","datum_B"))
    # Top view, centred at (0, 40).
    d.rectangle("TOP_OUT_",(0,40),220,180,"OUTLINE","top-view outer base contour",("outline","datum_A"))
    for eid,diam,purpose in [("TOP_BOSS",130,"bearing boss OD"),("TOP_SEAL",92,"seal recess"),("TOP_SEAT",80,"bearing seat"),("TOP_SHAFT",50,"shaft clearance")]:
        d.circle(eid,(0,40),diam,"OUTLINE" if eid=="TOP_BOSS" else "HOLE",purpose,("circular_feature","interface"))
    d.circle("TOP_PCD108",(0,40),108,"CENTER","indexer pitch circle",("construction","pcd"))
    d.circle("TOP_PCD104",(0,40),104,"CENTER","cover pitch circle",("construction","pcd"))
    for i in range(8):
        a=math.radians(22.5+i*45); d.circle(f"IDX_{i+1:02d}",(54*math.cos(a),40+54*math.sin(a)),9,"HOLE",f"indexer mounting hole {i+1}",( "hole","indexer_pattern"))
    for i in range(4):
        a=math.radians(45+i*90); d.circle(f"COV_{i+1:02d}",(52*math.cos(a),40+52*math.sin(a)),7,"HOLE",f"cover mounting hole {i+1}",( "hole","cover_pattern"))
    frame=[(85,105),(-85,105),(-85,-25),(85,-25)]
    for i,p in enumerate(frame,1):
        d.circle(f"FRM_CB_{i}",p,24,"OUTLINE",f"frame counterbore {i}",( "counterbore","frame_interface"))
        d.circle(f"FRM_H_{i}",p,14,"HOLE",f"frame through hole {i}",( "hole","frame_interface"))
    for i,p in enumerate([(70,40),(-70,40)],1): d.circle(f"DOWEL_{i}",p,8,"HOLE",f"H7 dowel hole {i}",( "hole","datum_C"))
    for i,(x,y) in enumerate([(86,70),(-86,70),(-86,10),(86,10)],1): d.rectangle(f"PKT{i}_",(x,y),36,34,"OUTLINE",f"lightening pocket {i}",( "pocket","non_through"))
    for i,(x,y,w,h) in enumerate([(48,40,42,72),(-48,40,42,72),(0,88,72,42),(0,-8,72,42)],1): d.rectangle(f"RIB{i}_",(x,y),w,h,"HIDDEN",f"rib pad projection {i}",( "rib","hidden_overlap"))
    d.line("TOP_CL_X",(-125,40),(125,40),"CENTER","top-view horizontal centreline",("centerline","datum_B"))
    d.line("TOP_CL_Y_LO",(0,0),(0,-65),"CENTER","lower bearing-axis centreline",("centerline","datum_B"))
    d.dimension("DIM_TOP_W","TOP_OUT_B.start","TOP_OUT_B.end",(-110,-62),"horizontal","overall base width 220")
    d.dimension("DIM_TOP_H","TOP_OUT_L.start","TOP_OUT_L.end",(-132,-50),"vertical","overall base height 180")
    d.dimension("DIM_FRAME_X","FRM_H_2.center","FRM_H_1.center",(-85,137),"horizontal","frame hole spacing 170")
    d.dimension("DIM_FRAME_Y","FRM_H_4.center","FRM_H_1.center",(128,-25),"vertical","frame hole spacing 130")
    d.dimension("DIM_DOWEL","DOWEL_2.center","DOWEL_1.center",(-70,151),"horizontal","dowel centre spacing 140")
    d.rectangle("VIEW_TOP_TAG_",(-25,158),110,14,"TITLE","framed top-view label",("view_label_frame",))
    d.text("TOP_LABEL",(-25,158),"TOP VIEW / 俯视图",6,"top view title")
    d.rectangle("TOP_INFO_",(230,60),140,90,"TITLE","framed top-view feature callouts",("feature_callout_frame",))
    for index,y in enumerate((87,69,51,33),1): d.line(f"TOP_INFO_H{index}",(160,y),(300,y),"TITLE","feature callout row divider",("feature_callout_frame",))
    d.text("CALLOUT_BOSS",(230,96),"BOSS Ø130",4,"boss diameter callout")
    d.text("CALLOUT_SEAT",(230,78),"Ø80 H7 × 36 DEEP",4,"bearing seat callout")
    d.text("CALLOUT_SEAL",(230,60),"Ø92 H8 × 6 DEEP",4,"seal recess callout")
    d.text("CALLOUT_IDX",(230,42),"8×Ø9 EQ SP ON Ø108 PCD, START 22.5°",4,"indexer pattern callout")
    d.text("CALLOUT_COV",(230,24),"4×Ø7 EQ SP ON Ø104 PCD, START 45°",4,"cover pattern callout")

    # Section A-A beneath the top view.
    yb,yt,zb=-230,-210,-174
    d.line("SEC_BOTTOM",(-110,yb),(110,yb),"OUTLINE","section base bottom",("section","datum_A"))
    d.line("SEC_BASE_L",(-110,yb),(-110,yt),"OUTLINE","section base left edge",("section","outline"))
    d.line("SEC_BASE_R",(110,yb),(110,yt),"OUTLINE","section base right edge",("section","outline"))
    d.line("SEC_TOP_L",(-110,yt),(-65,yt),"OUTLINE","section base top left land",("section","outline"))
    d.line("SEC_TOP_R",(65,yt),(110,yt),"OUTLINE","section base top right land",("section","outline"))
    d.line("SEC_BOSS_L",(-65,yt),(-65,zb),"OUTLINE","section boss left wall",("section","bearing_boss"))
    d.line("SEC_BOSS_R",(65,zb),(65,yt),"OUTLINE","section boss right wall",("section","bearing_boss"))
    d.line("SEC_BOSS_TOP_L",(-65,zb),(-46,zb),"OUTLINE","section boss top left land",("section","outline"))
    d.line("SEC_BOSS_TOP_R",(46,zb),(65,zb),"OUTLINE","section boss top right land",("section","outline"))
    d.line("SEC_SEAL_L",(-46,zb),(-46,-180),"OUTLINE","seal recess left wall",("section","seal_recess"))
    d.line("SEC_SEAL_R",(46,-180),(46,zb),"OUTLINE","seal recess right wall",("section","seal_recess"))
    d.line("SEC_SEAL_FLOOR_L",(-46,-180),(-40,-180),"OUTLINE","seal floor left",("section","seal_recess"))
    d.line("SEC_SEAL_FLOOR_R",(40,-180),(46,-180),"OUTLINE","seal floor right",("section","seal_recess"))
    d.line("SEC_SEAT_L",(-40,-180),(-40,yt),"OUTLINE","bearing seat left wall",("section","bearing_seat"))
    d.line("SEC_SEAT_R",(40,yt),(40,-180),"OUTLINE","bearing seat right wall",("section","bearing_seat"))
    d.line("SEC_SEAT_FLOOR_L",(-40,yt),(-25,yt),"OUTLINE","bearing seat shoulder left",("section","bearing_seat"))
    d.line("SEC_SEAT_FLOOR_R",(25,yt),(40,yt),"OUTLINE","bearing seat shoulder right",("section","bearing_seat"))
    d.line("SEC_SHAFT_L",(-25,zb),(-25,yb),"OUTLINE","shaft bore left wall",("section","shaft_clearance"))
    d.line("SEC_SHAFT_R",(25,yb),(25,zb),"OUTLINE","shaft bore right wall",("section","shaft_clearance"))
    d.line("SEC_CL",(0,-238),(0,-166),"CENTER","section bearing axis",("centerline","datum_B"))
    for i,x in enumerate(range(-105,-66,10),1): d.line(f"HATCH_BL_{i}",(x,yb+2),(x+15,yt-2),"HATCH","base section hatch",("hatch",))
    for i,x in enumerate(range(70,106,10),1): d.line(f"HATCH_BR_{i}",(x-15,yt-2),(x,yb+2),"HATCH","base section hatch",("hatch",))
    for i,x in enumerate([-62,-55,-48,48,55,62],1): d.line(f"HATCH_BOSS_{i}",(x,yt+2),(x+5 if x<0 else x-5,zb-2),"HATCH","boss section hatch",("hatch",))
    d.dimension("DIM_TOTAL_H","SEC_BOTTOM.start","SEC_BOSS_L.end",(-142,yb),"vertical","overall height 56")
    d.dimension("DIM_BASE_T","SEC_BASE_R.start","SEC_BASE_R.end",(128,yb),"vertical","base thickness 20")
    d.dimension("DIM_BOSS_H","SEC_BOSS_L.start","SEC_BOSS_L.end",(-126,yt),"vertical","boss height 36")
    d.dimension("DIM_SEAL_D","SEC_SEAL_L.start","SEC_SEAL_L.end",(-55,zb),"vertical","seal recess depth 6")
    d.rectangle("VIEW_SEC_TAG_",(-35,-158),150,14,"TITLE","framed section-view label",("view_label_frame",))
    d.text("SEC_LABEL",(-35,-158),"SECTION A-A / A-A剖视图",6,"section view title")
    d.rectangle("SEC_INFO_",(0,-250),220,14,"TITLE","framed section feature note",("feature_callout_frame",))
    d.text("SEC_NOTE",(0,-250),"BEARING SEAT: Ø80 H7 ; SHAFT BORE: Ø50 THRU",4,"section feature note")

    # Right-side view.
    d.rectangle("SIDE_BASE_",(220,-220),180,20,"OUTLINE","right-side base projection",("side_view","outline"))
    d.rectangle("SIDE_BOSS_",(220,-192),130,36,"OUTLINE","right-side boss projection",("side_view","bearing_boss"))
    d.line("SIDE_CL",(220,-238),(220,-166),"CENTER","right-view centreline",("centerline","datum_B"))
    d.line("SIDE_HID_L",(180,-230),(180,-174),"HIDDEN","bearing seat hidden left wall",("hidden","bearing_seat"))
    d.line("SIDE_HID_R",(260,-174),(260,-230),"HIDDEN","bearing seat hidden right wall",("hidden","bearing_seat"))
    d.rectangle("VIEW_SIDE_TAG_",(220,-158),140,14,"TITLE","framed right-view label",("view_label_frame",))
    d.text("SIDE_LABEL",(220,-158),"RIGHT VIEW / 右视图",6,"right view title")

    # Title block and controlled notes.
    d.rectangle("TB_OUT_",(75,-300),450,60,"TITLE","drawing title block",("title_block",))
    d.line("TB_V1",(-40,-330),(-40,-270),"TITLE","title block divider",("title_block",))
    d.line("TB_V2",(180,-330),(180,-270),"TITLE","title block divider",("title_block",))
    d.line("TB_H1",(-150,-300),(300,-300),"TITLE","title block horizontal divider",("title_block",))
    d.text("TB_TITLE",(70,-285),"SIFC-220 HIGH-STIFFNESS SERVO INDEXER FLANGE CARTRIDGE",5,"drawing title")
    d.text("TB_ID",(-95,-285),"PART: SIFC-220-REV-A",4,"part identifier")
    d.text("TB_SCALE",(-95,-315),"UNITS: mm   SCALE: REVIEW FIT",4,"units and scale")
    d.text("TB_MAT",(70,-315),"MATERIAL: 7075-T651   FINISH: HARD ANODIZE 25±5 μm",4,"material and finish")
    d.text("TB_STATUS",(240,-285),"STATUS: REVIEW ONLY",4,"review status")
    d.text("TB_LOCK",(240,-315),"NOT ACCEPTED / NOT RELEASED",4,"safety lock")
    d.rectangle("NOTES_OUT_",(75,-361),450,48,"TITLE","framed controlled general notes",("notes_frame",))
    for index,y in enumerate((-346.6,-356.2,-365.8,-375.4),1): d.line(f"NOTES_H{index}",(-150,y),(300,y),"TITLE","general note row divider",("notes_frame",))
    d.text("NOTE1",(75,-341.8),"1. DATUM A: BASE BOTTOM; DATUM B: BEARING AXIS; DATUM C: PRIMARY Ø8 H7 DOWEL.",3.2,"datum note")
    d.text("NOTE2",(75,-351.4),"2. BREAK SHARP EDGES 0.2–0.5 AND DEBURR; NATIVE FILLET/CHAMFER NOT CLAIMED.",3.2,"edge note")
    d.text("NOTE3",(75,-361),"3. MASK Ø80 H7, Ø92 H8, Ø8 H7 AND DATUM A DURING ANODIZE.",3.2,"finish masking note")
    d.text("NOTE4",(75,-370.6),"4. INSPECT DATUM A FLATNESS 0.03; Ø80 AXIS POSITION/COAXIALITY TO B PER CONTROL PLAN.",3.2,"inspection note")
    d.text("NOTE5",(75,-380.2),"5. THIS DRAWING IS A CONTROLLED AI REVIEW CANDIDATE, NOT MANUFACTURING RELEASE.",3.2,"release boundary note")

    plan={
        "schema_version":"2.0",
        "drawing":{"name":"SIFC_220_REV_A_MANUFACTURING_REVIEW","id":"SIFC220REVA2D","domain":"mechanical","units":"mm","origin":[0,0],"tolerance":0.000001,"locks":["review_only","not_accepted","not_manufacturing_release"],"review_policy":{"reviewOnly":True,"accepted":False,"ruleEnabled":False,"domainGated":True}},
        "engineering_normative_preflight":json.loads((RUN/"mechanical-preflight.json").read_text(encoding="utf-8")),
        "steps":d.steps,
    }
    (RUN/"SIFC_220_REV_A.2d.plan.json").write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__": build()
