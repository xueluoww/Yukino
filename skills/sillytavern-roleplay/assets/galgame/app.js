"use strict";
const $ = (id) => document.getElementById(id);
let state, token, frameIndex = 0, typed = 0, typingTimer, autoTimer, auto = false;
let speed = Number(localStorage.getItem("yukino-public-speed") || 28), submitting = false, latestError = "", visualKey = "", saving = false, toastTimer;
let pending=null, receiptUntil=0, imageSerial=0, choicesSignature="";
const cgDismissed=new Set(), cgSkipped=new Set(), cgDecoded=new Set(), cgDecoding=new Set(), cgDecodeFailed=new Set();
let selectedCardId="", selectedScenarioId="", rosterSignature="";
const modal = $("modal"), body = $("modal-body");
async function api(path, data) {
  const response = await fetch(path, data === undefined ? {signal:AbortSignal.timeout(10000)} : {signal:AbortSignal.timeout(10000),method:"POST",headers:{"Content-Type":"application/json","X-Session-Token":token},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) {const error=new Error(result.error || "暂时无法连接，请重试。");error.status=response.status;error.retryAsText=result.retry_as_text;throw error;}
  return result;
}
function toast(message, success=false) { clearTimeout(toastTimer); $("toast").textContent=message; $("toast").classList.toggle("success",success); $("toast").hidden=false; toastTimer=setTimeout(()=>$("toast").hidden=true,success?2000:4500); }
function openModal(title) { $("modal-title").textContent=title; body.replaceChildren(); modal.classList.remove("profile-modal","affinity-modal"); if(!modal.open)modal.showModal(); }
function textEl(tag, text, className) {const el=document.createElement(tag);el.textContent=text;if(className)el.className=className;return el;}
function safeAsset(url) {return typeof url==="string" && /^\/(?!\/)[\w\-./%]+$/.test(url) ? url : "";}
async function swapImage(element, url) {
  url=safeAsset(url);if(!url){element.hidden=true;return;}if(element.getAttribute("src")===url)return;
  const image=new Image();image.src=url;
  try{await image.decode();element.src=url;element.hidden=false;}catch{element.hidden=true;}
}
async function renderVisual() {
  const frame=state.frames[frameIndex], actor=state.actors?.[frame?.actor_id] || {};
  const onstage=(frame?.stage?.visible_actor_ids ?? frame?.stage?.present_actor_ids)?.includes(frame?.actor_id) ?? (frame?.expression!=="absent");
  const remote=state.scene_state?.contacts?.some(c=>c.actor_id===frame?.actor_id) || false;
  const waiting=state.busy && onstage && (state.activity?.waiting_actor_ids || []).includes(frame?.actor_id) && frame?.expression!=="absent";
  const expression=waiting?"thinking":frame?.expression || state.visual.expression;
  const spriteUrl=onstage?(actor.sprites?.[expression] || actor.sprites?.neutral || ""):"";
  const avatarUrl=(onstage || remote)?actor.avatar || "":"", backgroundUrl=playingCg() || frame?.background || state.background;
  const key=backgroundUrl+"|"+spriteUrl+"|"+avatarUrl+"|"+frame?.actor_id+"|"+expression+"|"+waiting;
  $("game").classList.toggle("is-thinking",waiting);$("game").classList.toggle("cg-scene",!!playingCg());
  if(key===visualKey)return;visualKey=key;const serial=++imageSerial;
  // Hide the previous speaker immediately, including while another sprite decodes.
  $("sprite").hidden=true;$("portrait-wrap").hidden=true;
  const bg=safeAsset(backgroundUrl);
  if(bg && $("background").dataset.source!==bg){const im=new Image();im.src=bg;try{await im.decode();if(serial!==imageSerial)return;$("background").style.backgroundImage=`url("${bg}")`;$("background").dataset.source=bg;$("background").animate([{opacity:.35},{opacity:1}],{duration:900});}catch{}}
  if(serial!==imageSerial)return;
  const sprite=safeAsset(spriteUrl);
  if(expression!=="absent" && !playingCg() && sprite){const im=new Image();im.src=sprite;try{await im.decode();if(serial!==imageSerial)return;$("sprite").src=sprite;$("sprite").hidden=false;}catch{}}
  if(serial!==imageSerial)return;
  // A portrait is a fallback only when the same actor has no usable sprite.
  if($("sprite").hidden && expression!=="absent" && !playingCg() && safeAsset(avatarUrl)){
    const im=new Image();im.src=safeAsset(avatarUrl);try{await im.decode();if(serial!==imageSerial)return;$("avatar").src=im.src;$("avatar").hidden=false;$("avatar").classList.remove("avatar-sprite");$("portrait-wrap").hidden=false;}catch{}
  }
}
function currentFrame(){return state?.frames[frameIndex];}
function completeText(){clearInterval(typingTimer);const f=currentFrame();if(!f)return;typed=f.text.length;$("dialogue").textContent=f.text;updateContinue();}
function updateContinue(){const last=frameIndex>=state.frames.length-1;$("next-button").textContent=last?(cgBlocks()?"查看这一幕 ◇":"轮到你了 ◇"):"继续 ◇";$("status").textContent="";renderCg();renderChoices();}
function showFrame() {
  clearInterval(typingTimer);clearTimeout(autoTimer);const f=currentFrame();if(!f)return;
  $("speaker").textContent=f.kind==="dialogue"?(f.speaker || state.name):f.kind==="thought"?`${f.speaker || state.actors?.[f.actor_id]?.name || state.name} · 心声`:"旁白";
  $("dialogue").className=f.kind;$("frame-count").textContent=`${String(frameIndex+1).padStart(2,"0")} / ${String(state.frames.length).padStart(2,"0")}`;
  typed=0;$("dialogue").textContent="";renderVisual();updateContinue();renderAffinityBadge();
  if(speed===0 || matchMedia("(prefers-reduced-motion: reduce)").matches)completeText();
  else typingTimer=setInterval(()=>{typed++;$("dialogue").textContent=f.text.slice(0,typed);if(typed>=f.text.length){clearInterval(typingTimer);updateContinue();if(auto && frameIndex<state.frames.length-1)autoTimer=setTimeout(next,1800);}},speed);
}
function next(){if(!state || !currentFrame())return;if(typed<currentFrame().text.length){completeText();return;}if(frameIndex<state.frames.length-1){frameIndex++;showFrame();}else{if(cgBlocks()){if(cgDecoded.has(cgId()))finishCg();else renderCg();return;}$("message").focus();}}
function applyState(nextState, reset=false) {
  const changed=!state || nextState.session_id!==state.session_id || nextState.turns.at(-1)?.turn_id!==state.turns.at(-1)?.turn_id;
  state=nextState;recoverPending();renderFeedback();renderThoughts();$("location").textContent=state.location;$("mode").textContent=state.status==="paused"?"已暂停":state.persistent?"故事进行中":"试读";
  $("chapter-number").textContent=`SCENE ${String(state.turns.length).padStart(2,"0")}`;$("chapter-title").textContent=state.story?.nodes?.at(-1)?.title || "初次相遇";
  $("save-state").textContent=state.persistent?"":"试读 · 可随时存档";
  $("send-button").disabled=state.provider==="demo" || state.busy || submitting || state.status==="paused";$("save-button").disabled=state.busy || saving;$("message").disabled=state.provider==="demo" || state.busy || state.status==="paused";if(state.provider==="demo")$("message").placeholder="演示模式：可查看故事记录，配置文本服务后自由游玩";
  if(changed || reset){frameIndex=0;showFrame();}else {renderVisual();updateContinue();}
  if(state.error && state.error!==latestError){if(!pending)toast(state.error);latestError=state.error;}if(!state.error)latestError="";

  if(window.YukimaEngine)window.YukimaEngine.render(state);preloadPredictions();renderInputPrefixes();renderRoster();renderAffinityBadge();if(modal.open && modal.classList.contains("affinity-modal"))renderAffinities(); window.YukimaMusic.refresh(state,!$("game").hidden);
}

function selectedCard(){return state.scripts.find(script=>script.id===selectedCardId);}
function selectCharacter(id){selectedCardId=id;const card=selectedCard();if(!card)return;$("selected-name").textContent=card.display_name;$("selected-bio").textContent=card.bio;$("selected-scene").textContent=card.scene_intro;$("selected-cast").textContent=(card.cast || []).join("、");for(const button of $("character-roster").children){button.classList.toggle("selected",button.dataset.card===id);button.setAttribute("aria-pressed",String(button.dataset.card===id));}}
function renderRoster(){const signature=JSON.stringify(state.scripts);if(signature===rosterSignature)return;rosterSignature=signature;$("character-roster").replaceChildren();$("library-count").textContent=`${state.scripts.length} 个可选剧本`;for(const card of state.scripts){const button=document.createElement("button");button.className="character-card";button.dataset.card=card.id;button.setAttribute("aria-label",`选择剧本 ${card.display_name}`);const img=document.createElement("img");img.src=safeAsset(card.sprite || card.avatar);img.alt=`${card.display_name}剧本立绘`;button.append(img,textEl("span",card.display_name));button.addEventListener("click",()=>selectCharacter(card.id));$("character-roster").append(button);}if(!selectedCard())selectedCardId=state.scripts[0]?.id || "";selectCharacter(selectedCardId);}
function storyTab(saved){$("new-story-pane").hidden=saved;$("saved-story-pane").hidden=!saved;$("new-story-tab").classList.toggle("selected",!saved);$("saved-story-tab").classList.toggle("selected",saved);}
function saveBelongsToScript(save,script){
  const identities=[script.id,script.world_id].filter(Boolean);
  // Explicit story identity takes precedence over today's primary character.
  if(save.script_id)return identities.includes(save.script_id);
  if(save.world_id)return identities.includes(save.world_id);
  // Only saves without an identity may use a uniquely bound legacy character.
  return script.world_id?(script.legacy_card_ids || []).includes(save.card_id):save.card_id===script.card_id;
}
async function chooseStory(){const card=selectedCard();if(!card)return;$("character-picker").hidden=true;$("story-picker").hidden=false;$("story-character-name").textContent=card.display_name;await swapImage($("story-sprite"),card.sprite || card.avatar);renderWorldPicker(card);$("player-name").value=state.user || "你";$("scenario-list").replaceChildren();selectedScenarioId=card.scenarios[0]?.id || "";
  for(const scene of card.scenarios){const button=document.createElement("button");button.className="scenario-card";button.dataset.scenario=scene.id;const bg=card.backgrounds?.[scene.background];if(bg){const img=document.createElement("img");img.src=safeAsset(bg);img.alt=scene.title;button.append(img);}const details=document.createElement("div");details.append(textEl("strong",scene.title),textEl("p",scene.description));button.append(details,textEl("span","◇","scene-radio"));button.classList.toggle("selected",scene.id===selectedScenarioId);button.addEventListener("click",()=>{selectedScenarioId=scene.id;for(const b of $("scenario-list").children)b.classList.toggle("selected",b.dataset.scenario===scene.id);});$("scenario-list").append(button);}
  $("saved-stories").replaceChildren();try{const result=await api("/api/sessions"),saves=result.sessions.filter(s=>saveBelongsToScript(s,card));renderSaveList($("saved-stories"),saves);if(!saves.length)$("saved-stories").append(textEl("p","这个剧本还没有存档。可以先选择一个开场，开启新故事。","hint"));storyTab(saves.length>0);}catch(error){$("lobby-notice").textContent=error.message;storyTab(false);}
}
function enterGame(newState){localStorage.setItem("yukino-public-view",newState.session_id);for(const url of Object.values(newState.sprites || {})){const img=new Image();img.src=safeAsset(url);img.decode().catch(()=>{});}$("lobby").hidden=true;$("game").hidden=false;visualKey="";applyState(newState,true);}
async function beginStory(persistent){$("begin-story").disabled=true;$("preview-story").disabled=true;try{enterGame(await api("/api/start",{script_id:selectedCardId,card:selectedCard()?.card_id,user:$("player-name").value || "你",persistent,scenario:selectedScenarioId,world_id:$("world-select").value,setting_ids:[...$("setting-select").selectedOptions].map(o=>o.value),protagonist_id:$("protagonist-select").value}));$("lobby-notice").textContent="";}catch(error){$("lobby-notice").textContent=error.message;}finally{$("begin-story").disabled=false;$("preview-story").disabled=false;}}
$("choose-story-button").addEventListener("click",chooseStory);$("back-to-characters").addEventListener("click",()=>{$("character-picker").hidden=false;$("story-picker").hidden=true;});$("new-story-tab").addEventListener("click",()=>storyTab(false));$("saved-story-tab").addEventListener("click",()=>storyTab(true));$("begin-story").addEventListener("click",()=>beginStory(true));$("preview-story").addEventListener("click",()=>beginStory(false));
$("input-form").addEventListener("submit",event=>{event.preventDefault();const text=$("message").value.trim();if(!text || state.busy || submitting || cgBlocks())return;sendTurn(text);});
$("retry-turn").addEventListener("click",()=>{if(pending && !state.busy)sendTurn(pending.text,pending.id,pending.gameplay);});
$("retry-image").addEventListener("click",async()=>{try{applyState(await api("/api/retry-images",{}));}catch(error){toast(error.message);}});
$("message").addEventListener("keydown",event=>{if(event.key==="Enter" && !event.shiftKey && !event.isComposing){event.preventDefault();$("input-form").requestSubmit();}});
$("next-button").addEventListener("click",next);$("dialogue").addEventListener("click",next);
document.addEventListener("keydown",event=>{if($("game").hidden || modal.open || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName))return;if(event.code==="Space"){event.preventDefault();next();}if(event.key.toLowerCase()==="h")toggleUI();});
function toggleUI(){const hidden=$("game").classList.toggle("ui-hidden");$("restore-ui").hidden=!hidden;}
$("hide-button").addEventListener("click",toggleUI);$("restore-ui").addEventListener("click",toggleUI);
$("fullscreen-button").addEventListener("click",async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await $("game").requestFullscreen();}catch{toast("当前浏览器不支持全屏。");}});
$("auto-button").addEventListener("click",()=>{auto=!auto;$("auto-button").setAttribute("aria-pressed",String(auto));clearTimeout(autoTimer);if(auto && typed>=currentFrame().text.length && frameIndex<state.frames.length-1)autoTimer=setTimeout(next,1500);});
$("close-modal").addEventListener("click",()=>modal.close());modal.addEventListener("click",event=>{if(event.target===modal){const r=modal.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)modal.close();}});
$("log-button").addEventListener("click",()=>{openModal("故事回看");body.append(exportBar("story"),textEl("p","最近的故事在前。导出文档按发生顺序排列。","hint"));for(const turn of [...state.turns].reverse())body.append(historyCard(turn));});
$("save-button").addEventListener("click",async()=>{if(saving)return;saving=true;$("save-button").disabled=true;try{const saved=await api("/api/save",{});enterGame(saved);if(saved.persistent)toast("已另存 · "+(saved.branch?.label || "主线"),true);}catch(error){toast(error.message);}finally{saving=false;$("save-button").disabled=state.busy;}});
$("gallery-button").addEventListener("click",()=>{
  openModal("故事画廊");const tabs=textEl("div","","gallery-tabs"),content=document.createElement("div");body.append(tabs,content);
  function show(items, selected){content.replaceChildren();for(const b of tabs.children)b.classList.toggle("selected",b===selected);if(!items?.length){content.append(textEl("p","值得留下的画面，会在故事里与你相遇。","hint"));return;}const grid=textEl("div","","gallery");for(const item of items){const button=document.createElement("button"),img=document.createElement("img");img.src=safeAsset(item.url);img.alt=item.name;button.append(img,textEl("span",item.name.slice(0,28)));button.addEventListener("click",()=>{content.replaceChildren();const full=img.cloneNode();full.className="gallery-full";content.append(full);});grid.append(button);}content.append(grid);}
  for(const [label,items] of [["场景",state.library?.backgrounds],["人物",state.library?.portraits],["剧情插图",state.illustrations]]){const b=textEl("button",label);b.addEventListener("click",()=>show(items,b));tabs.append(b);}const previewButton=textEl("button","候选图库");tabs.append(previewButton);previewButton.addEventListener("click",()=>{
    content.replaceChildren();for(const b of tabs.children)b.classList.toggle("selected",b===previewButton);
    const pool=state.prediction_library || {quotas:{},slots:{},entries:[]},labels={background:"背景",portrait:"立绘",interaction:"交流画面"};
    content.append(textEl("p","候选画面仅作准备，采用后移入故事画廊。","hint"));
    for(const [kind,quota] of Object.entries(pool.quotas)){content.append(textEl("h3",`${labels[kind]} · ${quota-(pool.slots[kind] || 0)} / ${quota}`));
      const grid=textEl("div","","gallery");for(const item of pool.entries.filter(e=>e.kind===kind)){const card=textEl("div","","preview-card");if(item.url){const img=document.createElement("img");img.src=safeAsset(item.url);img.alt=item.name;card.append(img);}card.append(textEl("span",item.name),textEl("small",{queued:"候选待备",painting:"候选准备中",ready:"可用",failed:"暂未就绪"}[item.status] || "准备中"));if(item.status==="failed"){const retry=textEl("button","重试此候选");retry.addEventListener("click",async()=>{retry.disabled=true;try{applyState(await api("/api/retry-preview",{key:item.key}));retry.textContent="候选待备";}catch(error){toast(error.message);retry.disabled=false;}});card.append(retry);}grid.append(card);}content.append(grid);
    }
  });show(state.library?.backgrounds,tabs.firstElementChild);
});
$("menu-button").addEventListener("click",async()=>{
  openModal("故事与设置");
  body.append(textEl("p",`${state.name} · ${state.user}`,"hint"));
  const speedRow=textEl("label","文字速度","setting"),slider=document.createElement("input");slider.type="range";slider.min="0";slider.max="65";slider.value=String(speed);slider.setAttribute("aria-label","文字速度");slider.addEventListener("input",()=>{speed=Number(slider.value);localStorage.setItem("yukino-public-speed",String(speed));});speedRow.append(slider);body.append(speedRow);
  const music=window.YukimaMusic.snapshot();
  const musicRow=textEl("label","背景音乐","setting"),musicToggle=document.createElement("input");musicToggle.type="checkbox";musicToggle.checked=music.enabled;musicToggle.setAttribute("aria-label","背景音乐");musicToggle.addEventListener("change",()=>window.YukimaMusic.setEnabled(musicToggle.checked));musicRow.append(musicToggle);body.append(musicRow);
  const volumeRow=textEl("label","音乐音量","setting"),volumeSlider=document.createElement("input");volumeSlider.type="range";volumeSlider.min="0";volumeSlider.max="100";volumeSlider.value=String(Math.round(music.volume*100));volumeSlider.setAttribute("aria-label","音乐音量");volumeSlider.addEventListener("input",()=>window.YukimaMusic.setVolume(Number(volumeSlider.value)/100));volumeRow.append(volumeSlider);body.append(volumeRow);
  const trackRow=textEl("label","选曲","setting"),trackSelect=document.createElement("select");trackSelect.setAttribute("aria-label","选曲");const automatic=textEl("option","随剧情切换");automatic.value="auto";trackSelect.append(automatic);for(const track of music.tracks){const option=textEl("option",track.label+" · "+track.title);option.value=track.id;trackSelect.append(option);}trackSelect.value=music.manual;trackSelect.addEventListener("change",()=>window.YukimaMusic.setTrack(trackSelect.value));trackRow.append(trackSelect);body.append(trackRow);
  const credits=textEl("button","音乐库与署名","music-credits-button");credits.addEventListener("click",()=>{openModal("音乐库与署名");body.append(textEl("p","录音：Kevin MacLeod · incompetech.com。以 CC BY 4.0 许可使用，原始音频未修改；播放时可循环和淡入淡出。","hint"));const license=textEl("a","Creative Commons Attribution 4.0");license.href="https://creativecommons.org/licenses/by/4.0/";license.target="_blank";license.rel="noopener noreferrer";body.append(license);for(const track of window.YukimaMusic.snapshot().tracks){const card=textEl("section","","music-credit");card.append(textEl("h3",track.title),textEl("p",track.label+" · "+track.duration+" · 录音 "+track.artist+" · 作曲 "+track.composer));const source=textEl("a","作者原始曲目页");source.href=track.source;source.target="_blank";source.rel="noopener noreferrer";card.append(source);body.append(card);}});body.append(credits);
  const imageRow=textEl("label","随剧情生成新画面","setting"),imageToggle=document.createElement("input");imageToggle.type="checkbox";imageToggle.checked=state.dynamic_images;imageToggle.setAttribute("aria-label","随剧情生成新画面");imageToggle.addEventListener("change",async()=>{try{applyState(await api("/api/settings",{dynamic_images:imageToggle.checked}));}catch(error){toast(error.message);imageToggle.checked=state.dynamic_images;}});imageRow.append(imageToggle);body.append(imageRow);
  const returnButton=textEl("button","返回主界面","primary");returnButton.disabled=state.busy;returnButton.addEventListener("click",async()=>{try{if(state.status!=="paused")applyState(await api("/api/pause",{}));localStorage.removeItem("yukino-public-view");modal.close();$("game").hidden=true;$("lobby").hidden=false;$("character-picker").hidden=false;$("story-picker").hidden=true;}catch(error){toast(error.message);}});body.append(returnButton);
  const pauseButton=textEl("button","暂停当前剧情","primary");pauseButton.disabled=state.busy || state.status==="paused";pauseButton.addEventListener("click",async()=>{try{applyState(await api("/api/pause",{}));modal.close();}catch(error){toast(error.message);}});body.append(pauseButton);
  const manager=textEl("button","管理存档与回收站");manager.addEventListener("click",openSaveManager);body.append(manager);body.append(textEl("h3","继续存档"));try{const result=await api("/api/sessions");if(!result.sessions.length)body.append(textEl("p","还没有保存的故事。","hint"));const tree=textEl("div","","save-tree");body.append(tree);renderSaveList(tree,result.sessions);}catch(error){body.append(textEl("p",error.message,"hint"));}
});
async function poll(){try{const nextState=await api("/api/state");applyState(nextState);}catch{if(pending && !["complete","failed"].includes(pending.stage)){pending.stage="uncertain";persistPending();renderFeedback();}$("menu-button").title="连接已中断，请重新启动游戏";}finally{setTimeout(poll,state?.busy?300:state?.transition?.active?600:1200);}}
(async()=>{try{token=(await api("/api/session-token")).token;applyState(await api("/api/state"));if(state.provider==="demo" || pending || localStorage.getItem("yukino-public-view")===state.session_id)enterGame(state);poll();}catch(error){$("lobby-notice").textContent=error.message;}})();

