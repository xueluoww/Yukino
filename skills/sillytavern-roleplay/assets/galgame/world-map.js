"use strict";
// The backend supplies only the player's knowledge. No requests to mutate the map.
window.YukimaWorldMap = (() => {
  let generation = 0;
  const labels = {room: "房间", floor: "楼层", building: "建筑", campus: "校园", outdoor: "户外", connector: "通道", region: "区域"};
  function prepare(text) {
    if (state.busy || cgBlocks()) return;
    modal.close();
    const input = $("message");
    input.value = text;
    input.dispatchEvent(new Event("input", {bubbles: true}));
    input.focus();
  }
  async function open(page = "map") {
    const request = ++generation;
    const sid = state.session_id, revision = state.revision;
    openModal(page === "map" ? "已知地图" : page === "school" ? "今日课表" : "已知约定");
    engineTabs([["返回手记", openStory], ["地图", () => open("map")], ["已知约定", () => open("appointments")], ["今日课表", () => open("school")]]);
    const content = textEl("section", "", "world-navigation");
    const status = textEl("p", "正在整理你已知的地点…", "hint");
    content.append(status); body.append(content);
    try {
      const query = new URLSearchParams({session_id: sid});
      if (revision != null) query.set("revision", revision);
      const result = await api("/api/world-map?" + query);
      if (request !== generation || !modal.open || state.session_id !== sid) return;
      if (revision != null && state.revision !== revision) {
        status.textContent = "故事已更新，请重新打开地图。"; return;
      }
      content.replaceChildren();
      if (page === "school") {
        const school=result.school || {enabled:false,periods:[]};
        content.append(textEl("p",school.enabled ? `第 ${school.day} 天 · ${school.label}` : "当前剧本未设置课表。","hint"));
        if(school.note) content.append(textEl("p",school.note,"hint"));
        const time=m=>`${String(Math.floor(m/60)).padStart(2,"0")}:${String(m%60).padStart(2,"0")}`;
        const attendance=school.attendance?.day===school.day ? school.attendance.entries || [] : [];
        const labels={present:"检查时在场",late:"迟到后在场",absent:"检查时未在场",left_early:"曾在场，之后离开",unknown:"尚无实际检查记录"};
        for(const p of school.periods || []) {
          const row=attendance.find(r=>r.id===p.id);
          content.append(engineCard(p.title,p.location,`${time(p.start)}–${time(p.end)} · ${labels[row?.status || "unknown"]}`));
        }
        if(school.enabled && !school.periods.length) content.append(textEl("p","今天没有安排正课，可自行安排活动。","hint"));
        return;
      }
      content.append(textEl("p", page === "map" ? "这里记录你已经知道的地点与通路。选择行动后可在输入框确认或修改。" : "这里只记录人物实际向你说过的安排；是否赴约仍由你决定。", "hint"));
      if (page === "appointments") {
        if (!result.appointments.length) content.append(textEl("p", "尚未听到明确的约定。", "hint"));
        for (const notice of result.appointments) {
          const minute = notice.due_at;
          const time = `第 ${Math.floor(minute / 1440) + 1} 天 · ${String(Math.floor(minute % 1440 / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
          content.append(engineCard(notice.text, "对方实际表达的安排，不代表你已经答应。", time));
        }
        return;
      }
      const nodes = new Map(result.map.nodes.map(n => [n.id, n]));
      if(result.journey?.status==="paused" && nodes.has(result.journey.target)) {
        const target=nodes.get(result.journey.target);
        const resume=textEl("button","继续前往"+target.name,"engine-action");
        resume.disabled=state.busy;resume.addEventListener("click",()=>prepare("【动作】前往"+target.name));content.append(resume);
      }
      const visited = new Set();
      function draw(node, depth) {
        if (visited.has(node.id)) return;
        visited.add(node.id);
        const current = node.id === result.map.location;
        const card = engineCard(node.name, node.description, (current ? "你在这里 · " : "") + (labels[node.kind] || "地点") + (node.visited ? " · 到访过" : ""));
        card.classList.add("world-map-card");
        card.dataset.depth = String(Math.min(depth, 8));
        if (current) card.classList.add("world-map-current");
        const routes = Object.entries(node.links).map(([id, minutes]) => `${nodes.get(id)?.name || "已知通路"} · ${minutes} 分钟`);
        if (routes.length) card.append(textEl("p", "通往：" + routes.join("、"), "world-map-routes"));
        if (node.walkable && !current && node.route_known) {
          const action = textEl("button", "前往这里", "engine-action");
          action.disabled = state.busy;
          action.addEventListener("click", () => prepare("【动作】前往" + node.name));
          card.append(action);
        }
        if (current && result.exploration) {
          const action = textEl("button", "探索附近", "engine-action");
          action.disabled = state.busy;
          action.addEventListener("click", () => prepare("【动作】探索当前区域"));
          card.append(action);
        }
        content.append(card);
        for (const child of result.map.nodes.filter(n => n.parent_id === node.id)) draw(child, depth + 1);
      }
      for (const node of result.map.nodes.filter(n => !n.parent_id || !nodes.has(n.parent_id))) draw(node, 0);
      if (!nodes.size) content.append(textEl("p", "尚未记录可展示的地点。", "hint"));
    } catch (error) {
      if (request === generation && modal.open) status.textContent = error.message;
    }
  }
  return {open};
})();
$("game-world-map").addEventListener("click", () => window.YukimaWorldMap.open());
