"use strict";
// Script code supplies cards and actions; this UI knows no quest or combat rules.
window.YukimaEngine={render(s){$("story-clock").textContent=s.story_state?.clock || "";$("gameplay-button").disabled=s.busy;$("game-world-map").hidden=!s.event_mode;},openStory};
function engineCard(title,text,status){const card=textEl("article","","engine-card");card.append(textEl("h3",title));if(status)card.append(textEl("small",status));if(text)card.append(textEl("p",text));return card;}
function engineTabs(entries){const tabs=textEl("div","","engine-tabs");for(const [label,fn] of entries){const button=textEl("button",label);button.addEventListener("click",fn);tabs.append(button);}body.append(tabs);}
function openStory(){
  openModal("故事手记");body.append(textEl("p",state.story_state?.clock || "","hint"));
  engineTabs([["玩法",openStory],["物品",openItems],["事件与承诺",openThreads],["关系",openRelations],[state.story_state?.time?.locked?"故事时间":"设置故事时间",openClock]]);
  if(state.navigation_features?.length)engineTabs([["地图与约定",()=>window.YukimaWorldMap.open()]]);
  if(state.gameplay_unavailable)body.append(textEl("p","当前玩法暂时无法打开，请查看维护日志。","hint"));
  if(!state.gameplay?.length)body.append(textEl("p","这个存档尚未启用额外玩法，可以继续自由推进故事。","hint"));
  for(const module of state.gameplay || []){
    const section=textEl("section","","engine-module");section.append(textEl("h3",module.name));
    for(const item of module.view.cards || []){const card=engineCard(item.title || "记录",item.text || "",item.status);if(item.details?.length){const details=document.createElement("details");details.append(textEl("summary","查看记录"));for(const note of item.details)details.append(textEl("p",String(note)));card.append(details);}section.append(card);}
    for(const action of module.view.actions || []){const button=textEl("button",action.label,"engine-action");button.disabled=state.busy || state.status!=="active";button.addEventListener("click",()=>{if(state.busy || cgBlocks())return;modal.close();sendTurn(action.text,undefined,{module_id:module.id,action_id:action.id});});section.append(button);}
    body.append(section);
  }
  if(state.gameplay_upgrade_available){const button=textEl("button","在新分支中启用新版玩法","primary");button.disabled=state.busy || !state.persistent;button.addEventListener("click",async()=>{button.disabled=true;try{enterGame(await api("/api/gameplay/enable",{session_id:state.session_id}));openStory();toast("新版玩法已启用 · 原存档已保留",true);}catch(e){toast(e.message);button.disabled=false;}});body.append(button);}
}
function openItems(){openModal("随身与场景物品");engineTabs([["返回手记",openStory]]);const items=(state.story_state?.items || []).filter(i=>i.quantity>0);if(!items.length)body.append(textEl("p","尚未记录物品。","hint"));for(const item of items){const owner=item.owner==="player"?state.user:state.actors?.[item.owner]?.name || item.owner;body.append(engineCard(item.name,"持有者："+owner+(item.location?" · "+item.location:""),"数量 · "+item.quantity));}}
function openThreads(){openModal("事件与承诺");engineTabs([["返回手记",openStory]]);const plot=state.story_state?.plot;if(plot)body.append(engineCard("当前阶段",plot.focus,plot.phase));const labels={open:"待推进",active:"进行中",resolved:"已解决",cancelled:"已放下"};const threads=state.story_state?.threads || [];if(!threads.length)body.append(textEl("p","尚无已记录的事件或承诺。","hint"));for(const t of threads)body.append(engineCard(t.title,t.note+(t.deadline?"\n期限："+t.deadline:""),labels[t.status]));}
function openRelations(){openModal("人物关系");engineTabs([["返回手记",openStory],["人物好感",openAffinities]]);const rels=state.story_state?.relations || [];if(!rels.length)body.append(textEl("p","关系会随真实相遇与交往形成。","hint"));function level(v,trust){return v==null?"尚未记录":v<20?(trust?"有所戒备":"陌生"):v<40?(trust?"谨慎观望":"初步认识"):v<65?(trust?"逐渐信任":"较为熟悉"):(trust?"信任稳固":"十分熟悉");}for(const r of rels){const name=state.actors?.[r.actor_id]?.name;if(name)body.append(engineCard(name,r.identity,"信任 · "+level(r.trust,true)+"　熟悉 · "+level(r.familiarity,false)));}}
function openClock(){openModal("故事时间");engineTabs([["返回手记",openStory]]);if(state.story_state?.time?.locked){body.append(engineCard("当前时间",state.story_state.clock,state.story_state.time.era));body.append(textEl("p","时间跟随你的行动推进，停留在界面、等待回应或暂停游戏不会消耗故事时间。","hint"));if(state.story_state.time.date_precision==="relative")body.append(textEl("p","这个故事没有指定具体公历日期，按开篇之后的天数记录。","hint"));return;}body.append(textEl("p","故事时间跟随行动推进，等待界面回应和暂停期间不会流逝。日期可以留空，使用故事第几天。","hint"));const form=document.createElement("form"),date=document.createElement("input"),time=document.createElement("input");date.type="date";date.value=state.story_state?.calendar?.date || "";date.setAttribute("aria-label","故事日期");time.type="time";time.required=true;const minute=state.story_state?.calendar?.minute ?? 960;time.value=String(Math.floor(minute/60)).padStart(2,"0")+":"+String(minute%60).padStart(2,"0");time.setAttribute("aria-label","故事时刻");const button=textEl("button","确认故事时间","primary");button.type="submit";form.className="engine-clock-form";form.append(date,time,button);form.addEventListener("submit",async e=>{e.preventDefault();button.disabled=true;try{const [h,m]=time.value.split(":").map(Number);applyState(await api("/api/story-clock",{session_id:state.session_id,date:date.value || null,minute:h*60+m}));openStory();toast("故事时间已保存",true);}catch(e){toast(e.message);button.disabled=false;}});body.append(form);}
$("gameplay-button").addEventListener("click",openStory);
$("manage-saves-button").addEventListener("click",openSaveManager);
$("lobby-manage-saves").addEventListener("click",openSaveManager);
async function openSaveManager(){
  if(!state || !token){toast("正在载入存档，请稍候。");return;}
  openModal("存档管理");engineTabs([["回收站",openRecycle],["导入存档",importSaveChooser]]);
  const filter=document.createElement("input");filter.type="search";filter.placeholder="搜索剧本、存档名称或备注";filter.setAttribute("aria-label","搜索存档");filter.className="save-search";body.append(filter);const tree=textEl("div","","save-tree");body.append(tree);
  try{const {sessions}=await api("/api/sessions");function draw(){renderSaveList(tree,sessions,{search:false,query:filter.value,manager:true});}filter.addEventListener("input",draw);draw();}catch(e){body.append(textEl("p",e.message,"hint"));}
}
function editSave(save,onReturn=openSaveManager){openModal("存档名称与备注");const form=document.createElement("form"),title=document.createElement("input"),note=document.createElement("textarea");title.value=save.title;title.maxLength=200;title.required=true;title.setAttribute("aria-label","存档名称");note.value=save.note || "";note.maxLength=3000;note.rows=5;note.setAttribute("aria-label","存档备注");const button=textEl("button","保存名称与备注","primary");button.type="submit";form.className="save-editor";form.append(textEl("label","名称"),title,textEl("label","备注"),note,button);form.addEventListener("submit",async e=>{e.preventDefault();button.disabled=true;try{await api("/api/save-manager",{operation:"edit",session_id:save.id,title:title.value,note:note.value});applyState(await api("/api/state"));await onReturn();toast("存档信息已保存",true);}catch(e){toast(e.message);button.disabled=false;}});body.append(form);}
function confirmDelete(save,sessions,onReturn=openSaveManager){openModal("移入回收站");body.append(textEl("p",save.title));body.append(textEl("p","只删除这一档时，子分支保留原来的父档编号；删除整棵分支时，所有后续子档一并回收。可以在回收站恢复。","hint"));const cancel=textEl("button","取消"),one=textEl("button","只移走这一档"),all=textEl("button","移走这一档与所有子分支","danger-action");cancel.addEventListener("click",()=>{modal.close();onReturn();});async function remove(subtree){one.disabled=all.disabled=true;try{await api("/api/save-manager",{operation:"delete",session_id:save.id,subtree,from_lobby:!$("lobby").hidden || window.YukimaSaveMap.fromLobby()});applyState(await api("/api/state"));await onReturn();toast("已移入回收站",true);}catch(e){toast(e.message);one.disabled=all.disabled=false;}}one.addEventListener("click",()=>remove(false));all.addEventListener("click",()=>remove(true));body.append(cancel,one,all);}
async function openRecycle(){openModal("存档回收站");engineTabs([["返回存档",openSaveManager]]);try{const {entries}=await api("/api/recycle-bin");if(!entries.length)body.append(textEl("p","回收站为空。","hint"));for(const item of entries){const card=engineCard(item.saves.map(s=>s.title).join(" / "),new Date(item.deleted_at).toLocaleString("zh-CN"),item.saves.length+" 个存档");const restore=textEl("button","恢复这些存档");restore.addEventListener("click",async()=>{restore.disabled=true;try{await api("/api/save-manager",{operation:"restore",recycle_id:item.id});await openRecycle();toast("存档已恢复",true);}catch(e){toast(e.message);restore.disabled=false;}});const purge=textEl("button","彻底清除");purge.addEventListener("click",async()=>{if(!confirm("彻底清除这些存档及其任务文件、独享图片？此操作无法恢复。公共图库与其他分支引用的图片会保留。"))return;purge.disabled=true;try{await api("/api/save-manager",{operation:"purge",recycle_id:item.id});await openRecycle();toast("已彻底清除",true);}catch(e){toast(e.message);purge.disabled=false;}});card.append(restore,purge);body.append(card);}}catch(e){body.append(textEl("p",e.message));}}
function importSaveChooser(){openModal("导入存档包");engineTabs([["返回存档",openSaveManager]]);body.append(textEl("p","导入会建立独立的新存档，不覆盖现有故事。生成图片另存于原资料库，存档包包含故事、记忆、回溯快照和玩法代码。","hint"));const file=document.createElement("input");file.type="file";file.accept=".zip";file.setAttribute("aria-label","选择存档包");const button=textEl("button","导入为新存档","primary");button.addEventListener("click",async()=>{if(!file.files[0])return;button.disabled=true;try{const f=file.files[0];if(f.size>32*1024*1024)throw new Error("存档包最多 32 MiB。");const bytes=new Uint8Array(await f.arrayBuffer());let value="";for(let i=0;i<bytes.length;i+=8192)value+=String.fromCharCode(...bytes.subarray(i,i+8192));await api("/api/save-manager",{operation:"import",bundle:btoa(value)});await openSaveManager();toast("已导入为独立存档",true);}catch(e){toast(e.message);button.disabled=false;}});body.append(file,button);}
function openThoughtPage(){openModal("人物心声");body.append(exportBar("thoughts"));const entries=state.inner_thoughts || [];if(!entries.length)body.append(textEl("p","尚未记录人物心声。","hint"));for(const entry of [...entries].reverse())body.append(engineCard(entry.name,entry.text,entry.scene));}

