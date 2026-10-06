"use strict";
// Pure ancestry/layout functions are shared with Node regression checks.
(function(scope){
  function forest(saves){
    const byId=new Map(saves.map(s=>[s.id,s])),grouped=new Map();
    function family(save){
      const seen=new Set();let point=save;
      while(point){
        if(seen.has(point.id))return [...seen].sort()[0];
        seen.add(point.id);const parent=byId.get(point.branch?.parent_id);
        if(!parent)return point.branch?.root_id || point.id;
        point=parent;
      }
    }
    for(const save of saves){const id=family(save);if(!grouped.has(id))grouped.set(id,[]);grouped.get(id).push(save);}
    return [...grouped].map(([id,members])=>{
      const ids=new Set(members.map(s=>s.id)),parents=new Map();
      for(const s of members){const parent=s.branch?.parent_id;if(parent!==s.id && ids.has(parent))parents.set(s.id,parent);}
      // Break a malformed historical cycle for display only; every save remains reachable.
      for(const s of members){const path=new Set();let key=s.id;while(parents.has(key)){if(path.has(key)){parents.delete([...path].sort()[0]);break;}path.add(key);key=parents.get(key);}}
      const roots=members.filter(s=>!parents.has(s.id)).sort((a,b)=>String(a.updated_at).localeCompare(String(b.updated_at)) || a.id.localeCompare(b.id));
      const root=byId.get(id) || roots[0],latest=[...members].sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at)) || a.id.localeCompare(b.id))[0];
      return {id,root,roots,members,parents,latest};
    }).sort((a,b)=>String(b.latest.updated_at).localeCompare(String(a.latest.updated_at)) || a.id.localeCompare(b.id));
  }
  function layout(group){
    const width=264,height=204,gapX=96,gapY=52,pad=48,children=new Map(),nodes=[],positions=new Map();let row=0;
    for(const s of group.members){const p=group.parents.get(s.id);if(p){if(!children.has(p))children.set(p,[]);children.get(p).push(s);}}
    for(const items of children.values())items.sort((a,b)=>String(a.updated_at).localeCompare(String(b.updated_at)) || a.id.localeCompare(b.id));
    function place(save,depth){
      const branch=children.get(save.id) || [],before=row;
      for(const child of branch)place(child,depth+1);
      if(!branch.length)row++;
      const mid=branch.length?(positions.get(branch[0].id).cy+positions.get(branch.at(-1).id).cy)/2:pad+height/2+before*(height+gapY);
      const node={save,x:pad+depth*(width+gapX),y:mid-height/2,cy:mid,width,height};positions.set(save.id,node);nodes.push(node);
    }
    for(const root of group.roots)place(root,0);
    const edges=[];for(const [id,parent] of group.parents){const a=positions.get(parent),b=positions.get(id);if(a && b)edges.push({from:parent,to:id,x1:a.x+width,y1:a.cy,x2:b.x,y2:b.cy});}
    return {nodes,edges,width:Math.max(...nodes.map(n=>n.x+width),0)+pad,height:Math.max(...nodes.map(n=>n.y+height),0)+pad};
  }
  const model={forest,layout};if(typeof module!=="undefined" && module.exports)module.exports=model;
  if(typeof document==="undefined")return;
  let active=null;
  function fromLobby(){return !!active && !active.origin.lobbyHidden;}
  function isOpen(){return !!active;}
  function leave(restore=true){
    if(!active)return;const previous=active;active=null;$("save-map-screen").hidden=true;document.body.classList.remove("save-map-open");
    if(restore){$("lobby").hidden=previous.origin.lobbyHidden;$("game").hidden=previous.origin.gameHidden;if(previous.options.manager)openSaveManager();else if(previous.origin.modalOpen)$("menu-button").click();else previous.returnFocus?.focus();}
  }
  async function refresh(){
    if(!active)return;const previous=active,{sessions}=await api("/api/sessions");
    const group=forest(sessions).find(g=>g.id===previous.group.id || g.members.some(s=>previous.group.members.some(old=>old.id===s.id)));
    if(!group){leave();return;}
    active.group=group;draw();
  }
  function manage(save){
    openModal("管理存档");body.append(textEl("h3",save.latest_event || save.title),textEl("p",save.summary || save.scene || "故事刚刚开始。","hint"));
    const back=textEl("button","返回分支图"),edit=textEl("button","名称与备注"),remove=textEl("button","移入回收站","danger-action"),download=textEl("a","导出存档包");
    back.addEventListener("click",()=>modal.close());edit.addEventListener("click",()=>editSave(save,async()=>{modal.close();await refresh();}));
    remove.disabled=state.busy || (save.id===state.session_id && state.persistent && !fromLobby());
    remove.addEventListener("click",()=>confirmDelete(save,active.group.members,async()=>{modal.close();await refresh();}));
    download.href="/api/save-bundle?session_id="+encodeURIComponent(save.id);download.download="yukima-"+save.id+".zip";
    const actions=textEl("div","","save-management-actions");actions.append(back,edit,download,remove);body.append(actions);
  }
  function sync(){
    const viewport=$("save-map-viewport"),range=$("save-map-scroll"),max=Math.max(0,viewport.scrollWidth-viewport.clientWidth);
    range.max=String(max);range.value=String(viewport.scrollLeft);range.disabled=max===0;range.setAttribute("aria-valuetext",max?Math.round(viewport.scrollLeft/max*100)+"%":"已显示完整故事线");
  }
  function draw(){
    const group=active.group,map=layout(group),canvas=$("save-map-canvas");canvas.replaceChildren();canvas.style.width=map.width+"px";canvas.style.height=map.height+"px";
    $("save-map-title").textContent=group.root.title;$("save-map-count").textContent=group.members.length+" 份存档 · 点击节点继续故事";
    const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.setAttribute("width",map.width);svg.setAttribute("height",map.height);svg.setAttribute("aria-hidden","true");svg.classList.add("save-map-lines");
    for(const e of map.edges){const path=document.createElementNS(svg.namespaceURI,"path"),bend=(e.x1+e.x2)/2;path.setAttribute("d",`M ${e.x1} ${e.y1} C ${bend} ${e.y1}, ${bend} ${e.y2}, ${e.x2} ${e.y2}`);svg.append(path);}canvas.append(svg);
    for(const n of map.nodes){
      const s=n.save,card=textEl("article","","save-map-node"+(s.id===state.session_id?" current-save":""));card.dataset.session=s.id;card.style.left=n.x+"px";card.style.top=n.y+"px";
      const button=textEl("button","","save-map-load");button.setAttribute("aria-label",`读取存档 #${s.id.slice(0,8)} · ${s.latest_event || s.title}`);button.disabled=state.busy;
      const tag=s.id===state.session_id?"当前进度":group.roots.some(r=>r.id===s.id)?"起始存档":({manual:"手动留档",rollback:"回溯分支","module-upgrade":"玩法更新"}[s.branch?.kind] || "故事分支");
      button.append(textEl("small",tag+" · #"+s.id.slice(0,8),"save-kind"),textEl("h3",s.latest_event || s.title),textEl("p",`${s.turn_count || 0} 回合 · ${new Date(s.updated_at).toLocaleString("zh-CN")}`,"save-card-meta"),textEl("p",s.summary || s.scene || "故事刚刚开始。","save-map-preview"));
      button.title=s.summary || s.scene || "";
      button.addEventListener("click",async()=>{button.disabled=true;try{const next=await api("/api/resume",{session_id:s.id});leave(false);enterGame(next);}catch(e){toast(e.message);button.disabled=state.busy;}});
      const more=textEl("button","管理","save-map-manage");more.setAttribute("aria-label","管理存档 #"+s.id.slice(0,8));more.addEventListener("click",()=>manage(s));card.append(button,more);canvas.append(card);
    }
    requestAnimationFrame(()=>{sync();});
  }
  function open(group,options={}){
    const origin={lobbyHidden:$("lobby").hidden,gameHidden:$("game").hidden,modalOpen:modal.open};
    active={group,options,origin,returnFocus:document.activeElement};
    $("lobby").hidden=true;$("game").hidden=true;if(modal.open)modal.close();
    $("save-map-screen").hidden=false;document.body.classList.add("save-map-open");draw();
    const rootNode=layout(group).nodes.find(n=>n.save.id===group.root.id);
    $("save-map-viewport").scrollTo({left:0,top:Math.max(0,(rootNode?.cy || 0)-$("save-map-viewport").clientHeight/2)});$("save-map-exit").focus();requestAnimationFrame(sync);
  }
  $("save-map-exit").addEventListener("click",()=>leave());
  $("save-map-scroll").addEventListener("input",e=>{$("save-map-viewport").scrollLeft=Number(e.target.value);});
  $("save-map-viewport").addEventListener("scroll",sync,{passive:true});
  $("save-map-latest").addEventListener("click",()=>{if(!active)return;$("save-map-canvas").querySelector(`[data-session="${active.group.latest.id}"]`)?.scrollIntoView({block:"center",inline:"center",behavior:"smooth"});});
  const viewport=$("save-map-viewport");let drag=null;
  viewport.addEventListener("pointerdown",e=>{if(e.button!==0 || e.target.closest("button,a,input"))return;drag={id:e.pointerId,x:e.clientX,y:e.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};viewport.setPointerCapture(e.pointerId);viewport.classList.add("dragging");});
  viewport.addEventListener("pointermove",e=>{if(drag?.id!==e.pointerId)return;viewport.scrollLeft=drag.left+drag.x-e.clientX;viewport.scrollTop=drag.top+drag.y-e.clientY;});
  function endDrag(e){if(drag?.id!==e.pointerId)return;drag=null;viewport.classList.remove("dragging");if(viewport.hasPointerCapture(e.pointerId))viewport.releasePointerCapture(e.pointerId);}
  viewport.addEventListener("pointerup",endDrag);viewport.addEventListener("pointercancel",endDrag);viewport.addEventListener("lostpointercapture",endDrag);
  viewport.addEventListener("keydown",e=>{const offset={ArrowLeft:[-200,0],ArrowRight:[200,0],ArrowUp:[0,-160],ArrowDown:[0,160]}[e.key];if(offset && e.target===viewport){e.preventDefault();viewport.scrollBy(...offset);}});
  document.addEventListener("keydown",e=>{if(e.key==="Escape" && active && !modal.open){e.preventDefault();leave();}});
  window.addEventListener("resize",sync);new ResizeObserver(sync).observe(viewport);
  scope.YukimaSaveMap={...model,open,leave,refresh,fromLobby,isOpen};
})(typeof window!=="undefined"?window:globalThis);
