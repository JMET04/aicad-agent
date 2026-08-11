from __future__ import annotations

import html
import json
import math
from typing import Any


_SCOPE_LABELS = {
    "authoritative_2d_geometry": "二维原始几何",
    "feature_profiles_before_final_visibility": "特征轮廓（用于检查与选择）",
    "feature_operation_extents": "特征高度与支撑关系",
    "selectable_feature_extent_proxy": "可旋转三维语义选择",
    "feature_operation_section": "特征运算截面（审查用途）",
}


def _bounds(entities: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for entity in entities:
        geometry = entity["geometry"]
        kind = geometry["type"]
        if kind == "line":
            xs.extend((float(geometry["start"][0]), float(geometry["end"][0])))
            ys.extend((float(geometry["start"][1]), float(geometry["end"][1])))
        elif kind == "circle":
            cx, cy = geometry["center"]
            radius = float(geometry["radius"])
            xs.extend((cx - radius, cx + radius))
            ys.extend((cy - radius, cy + radius))
        elif kind == "point":
            xs.append(float(geometry["point"][0]))
            ys.append(float(geometry["point"][1]))
    if not xs:
        return -5.0, -5.0, 5.0, 5.0
    width = max(max(xs) - min(xs), 1.0)
    height = max(max(ys) - min(ys), 1.0)
    margin = max(width, height) * 0.08
    return min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin


def _line_hit(start: list[float], end: list[float], pad: float) -> str:
    x1, y1 = map(float, start)
    x2, y2 = map(float, end)
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length * pad, dx / length * pad
    return " ".join(
        f"{x:.9g},{y:.9g}"
        for x, y in ((x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny))
    )


def _coordinate_triad_svg(view: dict[str, Any], left: float, bottom: float, width: float, height: float) -> str:
    ox = left + width * 0.085
    oy = -bottom - height * 0.105
    scale = max(width, height) * 0.065
    if view["kind"] == "isometric":
        angle = math.radians(30.0)
        vectors = (
            ("X", math.cos(angle), -math.sin(angle), "#c9362b"),
            ("Y", -math.cos(angle), -math.sin(angle), "#2f6f54"),
            ("Z", 0.0, -1.0, "#2563eb"),
        )
    else:
        horizontal, vertical = (list(view["axes"]) + ["u", "v"])[:2]
        vectors = (
            (str(horizontal).upper(), 1.0, 0.0, "#c9362b"),
            (str(vertical).upper(), 0.0, -1.0, "#2f6f54"),
        )
    rows = [f'<circle cx="{ox:.9g}" cy="{oy:.9g}" r="{scale * .055:.9g}" class="triad-origin"/>']
    for label, dx, dy, color in vectors:
        ex, ey = ox + dx * scale, oy + dy * scale
        rows.append(
            f'<line x1="{ox:.9g}" y1="{oy:.9g}" x2="{ex:.9g}" y2="{ey:.9g}" '
            f'style="stroke:{color}"/><circle cx="{ex:.9g}" cy="{ey:.9g}" r="{scale * .045:.9g}" '
            f'style="fill:{color}"/><text x="{ex + dx * scale * .13:.9g}" y="{ey + dy * scale * .13:.9g}" '
            f'style="fill:{color}">{html.escape(label)}</text>'
        )
    return (
        f'<g class="view-coordinate-triad" data-coordinate-system="MODEL_XYZ" '
        f'aria-label="模型坐标系">{"".join(rows)}</g>'
    )


def _svg(view: dict[str, Any]) -> str:
    left, bottom, right, top = _bounds(view["entities"])
    width, height = right - left, top - bottom
    pad = max(width, height) * 0.012
    rows: list[str] = []
    for entity in view["entities"]:
        geometry = entity["geometry"]
        classes = ["entity-pair"]
        if entity.get("key_geometry"):
            classes.append("key-geometry")
        attrs = (
            f'data-view-entity-id="{html.escape(entity["id"])}" '
            f'data-source-id="{html.escape(entity["source_object_id"])}" '
            f'data-source-subobject="{html.escape(entity["source_subobject"])}"'
        )
        role = html.escape(entity["role"])
        visible_class = f'view-entity role-{role}' + (" derived" if entity["derived"] else "")
        kind = geometry["type"]
        if kind == "line":
            x1, y1 = geometry["start"]
            x2, y2 = geometry["end"]
            hit = f'<polygon class="view-hit" points="{_line_hit(geometry["start"], geometry["end"], pad)}" {attrs}/>'
            visible = f'<line class="{visible_class}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>'
        elif kind == "circle":
            cx, cy = geometry["center"]
            radius = geometry["radius"]
            hit = f'<circle class="view-hit" cx="{cx}" cy="{cy}" r="{radius}" {attrs}/>'
            visible = f'<circle class="{visible_class}" cx="{cx}" cy="{cy}" r="{radius}"/>'
        else:
            cx, cy = geometry["point"]
            size = max(width, height) * 0.018
            hit = f'<circle class="view-hit point-hit" cx="{cx}" cy="{cy}" r="{size * 1.8}" {attrs}/>'
            visible = (
                f'<g class="{visible_class} point-mark"><line x1="{cx-size}" y1="{cy}" x2="{cx+size}" y2="{cy}"/>'
                f'<line x1="{cx}" y1="{cy-size}" x2="{cx}" y2="{cy+size}"/>'
                f'<circle cx="{cx}" cy="{cy}" r="{size * .34}"/></g>'
            )
        rows.append(f'<g class="{" ".join(classes)}">{hit}{visible}</g>')
    content = "".join(rows)
    triad = _coordinate_triad_svg(view, left, bottom, width, height)
    origin_size = max(width, height) * 0.012
    origin_marker = (
        f'<g class="model-origin-marker" data-coordinate-system="MODEL_XYZ">'
        f'<line x1="{-origin_size:.9g}" y1="0" x2="{origin_size:.9g}" y2="0"/>'
        f'<line x1="0" y1="{-origin_size:.9g}" x2="0" y2="{origin_size:.9g}"/>'
        f'<circle cx="0" cy="0" r="{origin_size * .32:.9g}"/></g>'
    )
    # Flip model geometry so positive CAD Y grows upward; keep the viewport triad upright.
    return (
        f'<svg class="cad-view" viewBox="{left} {-top} {width} {height}" preserveAspectRatio="xMidYMid meet" '
        f'aria-label="{html.escape(view["label"])}"><g transform="scale(1,-1)">{origin_marker}{content}</g>{triad}</svg>'
    )


def _interaction_script() -> str:
    return r"""
const objects=new Map(pkg.semantic_document.objects.map(x=>[x.id,x]));
const selectorObjects=new Map((pkg.selector_3d?.objects||[]).map(x=>[x.source_object_id,x]));
let selectedRefs=[],selected=[],operations=[],instructions=[],transactionRefs=new Map(),coordinateVisible=true;
const referenceKey=r=>r?.reference_key||`${r?.source_object_id}|${r?.source_subobject}`;
const selectedReferenceKeys=()=>new Set(selectedRefs.map(referenceKey));
const exactRef=r=>!!(r&&r.reference_key&&r.edit_scope);
const compactRef=r=>({source_object_id:r.source_object_id,source_subobject:r.source_subobject,reference_key:referenceKey(r),geometry_type:r.geometry_type,edit_paths:r.edit_paths||[]});
const pathLabels={'profile.center':'中心坐标','profile.width':'宽度','profile.height':'高度','profile.radius':'半径','profile.count':'阵列数量','profile.bolt_circle_radius':'分布圆半径','profile.start_angle_deg':'起始角','depth':'深度'};
const relationLabels={parallel:'平行',perpendicular:'垂直',collinear:'共线',equal_length:'等长',concentric:'同心',equal_radius:'等半径',coincident:'重合',offset:'偏移'};
const preserveLabels={keep_center:'保持中心',keep_opposite:'保持对边',keep_size:'保持尺寸',keep_support:'保持支撑面'};
function syncSelected(){selected=[...new Set(selectedRefs.map(r=>r.source_object_id))];}
function remember(r){transactionRefs.set(referenceKey(r),compactRef(r));}
function toggleSelectionRef(raw){if(!raw)return;const r={...raw,reference_key:referenceKey(raw)},key=referenceKey(r),i=selectedRefs.findIndex(x=>referenceKey(x)===key);if(i>=0)selectedRefs.splice(i,1);else{if(selectedRefs.length===2)selectedRefs.shift();selectedRefs.push(r);}syncSelected();primeSelectedMeasurementEditor();renderUi();}
function scopeFields(r){const shared=r.edit_scope==='shared_pattern_parameter',value={scope:shared?'shared_parameter_group':(r.edit_scope==='subobject_parameterized'?'subobject':'feature'),expected_affected_instance_count:r.affected_instance_count||1};if(shared)value.expected_shared_parameter_groups=r.shared_parameter_groups||[];return value;}
function preservePolicy(){return document.getElementById('preserve').value;}
function relationOptions(){
  if(selectedRefs.length!==2||!selectedRefs.every(exactRef))return[];
  const [a,b]=selectedRefs;if(a.geometry_type!==b.geometry_type)return[];
  const defaults={line:['parallel','perpendicular','collinear','equal_length'],circle:['concentric','equal_radius'],face:['parallel','perpendicular','coincident','offset'],point:['coincident']};
  const aa=a.relation_capabilities??defaults[a.geometry_type]??[],bb=b.relation_capabilities??defaults[b.geometry_type]??[];
  return aa.filter(x=>bb.includes(x));
}
function movableRef(refs){const order=new Map(pkg.semantic_document.objects.map((x,i)=>[x.id,i]));return [...refs].sort((a,b)=>(order.get(a.source_object_id)-order.get(b.source_object_id))||referenceKey(a).localeCompare(referenceKey(b)))[1];}
function operationSummary(op){
  if(op.op==='set_subobject_parameter')return `${op.reference_key.split('|')[0]} · ${pathLabels[op.path]||op.path} → ${Array.isArray(op.value)?op.value.join(', '):op.value}`;
  if(op.op==='move_subobject')return `${op.reference_key.split('|')[0]} · 沿 ${op.axis.toUpperCase()} ${op.value_mode==='delta'?'移动':'定位'}到 ${op.value}`;
  return `${op.members.map(x=>x.split('|')[0]).join(' ↔ ')} · ${relationLabels[op.relation]||op.relation}`;
}
function renderSelection(){
  const node=document.getElementById('selection');
  if(!selectedRefs.length){node.innerHTML='<span class="muted">点选线、面、中心或参数开始修改</span>';return;}
  node.innerHTML=selectedRefs.map(r=>`<div class="selection-chip"><b>${r.source_object_id}</b><span>${friendlySubobject(r.source_subobject)}</span><small>${r.derived?'关联几何':'原始几何'} · ${r.affected_instance_count>1?`影响 ${r.affected_instance_count} 个阵列实例`:'单一特征'}</small></div>`).join('');
}
function friendlySubobject(value){return value.replace('profile.center','几何中心').replace('profile.pattern.pitch_circle','阵列分布圆').replace('feature.axis.center.xz','主视中心轴').replace('feature.axis.center.yz','右视中心轴').replace('profile.edge.','轮廓边 ').replace('profile.circle.','轮廓圆 ').replace('feature.face.','特征面 ').replace('feature.edge.','交界边 ');}
function formatMeasure(value,digits=3){if(value===null||value===undefined||!Number.isFinite(Number(value)))return '—';const n=Number(value);return Math.abs(n)<1e-12?'0':String(Number(n.toFixed(digits)));}
function coordinateGrid(values,label){const v=values||[null,null,null];return `<div class="coordinate-label">${label}</div><div class="coordinate-grid">${['X','Y','Z'].map((axis,i)=>`<span><b>${axis}</b><strong>${formatMeasure(v[i])}</strong><i>mm</i></span>`).join('')}</div>`;}
function measurementAuthority(value){return ({model_semantic:'编译模型真值',authoritative_2d:'二维模型真值',orthographic_projection:'正投影语义值',isometric_projection:'等轴投影辅助值'})[value]||value;}
function editMeasuredValue(ref){const m=ref?.measurement;if(!m?.controller_path||m.controller_value===undefined)return;const select=document.getElementById('parameterPath'),input=document.getElementById('parameterValue');input.dataset.param='';populatePath();if(![...select.options].some(x=>x.value===m.controller_path))return showToast('该测量值当前只读');select.value=m.controller_path;input.value=Array.isArray(m.controller_value)?m.controller_value.join(', '):m.controller_value;document.getElementById('quickEditor').classList.add('attention');setTimeout(()=>document.getElementById('quickEditor').classList.remove('attention'),650);input.focus();}
function primeSelectedMeasurementEditor(){const input=document.getElementById('parameterValue'),select=document.getElementById('parameterPath'),r=selectedRefs.length===1?selectedRefs[0]:null,m=r?.measurement;input.dataset.param='';populatePath();if(!m?.controller_path||m.controller_value===undefined||![...select.options].some(x=>x.value===m.controller_path)){input.value='';return;}select.value=m.controller_path;input.value=Array.isArray(m.controller_value)?m.controller_value.join(', '):m.controller_value;}
function renderMeasurements(){
  const host=document.getElementById('measurement');
  if(!selectedRefs.length){host.innerHTML='<span class="muted">点一条线查看长度，点一个点查看坐标，点一个圆查看半径。</span>';return;}
  host.innerHTML=selectedRefs.map((r,index)=>{const m=r.measurement;if(!m)return `<article class="measurement-card"><b>暂无可证明的模型测量值</b></article>`;let primary='',details='';
    if(m.kind==='line'){primary=`<button class="metric-primary" ${m.controller_path?'data-editable="true"':''}><span>长度</span><strong>${formatMeasure(m.length_mm)} <i>mm</i></strong></button>`;details=coordinateGrid(m.start,'起点')+coordinateGrid(m.end,'终点');}
    else if(m.kind==='point'){primary=`<button class="metric-primary" ${m.controller_path?'data-editable="true"':''}><span>点坐标</span><strong>X / Y / Z</strong></button>`;details=coordinateGrid(m.coordinates,'模型坐标');}
    else if(m.kind==='circle'){primary=`<button class="metric-primary" ${m.controller_path?'data-editable="true"':''}><span>半径 R</span><strong>${formatMeasure(m.radius_mm)} <i>mm</i></strong></button><div class="metric-secondary"><span>直径 Ø</span><b>${formatMeasure(m.diameter_mm)} mm</b></div>`;details=coordinateGrid(m.center,'圆心');}
    else{primary=`<div class="metric-primary"><span>面积</span><strong>${formatMeasure(m.area_mm2)} <i>mm²</i></strong></div>`;details=m.center?coordinateGrid(m.center,'几何中心'):'';}
    return `<article class="measurement-card" data-measurement-kind="${m.kind}" data-index="${index}"><header><b>${r.source_object_id} · ${friendlySubobject(r.source_subobject)}</b><span>${measurementAuthority(m.authority)}</span></header>${primary}${details}${m.note?`<p>${m.note}</p>`:''}</article>`;
  }).join('');
  host.querySelectorAll('.measurement-card').forEach(card=>{const button=card.querySelector('[data-editable]');if(button)button.onclick=()=>editMeasuredValue(selectedRefs[Number(card.dataset.index)]);});
}
function setCoordinateVisible(value){coordinateVisible=!!value;window.__aicadCoordinateVisible=coordinateVisible;document.body.classList.toggle('coordinates-hidden',!coordinateVisible);const toggle=document.getElementById('coordinateToggle');if(toggle){toggle.checked=coordinateVisible;toggle.setAttribute('aria-checked',String(coordinateVisible));}if(window.drawAicad3d)window.drawAicad3d();}
function renderParameters(){
  const host=document.getElementById('coreParameters');
  host.innerHTML=[...selectorObjects.values()].map(o=>`<section class="parameter-group ${selected.includes(o.source_object_id)?'active':''}"><header><b>${o.source_object_id}</b><span>${featureLabel(o.feature_type)}</span></header><div>${(o.core_parameters||[]).map(p=>`<button class="parameter-row" data-feature="${o.source_object_id}" data-param="${p.id}"><span>${p.label}</span><strong>${Array.isArray(p.value)?p.value.join(', '):p.value}${p.unit?` <i>${p.unit}</i>`:''}</strong></button>`).join('')}</div></section>`).join('');
  host.querySelectorAll('.parameter-row').forEach(button=>button.onclick=()=>selectParameter(button.dataset.feature,button.dataset.param));
}
function featureLabel(type){return ({base_extrude:'基础拉伸',boss_extrude:'凸台拉伸',cut_extrude:'切除拉伸'})[type]||type;}
function selectParameter(featureId,paramId){
  const o=selectorObjects.get(featureId),p=(o.core_parameters||[]).find(x=>x.id===paramId);if(!p)return;
  const ref=p.selection_id?pkg.selection_map[p.selection_id]:null;if(ref){selectedRefs=[{...ref,reference_key:referenceKey(ref)}];syncSelected();}
  const path=document.getElementById('parameterPath');path.innerHTML=`<option value="${p.path}">${p.label}</option>`;path.value=p.path;
  const input=document.getElementById('parameterValue');input.value=Array.isArray(p.value)?p.value.join(', '):p.value;input.dataset.feature=featureId;input.dataset.param=paramId;input.dataset.component=p.component??'';
  document.getElementById('quickEditor').classList.add('attention');setTimeout(()=>document.getElementById('quickEditor').classList.remove('attention'),650);input.focus();renderUi(false);
}
function populatePath(){
  const select=document.getElementById('parameterPath'),r=selectedRefs.length===1?selectedRefs[0]:null,old=select.value,paths=r?.edit_paths||[];
  if(document.activeElement===select||document.getElementById('parameterValue').dataset.param)return;
  select.innerHTML=paths.map(x=>`<option value="${x}">${pathLabels[x]||x}</option>`).join('');if(paths.includes(old))select.value=old;
}
function addOperation(operation,refs){if(!refs.every(exactRef)){showToast('请先选择高亮后可精确引用的几何或核心参数');return false;}refs.forEach(remember);operations.push(operation);renderChanges();return true;}
function commitParameter(){
  if(selectedRefs.length!==1)return showToast('先选择一个几何或参数');
  const r=selectedRefs[0],path=document.getElementById('parameterPath').value,input=document.getElementById('parameterValue'),raw=input.value.trim();if(!path||!raw)return;
  let value;if(path==='profile.center'){value=raw.split(/[,，\s]+/).filter(Boolean).map(Number);if(value.length!==2||value.some(x=>!Number.isFinite(x)))return showToast('中心坐标请输入 X, Y');}else{value=Number(raw);if(!Number.isFinite(value))return showToast('请输入有效数字');}
  const op={op:'set_subobject_parameter',reference_key:referenceKey(r),path,value,...scopeFields(r)};if(['profile.width','profile.height','depth'].includes(path))op.preserve_policy=preservePolicy();
  if(addOperation(op,[r])){const o=selectorObjects.get(r.source_object_id),p=(o?.core_parameters||[]).find(x=>x.path===path&&!x.component);if(p)p.value=value;input.dataset.param='';renderUi();}
}
function commitMove(){
  if(selectedRefs.length!==1)return showToast('先选择一条边或一个面');const r=selectedRefs[0];
  const op={op:'move_subobject',reference_key:referenceKey(r),axis:document.getElementById('moveAxis').value,value:Number(document.getElementById('moveValue').value),value_mode:document.getElementById('valueMode').value,preserve_policy:preservePolicy(),...scopeFields(r)};addOperation(op,[r]);
}
function addInstruction(){const input=document.getElementById('aiInstruction'),text=input.value.trim();if(!text)return;instructions.push({text,selected_refs:selectedRefs.map(compactRef)});input.value='';renderChanges();}
function renderRelations(){const host=document.getElementById('relations'),options=relationOptions();host.innerHTML=options.length?options.map(x=>`<button data-relation="${x}">${relationLabels[x]||x}</button>`).join(''):'<span class="muted">选择两个兼容对象后自动出现可用关系</span>';host.querySelectorAll('button').forEach(button=>button.onclick=()=>{const relation=button.dataset.relation,movable=movableRef(selectedRefs),op={op:'add_subobject_relation',relation,members:selectedRefs.map(referenceKey),...scopeFields(movable)};if(['collinear','equal_length','coincident','offset'].includes(relation))op.preserve_policy=preservePolicy();if(relation==='offset')op.offset=Number(document.getElementById('offsetValue').value||0);addOperation(op,selectedRefs);});}
function formalCorrection(){const refs=[...transactionRefs.values()],ids=[...new Set(refs.map(r=>r.source_object_id))].sort();return{schema_version:'1.0',source_sha256:pkg.source_sha256,correction:{id:'UI_CORR_001',description:instructions.map(x=>x.text).join('；')||'由修改器生成的精确修改',space:pkg.space,selected_ids:ids,selected_refs:refs,operations:[...operations]},root_cause:{status:'candidate',cause_class:'interactive_review'},prevention_rule:{status:'candidate',ruleEnabled:false,requirement:'修改后重放依赖并复核相同几何不变量'},review_policy:{reviewOnly:true,accepted:false,ruleEnabled:false}};}
function handoff(){return{handoff_schema_version:'1.0',source_sha256:pkg.source_sha256,instructions,exact_transaction:operations.length?formalCorrection():null,agent_action:'将自然语言合并为精确事务，约束求解通过后再预览',review_policy:{reviewOnly:true,accepted:false,ruleEnabled:false}};}
function renderChanges(){
  const host=document.getElementById('changeList'),rows=[...operations.map((op,i)=>({kind:'operation',i,text:operationSummary(op)})),...instructions.map((n,i)=>({kind:'instruction',i,text:`告诉 AI：${n.text}`}))];
  host.innerHTML=rows.length?rows.map(x=>`<div class="change-row"><span>${x.text}</span><button data-kind="${x.kind}" data-index="${x.i}" aria-label="删除">×</button></div>`).join(''):'<span class="muted">尚无修改。选择对象、改数值，或直接告诉 AI。</span>';
  host.querySelectorAll('button').forEach(b=>b.onclick=()=>{(b.dataset.kind==='operation'?operations:instructions).splice(Number(b.dataset.index),1);renderChanges();});
  document.getElementById('advancedJson').textContent=JSON.stringify(handoff(),null,2);
  document.getElementById('changeCount').textContent=String(rows.length);
}
function exportHandoff(){const blob=new Blob([JSON.stringify(handoff(),null,2)],{type:'application/json;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='aicad-agent-change-request.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);showToast('修改请求已导出；内部精确事务保留在高级信息中');}
function renderUi(redraw=true){
  const keys=selectedReferenceKeys();document.querySelectorAll('.view-hit').forEach(x=>{const pair=x.closest('.entity-pair'),key=`${x.dataset.sourceId}|${x.dataset.sourceSubobject}`;pair?.classList.toggle('selected',keys.has(key));pair?.classList.toggle('context-selected',!keys.has(key)&&selected.includes(x.dataset.sourceId));});
  renderSelection();renderMeasurements();renderParameters();renderRelations();populatePath();if(redraw&&window.drawAicad3d)window.drawAicad3d();
}
function showToast(text){const n=document.getElementById('toast');n.textContent=text;n.classList.add('show');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>n.classList.remove('show'),2200);}
document.querySelectorAll('.view-hit').forEach(x=>x.onclick=e=>{e.stopPropagation();toggleSelectionRef(pkg.selection_map[x.dataset.viewEntityId]);});
document.getElementById('setParameter').onclick=commitParameter;document.getElementById('addMove').onclick=commitMove;document.getElementById('addInstruction').onclick=addInstruction;document.getElementById('exportRequest').onclick=exportHandoff;document.getElementById('coordinateToggle').onchange=e=>setCoordinateVisible(e.target.checked);setCoordinateVisible(true);
window.__aicadUi={get selectedRefs(){return selectedRefs},get operations(){return operations},get instructions(){return instructions},get coordinateVisible(){return coordinateVisible},toggleSelectionRef,selectParameter,formalCorrection,handoff,renderUi,setCoordinateVisible};
"""


def _section_script() -> str:
    return r"""
function initFreeSection(){
  const canvas=document.getElementById('freeSectionCanvas'),ctx=canvas.getContext('2d');let plane={n:[1,0,0],p:[0,0,0]},hits=[],hover=-1;
  const vadd=(a,b)=>a.map((x,i)=>x+b[i]),vsub=(a,b)=>a.map((x,i)=>x-b[i]),vmul=(a,s)=>a.map(x=>x*s),dot=(a,b)=>a.reduce((s,x,i)=>s+x*b[i],0),cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],norm=a=>Math.hypot(...a),unit=a=>{const n=norm(a)||1;return a.map(x=>x/n)};
  function triangleSection(tri,n,p){const d=tri.map(v=>dot(n,vsub(v,p))),out=[];for(const [i,j] of [[0,1],[1,2],[2,0]]){const a=d[i],b=d[j];if(Math.abs(a)<1e-8)out.push(tri[i]);if(a*b<0){const t=a/(a-b);out.push(vadd(tri[i],vmul(vsub(tri[j],tri[i]),t)));}}const unique=[];for(const q of out)if(!unique.some(v=>norm(vsub(v,q))<1e-6))unique.push(q);return unique.length>=2?[unique[0],unique[1]]:null;}
  function prismTriangles(o){const [x0,y0,x1,y1]=o.profile.bounds,z0=o.z_min,z1=o.z_max,v=[[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],[x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]],quads=[[0,1,2,3],[4,7,6,5],[0,4,5,1],[1,5,6,2],[2,6,7,3],[3,7,4,0]];return quads.flatMap(q=>[[v[q[0]],v[q[1]],v[q[2]]],[v[q[0]],v[q[2]],v[q[3]]]]);}
  function cylinderTriangles(o,c){const n=64,b=[],t=[],bc=[c.center[0],c.center[1],o.z_min],tc=[c.center[0],c.center[1],o.z_max];for(let i=0;i<n;i++){const a=i*Math.PI*2/n;b.push([c.center[0]+c.radius*Math.cos(a),c.center[1]+c.radius*Math.sin(a),o.z_min]);t.push([c.center[0]+c.radius*Math.cos(a),c.center[1]+c.radius*Math.sin(a),o.z_max]);}const rows=[];for(let i=0;i<n;i++){const j=(i+1)%n;rows.push([b[i],b[j],t[j]],[b[i],t[j],t[i]],[bc,b[j],b[i]],[tc,t[i],t[j]]);}return rows;}
  function controllerRef(o){const id=o.profile.kind==='circle_pattern'?`SEL3D_${o.source_object_id}_PATTERN_CONTROLLER`:`SEL3D_${o.source_object_id}_CENTER_POINT`;return pkg.selection_map[id];}
  function parseRequest(text){let n=null,p=[0,0,0],m=text.match(/\b([xyz])\s*=\s*(-?\d+(?:\.\d+)?)/i);if(m){n=[0,0,0];n['xyz'.indexOf(m[1].toLowerCase())]=1;p['xyz'.indexOf(m[1].toLowerCase())]=Number(m[2]);}const nm=text.match(/(?:法向|normal)\s*[:：]?\s*\(?\s*(-?\d+(?:\.\d+)?)\s*[,， ]\s*(-?\d+(?:\.\d+)?)\s*[,， ]\s*(-?\d+(?:\.\d+)?)/i);if(nm)n=[Number(nm[1]),Number(nm[2]),Number(nm[3])];const pm=text.match(/(?:过点|point)\s*[:：]?\s*\(?\s*(-?\d+(?:\.\d+)?)\s*[,， ]\s*(-?\d+(?:\.\d+)?)\s*[,， ]\s*(-?\d+(?:\.\d+)?)/i);if(pm)p=[Number(pm[1]),Number(pm[2]),Number(pm[3])];if(/过原点|through origin/i.test(text))p=[0,0,0];return n&&norm(n)>1e-9?{n:unit(n),p}:null;}
  function valuesPlane(){const n=['sectionNx','sectionNy','sectionNz'].map(id=>Number(document.getElementById(id).value)),p=['sectionPx','sectionPy','sectionPz'].map(id=>Number(document.getElementById(id).value));return norm(n)>1e-9?{n:unit(n),p}:null;}
  function updateFields(){['sectionNx','sectionNy','sectionNz'].forEach((id,i)=>document.getElementById(id).value=Number(plane.n[i].toFixed(6)));['sectionPx','sectionPy','sectionPz'].forEach((id,i)=>document.getElementById(id).value=Number(plane.p[i].toFixed(6)));}
  function createSection(next){if(!next)return showToast('无法识别截面。可输入 X=10，或“法向 1,1,0 过原点”');plane=next;updateFields();draw();}
  function draw(){
    const box=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1,w=Math.max(1,Math.round(box.width*dpr)),h=Math.max(1,Math.round(box.height*dpr));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}ctx.fillStyle='#fbfaf6';ctx.fillRect(0,0,w,h);
    const helper=Math.abs(plane.n[2])<.9?[0,0,1]:[0,1,0],u=unit(cross(helper,plane.n)),v=unit(cross(plane.n,u)),raw=[];
    for(const o of pkg.selector_3d.objects){const triangles=o.profile.kind==='center_rectangle'?prismTriangles(o):(o.profile.primitives||[]).flatMap(c=>cylinderTriangles(o,c));for(const tri of triangles){const seg=triangleSection(tri,plane.n,plane.p);if(seg)raw.push({o,ref:controllerRef(o),a:[dot(vsub(seg[0],plane.p),u),dot(vsub(seg[0],plane.p),v)],b:[dot(vsub(seg[1],plane.p),u),dot(vsub(seg[1],plane.p),v)]});}}
    const points=raw.flatMap(x=>[x.a,x.b]);if(!points.length){ctx.fillStyle='#6b7280';ctx.font=`${14*dpr}px Microsoft YaHei`;ctx.fillText('该平面没有穿过当前特征',18*dpr,32*dpr);hits=[];return;}
    const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),minx=Math.min(...xs),maxx=Math.max(...xs),miny=Math.min(...ys),maxy=Math.max(...ys),span=Math.max(maxx-minx,maxy-miny,1),scale=Math.min(w,h)*.76/span,cx=(minx+maxx)/2,cy=(miny+maxy)/2,project=p=>[w/2+(p[0]-cx)*scale,h/2-(p[1]-cy)*scale];
    hits=raw.map((x,i)=>({...x,index:i,pa:project(x.a),pb:project(x.b)}));for(const x of hits){const chosen=x.ref&&selectedReferenceKeys().has(x.ref.reference_key),hot=x.index===hover;ctx.beginPath();ctx.moveTo(...x.pa);ctx.lineTo(...x.pb);ctx.strokeStyle=hot||chosen?'#e97428':x.o.role==='subtractive'?'#c9362b':'#173f5f';ctx.lineWidth=(hot||chosen?2.4:1)*dpr;ctx.globalAlpha=x.o.role==='subtractive'?.82:.7;ctx.stroke();}ctx.globalAlpha=1;ctx.fillStyle='#384454';ctx.font=`${12*dpr}px Microsoft YaHei`;ctx.fillText(`截面法向 ${plane.n.map(x=>x.toFixed(3)).join(', ')} · 过点 ${plane.p.join(', ')}`,12*dpr,20*dpr);
  }
  const dist=(x,y,a,b)=>{const dx=b[0]-a[0],dy=b[1]-a[1],l=dx*dx+dy*dy;if(!l)return Math.hypot(x-a[0],y-a[1]);const t=Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/l));return Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy);};
  canvas.onmousemove=e=>{const b=canvas.getBoundingClientRect(),d=window.devicePixelRatio||1,x=(e.clientX-b.left)*d,y=(e.clientY-b.top)*d,candidates=hits.map(h=>({h,d:dist(x,y,h.pa,h.pb)})).filter(x=>x.d<9*d).sort((a,b)=>a.d-b.d),next=candidates.length?candidates[0].h.index:-1;if(next!==hover){hover=next;canvas.style.cursor=hover>=0?'pointer':'crosshair';draw();}};
  canvas.onclick=()=>{if(hover>=0&&hits[hover].ref)toggleSelectionRef(hits[hover].ref);};
  document.getElementById('makeSection').onclick=()=>{const text=document.getElementById('sectionRequest').value.trim();createSection(text?parseRequest(text):valuesPlane());};document.getElementById('applyPlaneFields').onclick=()=>createSection(valuesPlane());
  window.addEventListener('resize',draw);window.__aicadSection={parseRequest,createSection,get plane(){return plane},get hitCount(){return hits.length},firstHitPoint(){if(!hits.length)return null;const d=window.devicePixelRatio||1,h=hits[0];return{x:(h.pa[0]+h.pb[0])/(2*d),y:(h.pa[1]+h.pb[1])/(2*d)};}};updateFields();draw();
}
"""


def render_review_html_v2(package: dict[str, Any], selector_script: str = "") -> str:
    payload = json.dumps(package, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    selector_card = ""
    section_card = ""
    if package["space"] == "3d":
        selector_card = '''<section class="view-card selector-card"><div class="view-heading"><div><span class="eyebrow">3D SELECT</span><h2>可旋转三维选择器</h2></div><span class="hint">拖动旋转 · 滚轮缩放 · 悬停发现隐藏几何</span></div><canvas id="aicad3d-selector" aria-label="可旋转三维特征选择器"></canvas></section>'''
        section_card = '''<section class="view-card section-card"><div class="view-heading"><div><span class="eyebrow">FREE SECTION</span><h2>自由截面</h2></div><span class="hint">告诉 AI 截面位置，截面线可直接点选</span></div><div class="section-command"><input id="sectionRequest" placeholder="例如：看 X=10 截面；或 法向 1,1,0 过原点"><button id="makeSection" class="accent">生成截面</button></div><details class="plane-fields"><summary>精确平面</summary><div class="plane-grid"><label>法向 X<input id="sectionNx" type="number" step="0.1"></label><label>法向 Y<input id="sectionNy" type="number" step="0.1"></label><label>法向 Z<input id="sectionNz" type="number" step="0.1"></label><label>过点 X<input id="sectionPx" type="number" step="0.1"></label><label>过点 Y<input id="sectionPy" type="number" step="0.1"></label><label>过点 Z<input id="sectionPz" type="number" step="0.1"></label></div><button id="applyPlaneFields">按数值更新</button></details><canvas id="freeSectionCanvas" aria-label="自由截面选择视图"></canvas><p class="authority-note">截面来自受约束特征运算，可用于定位和修改参数；制造结论仍需宿主 CAD 的最终 BREP 复核。</p></section>'''
    cards = selector_card + section_card + "".join(
        f'<section class="view-card"><div class="view-heading"><div><span class="eyebrow">{html.escape(view["id"])}</span><h2>{html.escape(view["label"])}</h2></div><span class="hint">{html.escape(_SCOPE_LABELS.get(view["geometry_scope"], view["geometry_scope"]))}</span></div>{_svg(view)}</section>'
        for view in package["views"]
    )
    interaction = _interaction_script()
    section = _section_script() if package["space"] == "3d" else ""
    init = "if(typeof initAicad3dSelector==='function')initAicad3dSelector();initFreeSection();" if package["space"] == "3d" else ""
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AICAD 几何审查与修改器</title><style>
:root{{--paper:#f4f1e9;--panel:#fffdf7;--ink:#1d2935;--muted:#68717b;--line:#c9c5ba;--navy:#173f5f;--orange:#e97428;--red:#c9362b;--green:#2f6f54}}
*{{box-sizing:border-box}}html{{background:var(--paper)}}body{{margin:0;color:var(--ink);background:linear-gradient(90deg,#0000 31px,#d9d4c820 32px),linear-gradient(#0000 31px,#d9d4c820 32px),var(--paper);background-size:32px 32px;font-family:"Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif}}
button,input,select,textarea{{font:inherit}}button{{cursor:pointer}}.topbar{{height:66px;padding:0 22px;background:#132433;color:#fff;display:flex;align-items:center;justify-content:space-between;border-bottom:4px solid var(--orange)}}.title-lockup{{display:flex;gap:14px;align-items:center}}.mark{{width:34px;height:34px;border:1px solid #fff8;display:grid;place-items:center;font:700 13px Consolas}}.topbar h1{{font-size:17px;margin:0;letter-spacing:.04em}}.topbar p{{font-size:11px;margin:3px 0 0;color:#b9c6d0}}.top-actions{{display:flex;align-items:center;gap:16px}}.safety{{font:11px Consolas;color:#d9e3ea}}.coordinate-toggle{{display:flex;align-items:center;gap:7px;font-size:11px;cursor:pointer;user-select:none}}.coordinate-toggle input{{position:absolute;opacity:0;pointer-events:none}}.switch-track{{width:31px;height:16px;border:1px solid #ffffff88;background:#07131d;position:relative}}.switch-track:after{{content:"";position:absolute;width:10px;height:10px;top:2px;left:2px;background:#9baab5;transition:.16s}}.coordinate-toggle input:checked+.switch-track:after{{left:17px;background:var(--orange)}}
main{{display:grid;grid-template-columns:minmax(0,1fr) 390px;gap:14px;padding:14px;align-items:start}}.workspace{{display:grid;grid-template-columns:repeat(2,minmax(320px,1fr));gap:12px}}.view-card,.inspector{{background:var(--panel);border:1px solid var(--line);box-shadow:3px 3px 0 #27374618}}.view-card{{min-height:292px;padding:12px}}.selector-card,.section-card{{grid-column:span 2}}.view-heading{{display:flex;justify-content:space-between;gap:12px;align-items:end;margin-bottom:9px;border-bottom:1px solid #d9d5ca;padding-bottom:7px}}.view-heading h2{{margin:1px 0 0;font-size:15px}}.eyebrow{{font:700 9px Consolas;color:var(--orange);letter-spacing:.12em}}.hint{{font-size:11px;color:var(--muted);text-align:right}}
.cad-view,#aicad3d-selector,#freeSectionCanvas{{display:block;width:100%;height:250px;border:1px solid #d6d1c6;background:#fbfaf6}}#aicad3d-selector{{height:340px;cursor:grab}}#aicad3d-selector:active{{cursor:grabbing}}#freeSectionCanvas{{height:300px;cursor:crosshair}}
.view-entity{{fill:none;stroke:#34495a;stroke-width:.8;vector-effect:non-scaling-stroke;pointer-events:none}}.view-entity.derived{{stroke-dasharray:5 3;opacity:.56}}.role-additive{{stroke:var(--navy)}}.role-subtractive{{stroke:var(--red)}}.view-hit{{fill:rgba(0,0,0,.001);stroke:rgba(0,0,0,.001);stroke-width:12;vector-effect:non-scaling-stroke;pointer-events:all;cursor:pointer}}.entity-pair.key-geometry .view-entity{{opacity:0}}.entity-pair.key-geometry:hover .view-entity,.entity-pair.key-geometry.selected .view-entity{{opacity:1;stroke:var(--orange);stroke-width:1.3;stroke-dasharray:4 2}}.entity-pair:not(.key-geometry):hover .view-entity,.entity-pair.selected .view-entity{{stroke:var(--orange);stroke-width:1.8;opacity:1}}.entity-pair.context-selected .view-entity{{stroke:#4b86ad;opacity:.62}}.point-mark line,.point-mark circle{{fill:none;stroke:inherit;vector-effect:non-scaling-stroke}}.view-coordinate-triad,.model-origin-marker{{pointer-events:none}}.view-coordinate-triad line{{stroke-width:1.2;vector-effect:non-scaling-stroke}}.view-coordinate-triad text{{font:700 9px Consolas;text-anchor:middle;dominant-baseline:middle;paint-order:stroke;stroke:#fff;stroke-width:2px;vector-effect:non-scaling-stroke}}.view-coordinate-triad .triad-origin{{fill:#132433}}.model-origin-marker{{stroke:#e97428;fill:#fff;stroke-width:1;vector-effect:non-scaling-stroke;opacity:.88}}.coordinates-hidden .view-coordinate-triad,.coordinates-hidden .model-origin-marker{{display:none}}
.section-command{{display:grid;grid-template-columns:1fr auto;gap:8px;margin-bottom:8px}}input,select,textarea{{border:1px solid #aaa59a;background:#fffefa;color:var(--ink);padding:8px 9px;border-radius:2px;min-width:0}}button{{border:1px solid #8c8a83;background:#fffefa;color:var(--ink);padding:8px 10px;border-radius:2px}}button:hover{{border-color:var(--orange);color:#b34b14}}button.accent,.primary{{background:var(--orange);border-color:var(--orange);color:#fff;font-weight:700}}.plane-fields{{font-size:11px;margin:5px 0 9px;color:var(--muted)}}.plane-grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin:7px 0}}.plane-grid label{{display:grid;gap:3px}}.authority-note{{font-size:10px;color:var(--muted);margin:7px 0 0}}
.inspector{{position:sticky;top:12px;max-height:calc(100vh - 24px);overflow:auto}}.inspector-head{{padding:14px 15px 11px;background:#e8e4d9;border-bottom:1px solid var(--line)}}.inspector-head h2{{font-size:16px;margin:0}}.inspector-head p{{font-size:11px;color:var(--muted);margin:5px 0 0}}.panel-section{{padding:12px 14px;border-bottom:1px solid #d9d5ca}}.panel-section h3{{font-size:12px;margin:0 0 9px;text-transform:uppercase;letter-spacing:.06em}}.selection-chip{{display:grid;grid-template-columns:52px 1fr;gap:4px 7px;border-left:3px solid var(--orange);padding:7px 8px;background:#f6efe8;margin:5px 0;font-size:11px}}.selection-chip small{{grid-column:1/-1;color:var(--muted)}}.muted{{font-size:11px;color:var(--muted)}}.measurement-card{{border:1px solid #cfc9bc;background:#fffefa;margin:7px 0;box-shadow:2px 2px 0 #173f5f12}}.measurement-card header{{display:flex;justify-content:space-between;gap:8px;padding:7px 8px;background:#e8edf0;border-bottom:1px solid #d4d9dc;font-size:10px}}.measurement-card header span{{color:var(--green)}}.metric-primary{{display:flex;width:100%;align-items:baseline;justify-content:space-between;border:0;border-bottom:1px solid #e5dfd3;background:transparent;padding:9px 8px;text-align:left}}button.metric-primary:hover{{background:#fff3e7}}.metric-primary>span{{font-size:11px;color:var(--muted)}}.metric-primary>strong{{font:700 20px "Cascadia Mono",Consolas;color:var(--navy)}}.metric-primary i{{font:normal 10px "Microsoft YaHei"}}.metric-secondary{{display:flex;justify-content:space-between;padding:6px 8px;border-bottom:1px solid #e5dfd3;font-size:11px}}.coordinate-label{{padding:6px 8px 3px;color:var(--muted);font-size:9px}}.coordinate-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;padding:0 7px 7px}}.coordinate-grid span{{display:grid;grid-template-columns:auto 1fr auto;gap:3px;align-items:baseline;background:#f1eee7;padding:5px}}.coordinate-grid b{{font:700 10px Consolas;color:var(--orange)}}.coordinate-grid strong{{font:700 11px Consolas;text-align:right}}.coordinate-grid i{{font:normal 8px "Microsoft YaHei";color:var(--muted)}}.measurement-card p{{margin:0;padding:6px 8px;color:var(--muted);font-size:9px}}
.parameter-group{{border:1px solid #d5d0c5;margin:6px 0;background:#fbfaf6}}.parameter-group.active{{border-color:var(--orange)}}.parameter-group header{{display:flex;justify-content:space-between;padding:6px 8px;background:#ece8df;font-size:10px}}.parameter-row{{display:flex;width:100%;justify-content:space-between;border:0;border-top:1px solid #e6e1d7;padding:6px 8px;background:transparent;font-size:11px;text-align:left}}.parameter-row strong{{font:700 11px "Cascadia Mono",Consolas}}.parameter-row i{{font:normal 9px "Microsoft YaHei";color:var(--muted)}}.form-grid{{display:grid;grid-template-columns:1fr 1fr;gap:7px}}.form-grid .wide{{grid-column:1/-1}}.label{{display:grid;gap:3px;font-size:10px;color:var(--muted)}}.attention{{animation:attention .65s}}@keyframes attention{{50%{{background:#fff0dd}}}}
.relation-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:6px}}textarea{{width:100%;min-height:78px;resize:vertical}}.ai-row{{display:grid;grid-template-columns:1fr auto;gap:6px}}.change-row{{display:flex;justify-content:space-between;gap:8px;border-left:2px solid var(--green);background:#edf4ef;padding:7px 8px;margin:5px 0;font-size:11px}}.change-row button{{border:0;background:transparent;padding:0 4px;font-size:16px}}.primary{{width:100%;margin-top:9px}}details.advanced{{margin-top:8px;font-size:10px;color:var(--muted)}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:9px Consolas;max-height:230px;overflow:auto;background:#14232e;color:#dce7ee;padding:8px}}#toast{{position:fixed;left:50%;bottom:24px;transform:translate(-50%,20px);background:#132433;color:white;padding:9px 14px;opacity:0;pointer-events:none;transition:.18s;border-left:4px solid var(--orange);z-index:20;font-size:12px}}#toast.show{{opacity:1;transform:translate(-50%,0)}}
@media(max-width:1050px){{main{{grid-template-columns:1fr}}.inspector{{position:static;max-height:none}}}}@media(max-width:720px){{.workspace{{grid-template-columns:1fr}}.selector-card,.section-card{{grid-column:span 1}}.plane-grid{{grid-template-columns:repeat(3,1fr)}}.safety{{display:none}}}}
</style></head><body><header class="topbar"><div class="title-lockup"><div class="mark">CAD</div><div><h1>几何审查与修改器</h1><p>选择 → 修改 → 约束复核；系统在后台生成精确事务</p></div></div><div class="top-actions"><label class="coordinate-toggle" title="显示或隐藏所有坐标基准"><input id="coordinateToggle" type="checkbox" checked role="switch" aria-checked="true"><span class="switch-track"></span><b>坐标系</b></label><div class="safety">REVIEW ONLY · NOT ACCEPTED · RULES OFF</div></div></header>
<main><div class="workspace">{cards}</div><aside class="inspector"><div class="inspector-head"><h2>修改面板</h2><p>选择对象后先读取模型真值，再决定是否修改。</p></div>
<section class="panel-section"><h3>当前对象</h3><div id="selection"></div></section>
<section class="panel-section measurement-section"><h3>几何数值</h3><div id="measurement"></div></section>
<section class="panel-section"><h3>核心参数</h3><div id="coreParameters"></div></section>
<section class="panel-section" id="quickEditor"><h3>快速修改</h3><div class="form-grid"><label class="label">参数<select id="parameterPath"></select></label><label class="label">新值<input id="parameterValue" placeholder="输入数值；中心用 X, Y"></label><label class="label">尺寸变化时<select id="preserve"><option value="keep_center">保持中心</option><option value="keep_opposite">保持对边</option><option value="keep_size">保持尺寸</option><option value="keep_support">保持支撑面</option></select></label><button id="setParameter">加入修改</button></div><details><summary class="muted">沿坐标轴移动边或面</summary><div class="form-grid"><select id="moveAxis"><option value="x">X 轴</option><option value="y">Y 轴</option><option value="z">Z 轴</option></select><select id="valueMode"><option value="absolute">绝对坐标</option><option value="delta">增量</option></select><input id="moveValue" type="number" value="0" step="0.1"><button id="addMove">加入移动</button></div></details></section>
<section class="panel-section"><h3>对象关系</h3><div id="relations" class="relation-grid"></div><label class="label">偏移量<input id="offsetValue" type="number" value="0" step="0.1"></label></section>
<section class="panel-section"><h3>直接告诉 AI</h3><div class="ai-row"><textarea id="aiInstruction" placeholder="例如：让中心孔与凸台同心，孔径改为 12 mm，其他尺寸保持不变。"></textarea><button id="addInstruction">加入</button></div></section>
<section class="panel-section"><h3>修改清单 <span id="changeCount">0</span></h3><div id="changeList"></div><button id="exportRequest" class="primary">导出给 AI 执行</button><details class="advanced"><summary>高级信息：精确引用与安全锁</summary><pre id="advancedJson"></pre></details></section></aside></main><div id="toast"></div>
<script>const pkg={payload};
{selector_script}
{interaction}
{section}
{init}renderUi();renderChanges();</script></body></html>'''
