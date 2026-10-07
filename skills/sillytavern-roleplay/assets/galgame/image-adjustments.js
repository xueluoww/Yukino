"use strict";
let imageAdjustmentDraft=null, imageAdjustmentSignature="";

function openImageAdjustments(selectedUrl){
  openModal("调整画面");modal.classList.add("image-adjustments-modal");
  imageAdjustmentSignature="";imageAdjustmentDraft=null;
  body.append(textEl("p","补充你希望调整的构图、光线或画面细节。人物与故事保留原设定；原图会一直保留。","hint"));
  const sources=state.image_adjustment_sources || [];
  if(!sources.length){body.append(textEl("p","当前还没有可调整的画面。"));return;}
  const form=textEl("form","","image-adjustment-form"),label=textEl("label","选择画面"),select=document.createElement("select");
  select.id="adjustment-source";select.setAttribute("aria-label","选择要调整的画面");
  const kinds={background:"场景",portrait:"立绘",cg:"剧情插图"};
  for(const source of sources){const option=textEl("option",kinds[source.kind]+" · "+source.name);option.value=source.key;select.append(option);}
  const chosen=sources.find(s=>s.url===selectedUrl);if(chosen)select.value=chosen.key;
  label.append(select);form.append(label);
  const original=document.createElement("img");original.id="adjustment-original";original.className="adjustment-preview";original.alt="待调整的原图";form.append(original);
  const promptLabel=textEl("label","补充要求"),prompt=document.createElement("textarea");prompt.id="adjustment-prompt";prompt.maxLength=1200;prompt.required=true;prompt.rows=3;prompt.placeholder="描述你希望这幅画面怎样变化";promptLabel.append(prompt);form.append(promptLabel);
  const button=textEl("button","生成新版本","primary");button.id="adjustment-generate";button.type="submit";button.disabled=state.busy || !state.dynamic_images;form.append(button);
  if(!state.dynamic_images)form.append(textEl("p","请先在设置中启用画面生成。","hint"));
  const change=()=>{imageAdjustmentDraft=null;const source=sources.find(s=>s.key===select.value);original.src=safeAsset(source?.url);};
  select.addEventListener("change",change);prompt.addEventListener("input",()=>imageAdjustmentDraft=null);change();
  form.addEventListener("submit",async event=>{
    event.preventDefault();if(!prompt.value.trim())return;
    imageAdjustmentDraft ||= {session_id:state.session_id,source_key:select.value,prompt:prompt.value.trim(),request_id:crypto.randomUUID()};
    button.disabled=true;
    try{applyState(await api("/api/images/adjust",imageAdjustmentDraft));imageAdjustmentDraft=null;toast("新画面已开始准备，原图保留",true);}
    catch(error){toast(error.message);}
    finally{button.disabled=state.busy || !state.dynamic_images;}
  });
  body.append(form,textEl("h3","新旧画面对照"));const results=textEl("div","","image-adjustment-results");results.id="adjustment-results";body.append(results);renderImageAdjustmentResults();
}

function renderImageAdjustmentResults(){
  const list=$("adjustment-results");if(!list)return;
  const records=state.image_adjustments || [],signature=JSON.stringify([state.session_id,state.busy,records]);
  if(signature===imageAdjustmentSignature)return;imageAdjustmentSignature=signature;list.replaceChildren();
  if(!records.length){list.append(textEl("p","新版本完成后，可在这里比较并选择。","hint"));return;}
  for(const record of [...records].reverse()){
    const card=textEl("section","","adjustment-card");card.append(textEl("h4",record.name),textEl("p",record.prompt));
    const comparison=textEl("div","","adjustment-comparison");
    for(const [label,url] of [["原图",record.source_url],["新版",record.url]]){const figure=document.createElement("figure");figure.append(textEl("figcaption",label));if(url){const image=document.createElement("img");image.src=safeAsset(url);image.alt=record.name+" · "+label;figure.append(image);}else figure.append(textEl("p",record.status==="failed"?"画面暂未完成":"新画面正在准备"));comparison.append(figure);}
    card.append(comparison);
    if(record.adopted)card.append(textEl("p","已采用 · 原图保留","hint"));
    else if(record.status==="ready" && record.url){
      const adopt=textEl("button",record.can_apply_current?"采用新版":"采用并加入画廊");adopt.disabled=state.busy;
      adopt.addEventListener("click",async()=>{adopt.disabled=true;try{const decoded=new Image();decoded.src=safeAsset(record.url);await decoded.decode();applyState(await api("/api/images/adopt",{session_id:state.session_id,key:record.key}));toast("已采用新版，其他存档保留原画面",true);}catch(error){toast(error.message || "这幅画面暂时无法显示。");adopt.disabled=false;}});card.append(adopt);
      if(!record.can_apply_current)card.append(textEl("p","对应情节已经过去，新版会保留在画廊。","hint"));
    }else if(record.status==="failed"){
      const retry=textEl("button","重试新版");retry.disabled=state.busy || !state.dynamic_images;retry.addEventListener("click",async()=>{retry.disabled=true;try{applyState(await api("/api/images/retry-adjustment",{session_id:state.session_id,key:record.key}));}catch(error){toast(error.message);retry.disabled=false;}});card.append(retry);
    }
    list.append(card);
  }
}

// An entry in the game menu also supports adjusting the visible current scene.
document.addEventListener("click",event=>{
  if(event.target.id!=="menu-button")return;
  const entry=textEl("button","调整当前画面");entry.addEventListener("click",()=>openImageAdjustments(playingCg() || currentFrame()?.background || state.background));
  body.insertBefore(entry,body.firstChild);
});