function updateMusicButton(){const music=window.YukimaMusic.snapshot();$("music-button").textContent=music.enabled?"♫":"♪";$("music-button").setAttribute("aria-label",music.enabled?"静音背景音乐":"开启背景音乐");$("music-button").setAttribute("aria-pressed",String(music.enabled));}
document.addEventListener("yukino-public-music-change",updateMusicButton);$("music-button").addEventListener("click",()=>window.YukimaMusic.setEnabled(!window.YukimaMusic.snapshot().enabled));updateMusicButton();

function pendingKey(){return "yukino-public-pending-"+state.session_id;}
function persistPending(){if(pending)localStorage.setItem(pendingKey(),JSON.stringify(pending));else localStorage.removeItem(pendingKey());}
function recoverPending(){
  if(pending?.session_id!==state.session_id){pending=null;receiptUntil=0;try{pending=JSON.parse(localStorage.getItem(pendingKey()) || "null");}catch{}}
  if(!pending && state.busy && state.activity?.text)pending={id:state.activity.id,text:state.activity.text,session_id:state.session_id,stage:"accepted"};
  if(!pending)return;
  if(state.turns.some(t=>t.turn_id===pending.id)){
    if(pending.stage!=="complete"){pending.stage="complete";receiptUntil=Date.now()+2400;localStorage.removeItem(pendingKey());}
  }else if(state.activity?.id===pending.id){
    pending.stage=state.activity.stage==="failed"?"failed":state.busy?"accepted":pending.stage;
    persistPending();
  }else if(!submitting && !state.busy && !["complete","failed"].includes(pending.stage)){pending.stage="uncertain";persistPending();}
}
async function sendTurn(text,id,gameplay){
  if(state.busy || submitting || cgBlocks() || state.status==="paused")return;
  pending={id:id || crypto.randomUUID().replaceAll("-",""),text,session_id:state.session_id,stage:"sending",gameplay};
  const flight=pending;
  persistPending();submitting=true;renderFeedback();$("send-button").disabled=true;$("message").value="";
  try{const result=await api(pending.gameplay?"/api/gameplay/action":"/api/turn",{text,request_id:pending.id,session_id:pending.session_id,...(pending.gameplay || {})});
    if(pending!==flight)return;
    if(result.accepted && pending.stage!=="complete"){pending.stage="accepted";persistPending();}else if(result.status==="paused"){pending=null;persistPending();applyState(result);}
  }catch(error){if(pending===flight && pending.stage!=="complete"){pending.stage=error.status>=400 && error.status<500?"failed":"uncertain";pending.error=error.message;if(error.retryAsText){delete pending.gameplay;pending.error="消息类型已纠正 · 点击重试发送原文";}persistPending();}}
  finally{submitting=false;try{applyState(await api("/api/state"));}catch{renderFeedback();}}
}
function renderFeedback(){
  const show=!!pending && (pending.stage!=="complete" || Date.now()<receiptUntil);
  $("receipt").hidden=!show;
  if(show){$("receipt-name").textContent=state.user;$("receipt-text").textContent=pending.text;
    $("receipt-stage").textContent={sending:"送出中",accepted:"已送达",complete:state.persistent?"已回应 · 已保存":"已回应",failed:"回应暂未到达 · 可重试",uncertain:"等待确认"}[pending.stage];
    if(pending.stage==="failed")$("receipt-stage").textContent=pending.error || state.error || "回应未完成 · 可重试";
    $("receipt").dataset.stage=pending.stage;$("retry-turn").hidden=!['failed','uncertain'].includes(pending.stage) || state.busy || submitting;$("retry-turn").disabled=state.status==="paused";
    $("receipt-stage").title=pending.stage==="failed"?state.error:pending.error || "";}
  $("waiting").hidden=!state.busy;
  const waitingNames=(state.activity?.waiting_actor_ids || []).map(k=>state.actors?.[k]?.name).filter(Boolean);
  const waitingActor=waitingNames.length===1?waitingNames[0]:"";
  $("waiting-text").textContent=state.activity?.stage==="saving"?"这一刻留在故事里":waitingActor?waitingActor+" · 斟酌回应":waitingNames.length>1?"交谈仍在继续":"这一刻的故事仍在延续";
  const elapsed=Math.floor(state.activity?.elapsed || 0);$("waiting-time").textContent=elapsed>=20?`${elapsed} 秒` : "";
  const tr=state.transition || {}, active=tr.active && !playingCg();
  $("transition").hidden=!active;$("transition-target").textContent=tr.target || "";
  const moving=['queued','painting'].includes(tr.status);
  $("game").classList.toggle("scene-in-transit",active && moving);
  $("transition-label").textContent=moving?"场景过渡":tr.status==="failed"?"暂留此景 · 新画面未能就绪":"暂留此景";
  $("retry-image").hidden=!active || tr.status!=="failed" || !state.dynamic_images;
  renderChoices();
}
function renderChoices(){
  if(!state)return;
  const items=state.story?.choices || [], allowed=!cgBlocks() && !state.busy && !submitting && state.status!=="paused" && frameIndex===state.frames.length-1 && typed>=currentFrame()?.text.length;
  $("choices").hidden=!allowed || !items.length;
  const signature=JSON.stringify(items);if(signature===choicesSignature)return;choicesSignature=signature;$("choices").replaceChildren();
  for(const choice of items){const text=choice.text.startsWith("【")?choice.text:"【语言】"+choice.text;const b=textEl("button",text);b.title=text;b.addEventListener("click",()=>{$("message").value=text;$("message").focus();renderInputPrefixes();});$("choices").append(b);}
}
$("plot-button").addEventListener("click",()=>{
  openModal("剧情脉络");body.append(exportBar("plot"));const story=state.story || {nodes:[]};
  body.append(textEl("p","当前：剧情分支 "+(state.branch?.label || "主线")+" · 回溯会保留原存档，另开独立故事。","hint"));
  if(story.thread)body.append(textEl("p",story.thread,"plot-thread"));
  const route=textEl("div","","plot-route");body.append(route);
  const labels={setup:"铺垫",development:"发展",revelation:"揭示",turning_point:"转折",resolution:"收束"};
  for(const [i,node] of story.nodes.entries()){
    const section=textEl("section","","plot-node"+(node.milestone?" milestone":"")+(i===story.nodes.length-1?" current":""));
    section.append(textEl("small",`${String(i+1).padStart(2,"0")} · ${labels[node.beat] || "发展"}`),textEl("h3",node.title));
    if(node.cg_url){const img=document.createElement("img");img.src=safeAsset(node.cg_url);img.alt=node.title;section.append(img);}
    if(node.scene)section.append(textEl("p",node.scene));
    const actions=textEl("div","","plot-actions"),review=textEl("button","回看这一幕");
    review.addEventListener("click",()=>{openModal(node.title);const turn=state.turns[node.turn_index];if(turn)body.append(historyCard(turn));if(node.cg_url){const img=document.createElement("img");img.className="gallery-full";img.src=safeAsset(node.cg_url);img.alt=node.title;body.append(img);}});actions.append(review);
    if(node.can_branch){const branch=textEl("button","回溯到这里 · 新建分支");branch.disabled=state.busy;branch.addEventListener("click",async()=>{branch.disabled=true;try{enterGame(await api("/api/branch",{node_id:node.id,session_id:state.session_id}));modal.close();toast("回溯分支已存档 · "+(state.branch?.label || ""),true);}catch(error){toast(error.message);branch.disabled=false;}});actions.append(branch);}
    section.append(actions);route.append(section);
  }
  if(story.choices?.length){const next=textEl("section","","plot-possibilities");next.append(textEl("small","可选方向 · 也可自由回应"));for(const c of story.choices)next.append(textEl("span",c.label));route.append(next);}
});

