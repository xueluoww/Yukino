"use strict";
(() => {
  const clamp = value => Math.max(0, Math.min(1, value));
  const rawVolume = Number(localStorage.getItem("yukino-public-music-volume") ?? .25);
  let volume = Number.isFinite(rawVolume) ? clamp(rawVolume) : .25;
  let enabled = localStorage.getItem("yukino-public-music-enabled") !== "false";
  let manual = localStorage.getItem("yukino-public-music-track") || "auto";
  let library = [], unlocked = false, active = 0, current = "", desired = "", switching = false;
  let generation = 0, lastSwitch = 0, lastState, inGame = false, failed = "";
  const players = [0, 1].map(() => {
    const audio = document.createElement("audio");
    audio.loop = true; audio.preload = "none"; audio.hidden = true; audio.volume = 0;
    audio.setAttribute("aria-hidden", "true"); document.body.append(audio); return audio;
  });
  function chooseMood(state) {
    const frames = state?.frames || [];
    // Use the displayed moment, not historical memories or hypothetical player input.
    const text = frames.map(f => f.text || "").join("。").split(/[。！？\n]/)
      .filter(s => !/(没有|并未|并不|不会|不再|假如|如果|倘若|免得|避免|别担心)/.test(s)).join("。");
    if (/(惊恐|恐惧|危险逼近|争吵|愤怒|剑拔弩张|威胁|不安地|紧张地)/.test(text)) return "tense";
    if (state?.visual?.expression === "sad" || /(流泪|泪水|哭泣|悲伤|哽咽|失落|心痛|悲痛)/.test(text)) return "sad";
    if (["soft", "shy", "happy"].includes(state?.visual?.expression) || /(微笑|温柔|脸红|羞涩|心动|安慰)/.test(text)) return "warm";
    if (["serious", "thinking", "troubled", "displeased"].includes(state?.visual?.expression) || /rain|night|dusk|evening/.test(state?.visual?.background || "") || /雨|夜|黄昏|沉思|暮色/.test(state?.location || "")) return "reflective";
    return "calm";
  }
  function notify() { document.dispatchEvent(new CustomEvent("yukino-public-music-change")); }
  function stop() {
    generation++; switching = false;
    players.forEach(audio => { audio.pause(); audio.volume = 0; });
  }
  async function playDesired(force = false) {
    if (!enabled || !unlocked || !desired || (inGame && lastState?.status === "paused")) return;
    const track = library.find(t => t.id === desired);
    if (!track) return;
    if (current === desired) {
      if (!switching) { players[active].volume = volume; players[active].play().catch(() => {}); }
      return;
    }
    if (switching || (!force && current && performance.now() - lastSwitch < 12000)) return;
    switching = true; const ticket = ++generation;
    const outgoing = players[active], incoming = players[1 - active];
    incoming.pause(); incoming.src = track.url; incoming.volume = 0;
    try {
      await incoming.play();
      if (ticket !== generation) { incoming.pause(); return; }
      const started = performance.now(), outgoingVolume = outgoing.volume;
      await new Promise(resolve => {
        function fade(now) {
          if (ticket !== generation) { resolve(); return; }
          const progress = Math.min(1, (now - started) / 1600);
          outgoing.volume = clamp(outgoingVolume * (1 - progress)); incoming.volume = clamp(volume * progress);
          if (progress < 1) requestAnimationFrame(fade); else resolve();
        }
        requestAnimationFrame(fade);
      });
      if (ticket !== generation) return;
      outgoing.pause(); outgoing.volume = 0; active = 1 - active;
      current = track.id; failed = ""; lastSwitch = performance.now();
    } catch {
      if (ticket === generation) { incoming.pause(); failed = track.id; }
    } finally { if (ticket === generation) switching = false; notify(); }
  }
  function refresh(state, gameVisible) {
    lastState = state; inGame = gameVisible;
    desired = manual !== "auto" && library.some(t => t.id === manual) ? manual : inGame ? chooseMood(state) : "calm";
    if (inGame && state?.status === "paused") { if (players.some(p => !p.paused)) stop(); return; }
    playDesired();
  }
  document.addEventListener("pointerdown", () => { unlocked = true; playDesired(); }, {capture: true});
  document.addEventListener("keydown", () => { unlocked = true; playDesired(); }, {capture: true});
  window.YukimaMusic = {
    refresh,
    setEnabled(value) {
      enabled = Boolean(value); localStorage.setItem("yukino-public-music-enabled", String(enabled));
      if (!enabled) stop(); else { unlocked = true; playDesired(true); } notify();
    },
    setVolume(value) {
      volume = clamp(Number(value) || 0); localStorage.setItem("yukino-public-music-volume", String(volume));
      if (!switching) players[active].volume = enabled ? volume : 0; notify();
    },
    setTrack(value) {
      manual = library.some(t => t.id === value) ? value : "auto";
      localStorage.setItem("yukino-public-music-track", manual); refresh(lastState, inGame); playDesired(true); notify();
    },
    snapshot: () => ({enabled, volume, manual, tracks: library, current, failed, playing: players.some(p => !p.paused)}),
  };
  fetch("/music/library.json").then(r => { if (!r.ok) throw new Error(); return r.json(); }).then(data => {
    library = data.tracks.filter(t => typeof t.id === "string" && /^\/music\/[\w-]+\.mp3$/.test(t.url));
    refresh(lastState, inGame); notify();
  }).catch(() => {});
})();