modal.addEventListener("close",()=>{if(!window.YukimaSaveMap.isOpen() && !$("lobby").hidden && !$("story-picker").hidden)chooseStory();});

// Explicit reader view. Opening never starts/resumes a save or advances time.
async function openWorldEvents(fromLobby=false){
  openModal("事件记录");modal.classList.add("events-modal");let eventView="protagonist",eventSession=fromLobby?"":state.session_id,cursor=0,loadSeq=0;
  const controls=document.createElement("div"),select=document.createElement("select"),tabs=document.createElement("div"),list=document.createElement("div"),status=textEl("p","","hint");
  const exit=textEl("button","退出事件记录");exit.addEventListener("click",()=>modal.close());
  controls.className="event-controls";tabs.className="event-tabs";list.className="event-list";status.setAttribute("role","status");
  if(fromLobby){select.setAttribute("aria-label","选择故事记录");controls.append(select);}controls.append(exit);body.append(controls,tabs,status,list);
  const sessions=fromLobby?await api("/api/sessions"):{sessions:[]};const saves=Array.isArray(sessions)?sessions:sessions.sessions || [];
  const empty=document.createElement("option");empty.value="";empty.textContent="选择要回顾的故事";select.append(empty);
  for(const save of saves){const option=document.createElement("option");option.value=save.id || save.session_id;option.textContent=(save.title || option.value)+" · "+(save.branch?.label || "主线");select.append(option);}
  if(saves.some(s=>(s.id || s.session_id)===state.session_id)){select.value=state.session_id;eventSession=state.session_id;}
  for(const [view,label]of[["protagonist","主角事件"],["world","世界事件"],["expected","预期事件"]]){const button=textEl("button",label);button.dataset.eventView=view;button.setAttribute("aria-pressed",view===eventView);button.addEventListener("click",()=>{eventView=view;cursor=0;load();});tabs.append(button);}
  async function load(){
    const sequence=++loadSeq;
    list.replaceChildren();for(const button of tabs.children)button.setAttribute("aria-pressed",button.dataset.eventView===eventView);
    if(!eventSession){status.textContent=saves.length?"选择存档即可查看，无需进入游戏。":"还没有存档。";return;}
    status.textContent="正在读取事件记录。";
    try{const result=await api("/api/world-events?"+new URLSearchParams({session_id:eventSession,view:eventView,cursor,limit:50}));
      if(sequence!==loadSeq || !modal.open || !modal.classList.contains("events-modal"))return;
      if(eventView==="expected"){
        status.textContent=result.legacy?"这个存档没有预期事件表；不会补写旧档的安排。":`${result.title} · ${result.total} 项安排`;
        if(result.note)list.append(textEl("p",result.note,"hint"));
        for(const event of result.entries)list.append(engineCard(event.title,event.description,`${event.display_time} · ${event.category} · ${event.status_label}`));
        if(!result.legacy && !result.total)list.append(textEl("p","尚无已公布的后续安排。","hint"));
        if(result.next_cursor!==null){const next=textEl("button","下一页");next.addEventListener("click",()=>{cursor=result.next_cursor;load();});list.append(next);}
        if(cursor){const first=textEl("button","返回近期安排");first.addEventListener("click",()=>{cursor=0;load();});list.append(first);}
        return;
      }
      status.textContent=result.legacy?"这个旧存档尚未记录世界事件；不会补造过去的历史。":`${result.title} · ${result.total} 条 · ${eventView==="world"?"读者视角，查看不代表主角获知":"与主角有关的事件"}`;
      if(!result.legacy){const downloads=textEl("div","","export-bar");for(const [label,format]of[["导出文本","txt"],["导出 Markdown","md"]]){const link=textEl("a",label);link.href="/api/export?"+new URLSearchParams({session_id:eventSession,scope:eventView==="world"?"world-events":"protagonist-events",format});link.setAttribute("download","");link.className="export-link";downloads.append(link);}list.append(downloads);}
      for(const event of result.entries){const card=engineCard(event.title,"",`${event.display_time} · ${event.status_label}`),detail=document.createElement("details"),summary=textEl("summary","展开经过");detail.append(summary,textEl("p",event.description));if(!event.protagonist_knows)detail.append(textEl("p","主角尚未获知","hint"));card.append(detail);list.append(card);}
      if(result.next_cursor!==null){const next=textEl("button","下一页");next.addEventListener("click",()=>{cursor=result.next_cursor;load();});list.append(next);}
      if(cursor){const first=textEl("button","返回最近事件");first.addEventListener("click",()=>{cursor=0;load();});list.append(first);}
    }catch(error){if(sequence===loadSeq && modal.open && modal.classList.contains("events-modal"))status.textContent=error.message;}
  }
  select.addEventListener("change",()=>{eventSession=select.value;cursor=0;load();});await load();
}
$("lobby-world-events").addEventListener("click",()=>openWorldEvents(true));
$("game-world-events").addEventListener("click",()=>openWorldEvents(false));