let preloadedPredictionUrls=new Set();
function preloadPredictions(){
  for(const url of state.prediction_preloads || []){
    const safe=safeAsset(url);if(!safe || preloadedPredictionUrls.has(safe))continue;
    preloadedPredictionUrls.add(safe);const image=new Image();image.src=safe;image.decode().catch(()=>preloadedPredictionUrls.delete(safe));
  }
}
function renderInputPrefixes(){for(const button of document.querySelectorAll("[data-prefix]"))button.disabled=state.busy || submitting || state.status==="paused";}
for(const button of document.querySelectorAll("[data-prefix]"))button.addEventListener("click",()=>{
  const input=$("message"),prefix="【"+button.dataset.prefix+"】",start=input.selectionStart,end=input.selectionEnd;
  const line=start>0 && input.value[start-1]!=="\n"?"\n":"";
  input.setRangeText(line+prefix,start,end,"end");input.focus();input.dispatchEvent(new Event("input"));
});
function renderSaveList(container,saves,options={}){
  container.replaceChildren();container.classList.remove("save-tree");container.classList.add("save-list");
  const groups=window.YukimaSaveMap.forest(saves);
  const toolbar=textEl("div","","save-list-toolbar"),count=textEl("span","","hint");toolbar.append(count);container.append(toolbar);
  let search;
  if(options.search!==false){search=document.createElement("input");search.type="search";search.placeholder="搜索故事、分支剧情或备注";search.setAttribute("aria-label","搜索故事存档");search.className="save-search";toolbar.append(search);}
  const grid=textEl("div","","save-card-grid");container.append(grid);
  function draw(){
    const q=search?.value.trim().toLowerCase() || options.query?.trim().toLowerCase() || "";
    const shown=groups.filter(g=>g.members.some(s=>[s.title,s.latest_event,s.note,s.summary,s.id].join(" ").toLowerCase().includes(q)));
    count.textContent=`${shown.length} 条故事 · ${shown.reduce((n,g)=>n+g.members.length,0)} 份存档`;grid.replaceChildren();
    for(const group of shown){
      const save=group.root,card=textEl("article","","save-card save-family-card");card.dataset.session=save.id;card.dataset.family=group.id;
      const current=group.members.some(s=>s.id===state.session_id);if(current)card.classList.add("current-save");
      const header=textEl("div","","save-card-header");header.append(textEl("span",current?"当前故事":"故事起点","save-kind"),textEl("small",`起始存档 #${save.id.slice(0,8)}`,"save-id"));card.append(header);
      card.append(textEl("h3",save.title),textEl("p",`${group.members.length} 份存档 · 最近进度 ${group.latest.turn_count || 0} 回合`,"save-card-meta"));
      card.append(textEl("p","最近一幕 · "+(group.latest.latest_event || group.latest.scene || "故事开场"),"save-script-label"));
      card.append(textEl("p",save.summary || save.scene || "故事刚刚开始。","save-preview"));
      const open=textEl("button","查看存档分支 →","save-family-open");open.addEventListener("click",()=>window.YukimaSaveMap.open(group,options));card.append(open);grid.append(card);
    }
    if(!shown.length)grid.append(textEl("p",q?"没有符合条件的故事。":"还没有保存的故事。","hint"));
  }
  search?.addEventListener("input",draw);draw();
}

function renderWorldPicker(script){
  const catalog=state.world_catalog || {worlds:[],setting_sets:[]},world=catalog.worlds.find(w=>w.id===script.world_id);
  $("world-select").replaceChildren();const o=textEl("option",world?.name || "角色卡背景");o.value=script.world_id || "";o.selected=true;$("world-select").append(o);
  $("setting-select").replaceChildren();for(const id of script.setting_set_ids || []){const set=catalog.setting_sets.find(s=>s.id===id);const option=textEl("option",set?.name || id);option.value=id;option.selected=true;$("setting-select").append(option);}
  $("world-description").textContent=script.bio;$("script-settings-summary").textContent=(script.setting_set_ids || []).map(id=>catalog.setting_sets.find(s=>s.id===id)?.name || id).join(" · ") || "角色卡内的人物与场景";
  $("protagonist-select").replaceChildren();for(const p of state.protagonists || []){const option=textEl("option",p.name);option.value=p.id;$("protagonist-select").append(option);}$("protagonist-select").value=script.default_protagonist_id || "hachiman";
}

// Profiles are fetched only when opened, outside the dialogue polling path.
let profileRequest=0;
function profilePortrait(card,large=false){
  const wrap=textEl("div","","profile-portrait"+(large?" large":""));
  wrap.append(textEl("span",card.name.slice(0,1),"portrait-monogram"));
  const url=safeAsset(card.avatar);
  if(url){const img=document.createElement("img");img.src=url;img.alt=card.name+"头像";img.loading="lazy";img.addEventListener("load",()=>wrap.classList.add("has-image"));img.addEventListener("error",()=>img.remove());wrap.append(img);}
  return wrap;
}
function showProfileDetail(card,catalog,kind){
  body.replaceChildren();$("modal-title").textContent=card.name;
  const back=textEl("button","← 返回卡片列表","profile-back");back.addEventListener("click",()=>showProfileGrid(catalog,kind));body.append(back);
  const article=textEl("article","","profile-detail");
  const header=textEl("header","","profile-detail-header"),identity=textEl("div","","profile-identity");
  identity.append(textEl("small",kind==="protagonist"?"主角档案":"人物档案","eyebrow"),textEl("h3",card.name),textEl("p","年龄 · "+card.age,"profile-age"));
  if(card.aliases?.length)identity.append(textEl("p",card.aliases.join(" / "),"profile-aliases"));
  header.append(profilePortrait(card,true),identity);article.append(header);
  for(const [label,content] of [["人物简介",card.description],["性格",card.personality],["外貌",card.appearance]])if(content){const section=document.createElement("section");section.append(textEl("h4",label),textEl("p",content));article.append(section);}
  if(kind==="protagonist"){const choose=textEl("button","使用这张主角卡","primary");choose.addEventListener("click",()=>{$("protagonist-select").value=card.id;modal.close();});article.append(choose);}
  const source=card.source;if(typeof source==="string" && /^https:\/\//.test(source)){const link=textEl("a","资料来源","profile-source");link.href=source;link.target="_blank";link.rel="noopener noreferrer";article.append(link);}
  if(card.avatar?.startsWith("/profiles/oregairu/"))article.append(textEl("small","头像：TBS 官方人物图 · ©渡 航、小学館／やはりこの製作委員会はまちがっている。完","profile-credit"));
  body.append(article);
}
function showProfileGrid(catalog,kind){
  body.replaceChildren();$("modal-title").textContent=catalog.title;modal.classList.add("profile-modal");
  body.append(textEl("p",kind==="protagonist"?"查看主角设定，选择你想使用的卡片。":"点击人物卡，查看详细资料。","hint"));
  const grid=textEl("div","","profile-grid");
  for(const card of catalog.cards){const button=textEl("button","","profile-mini");button.setAttribute("aria-label","查看人物卡 "+card.name);const info=document.createElement("div");info.append(textEl("h3",card.name),textEl("small","年龄 · "+card.age,"profile-age"),textEl("p",card.summary));button.append(profilePortrait(card),info,textEl("span","↗","profile-arrow"));button.addEventListener("click",()=>showProfileDetail(card,catalog,kind));grid.append(button);}
  if(!catalog.cards.length)grid.append(textEl("p","这个剧本还没有人物卡。","hint"));body.append(grid);
}
async function openProfiles(kind){
  const request=++profileRequest;openModal(kind==="protagonist"?"主角卡":"人物图鉴");modal.classList.add("profile-modal");body.append(textEl("p","正在展开档案……","hint"));
  try{const catalog=await api(kind==="protagonist"?"/api/profiles?kind=protagonist":"/api/profiles?script="+encodeURIComponent(selectedCardId));if(request===profileRequest && modal.open)showProfileGrid(catalog,kind);}
  catch(error){if(request===profileRequest && modal.open)body.replaceChildren(textEl("p",error.message,"hint"));}
}
$("view-script-cards").addEventListener("click",()=>openProfiles("script"));
$("view-protagonist-cards").addEventListener("click",()=>openProfiles("protagonist"));

let affinitySignature="";
function affinityDelta(value){return value>0?" +"+value:value<0?" "+value:"";}
function renderAffinityBadge(){
  const frame=currentFrame(),item=state?.affinity?.characters.find(c=>c.actor_id===frame?.actor_id),badge=$("affinity-badge");
  badge.hidden=!item || frame?.kind==="narration" || frame?.actor_id==="player";
  if(item){badge.textContent="♡ "+item.score+" · "+item.status+affinityDelta(item.delta);badge.setAttribute("aria-label",item.name+"好感度 "+item.score+"，"+item.status+"，查看人物好感度");badge.dataset.delta=String(Math.sign(item.delta));}
}
function renderAffinities(){
  const items=state?.affinity?.characters || [],signature=JSON.stringify(items);
  if(signature===affinitySignature && body.childElementCount)return;affinitySignature=signature;body.replaceChildren();
  const grid=textEl("div","","affinity-grid");
  for(const item of items){const card=textEl("article","","affinity-card"),header=textEl("header","","affinity-card-header"),identity=document.createElement("div");
    identity.append(textEl("h3",item.name),textEl("small",item.status,"affinity-status"));header.append(profilePortrait(item),identity);
    const score=textEl("div","","affinity-score");score.append(textEl("strong",String(item.score)),textEl("small"," / 100"));
    if(item.delta){const delta=textEl("span",affinityDelta(item.delta).trim(),"affinity-delta");delta.dataset.sign=String(Math.sign(item.delta));score.append(delta);}
    const meter=document.createElement("progress");meter.max=100;meter.value=item.score;meter.setAttribute("aria-label",item.name+"好感度");
    card.append(header,score,meter);grid.append(card);
  }
  if(!items.length)grid.append(textEl("p","相遇之后，彼此的关系会慢慢展开。","hint"));body.append(grid);
}
function openAffinities(){openModal("人物好感度");modal.classList.add("affinity-modal");affinitySignature="";renderAffinities();}
$("affinity-button").addEventListener("click",openAffinities);
$("affinity-badge").addEventListener("click",openAffinities);

let thoughtSignature="";
function renderThoughts(){
  $("export-thoughts").replaceChildren(exportBar("thoughts"));
  const entries=state.inner_thoughts || [],signature=state.session_id+"|"+JSON.stringify(entries);
  if(signature===thoughtSignature)return;thoughtSignature=signature;
  const list=$("thought-list");list.replaceChildren();
  if(!entries.length)list.append(textEl("p","尚未记录人物心声。","thought-empty"));
  for(const entry of entries){const card=textEl("article","","thought-entry");card.append(textEl("strong",entry.name),textEl("small",entry.scene),textEl("p",entry.text));list.append(card);}
  $("thought-button").textContent=entries.length?"心声 · "+entries.length:"心声";
  list.scrollTop=list.scrollHeight;
}
$("thought-button").addEventListener("click",()=>openThoughtPage());
$("close-thoughts").addEventListener("click",()=>{$("thought-panel").hidden=true;$("thought-button").setAttribute("aria-expanded","false");});

function historyCard(turn){
  const block=textEl("section","","log-turn");
  if(turn.saved_at)block.append(textEl("small",turn.saved_at,"hint"));
  if(turn.user)block.append(textEl("small",state.user),textEl("p",turn.user,"log-user"));
  if(turn.frames?.length){for(const frame of turn.frames){block.append(textEl("small",frame.kind==="narration"?"旁白":frame.speaker || "未标注人物"),textEl("p",frame.text,frame.kind));}}
  else block.append(textEl("small","历史文本"),textEl("p",turn.assistant.replaceAll("*","")));
  return block;
}
function exportBar(scope){
  const row=textEl("div","","export-bar");
  for(const [label,format,part] of [["导出文本","txt",scope],["导出 Markdown","md",scope],["导出完整故事","txt","all"]]){
    const link=textEl("a",label);link.className="export-link";
    link.href="/api/export?"+new URLSearchParams({session_id:state.session_id,scope:part,format});link.setAttribute("download","");row.append(link);
  }return row;
}
function cgId(){const cue=state?.cg_cue;return cue?.key?state.session_id+":"+cue.turn_id+":"+cue.key:"";}
function cgBlocks(){return !!cgId() && !cgDismissed.has(cgId());}
function cgAtCue(){return frameIndex===state?.frames.length-1 && typed>=currentFrame()?.text.length;}
function playingCg(){return cgAtCue() && cgDecoded.has(cgId()) && !cgSkipped.has(cgId())?state.cg_cue.url:"";}
function renderCg(){
  const id=cgId(),cue=state?.cg_cue || {},active=cgBlocks() && cgAtCue() && !state.busy;
  const ready=cgDecoded.has(id),failed=cue.status==="failed" || cgDecodeFailed.has(id);
  $("cg-wait").hidden=!active;$("game").classList.toggle("awaiting-cg",active && !ready);
  $("cg-wait").classList.toggle("is-ready",ready);$("cg-skip").hidden=ready;
  $("cg-wait-title").textContent=cue.title || "这一幕";
  $("cg-wait-status").textContent=ready?"这一幕，已经展开":failed?"这幅画面暂未抵达":"为这一幕，稍作停留";
  $("cg-continue").hidden=!ready;$("cg-skip").textContent=failed?"继续故事 · 稍后到画廊查看":"先继续故事";
  $("cg-retry").hidden=!failed || !state.dynamic_images;
  $("send-button").disabled=state.provider==="demo" || state.busy || submitting || state.status==="paused" || cgBlocks();
  // Keep the draft editable while waiting; sending and choices stay gated.
  if(active && cue.url && !ready && !cgDecoding.has(id) && !cgDecodeFailed.has(id)){
    cgDecoding.add(id);const im=new Image();im.src=safeAsset(cue.url);
    im.decode().then(()=>{cgDecoded.add(id);if(cgId()===id){visualKey="";renderVisual();renderCg();}}).catch(()=>{cgDecodeFailed.add(id);if(cgId()===id)renderCg();}).finally(()=>cgDecoding.delete(id));
  }
}
function finishCg(skip=false){const id=cgId();if(!id)return;cgDismissed.add(id);if(skip)cgSkipped.add(id);visualKey="";renderCg();renderVisual();updateContinue();$("message").focus();}
$("cg-continue").addEventListener("click",()=>finishCg());
$("cg-skip").addEventListener("click",()=>finishCg(true));
$("cg-retry").addEventListener("click",async()=>{cgDecodeFailed.delete(cgId());try{applyState(await api("/api/retry-images",{}));renderCg();}catch(error){toast(error.message);}});
