// Reel viewer: renders a reel deterministically from reel time.
//
// Everything visible at reel time t (sprite positions and frames, camera,
// chat panel, fades) is a pure function of t and the data in
// /data/extract.json and /data/timeline.json. That is what lets
// `window.reel.seek(t)` produce identical frames for video capture.
(() => {
  "use strict";

  const params = new URLSearchParams(location.search);
  const CAPTURE = params.has("capture");
  const TILE = 32;
  const VIEW_W = 1100, VIEW_H = 900;
  const CAM_SAMPLE_HZ = 30;
  const MAX_MESSAGES = 6;
  const A = "/assets/the_ville/visuals/map_assets/";
  // [phaser key, Tiled tileset name, image path]
  const TILESETS = [
    ["blocks_1", "blocks", A + "blocks/blocks_1.png"],
    ["walls", "Room_Builder_32x32", A + "v1/Room_Builder_32x32.png"],
    ["interiors_pt1", "interiors_pt1", A + "v1/interiors_pt1.png"],
    ["interiors_pt2", "interiors_pt2", A + "v1/interiors_pt2.png"],
    ["interiors_pt3", "interiors_pt3", A + "v1/interiors_pt3.png"],
    ["interiors_pt4", "interiors_pt4", A + "v1/interiors_pt4.png"],
    ["interiors_pt5", "interiors_pt5", A + "v1/interiors_pt5.png"],
  ];
  for (const n of ["Field_B", "Field_C", "Harbor_C", "Village_B", "Forest_B", "Desert_C", "Mountains_B", "Desert_B", "Forest_C"]) {
    TILESETS.push(["CuteRPG_" + n, "CuteRPG_" + n, A + "cute_rpg_word_VXAce/tilesets/CuteRPG_" + n + ".png"]);
  }
  // Layer names come from Tiled; note the trailing space in "Interior Furniture L2 ".
  const LAYERS = ["Bottom Ground", "Exterior Ground", "Exterior Decoration L1", "Exterior Decoration L2",
    "Interior Ground", "Wall", "Interior Furniture L1", "Interior Furniture L2 ", "Foreground L1", "Foreground L2"];

  let EX, TL, CAM;
  let spans, speechBySeg, facing, camPath;
  let tNow = 0, playing = false, speed = 1;
  let lastPanelKey = "";
  const sprites = {}, emojis = {}, missingAtlas = new Set();
  const audioEls = {}, audioStarted = new Set();

  const $ = (id) => document.getElementById(id);
  const keyOf = (name) => name.split(" ").join("_");
  const initials = (name) => name.split(" ").map((w) => w[0]).join("");
  const lerp = (a, b, f) => a + (b - a) * f;
  const ease = (f) => (f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2);

  // ---------------------------------------------------------------------------
  // Data prep
  // ---------------------------------------------------------------------------

  function dirOf(dx, dy) {
    if (Math.abs(dx) >= Math.abs(dy)) return dx > 0 ? "right" : "left";
    return dy > 0 ? "down" : "up";
  }

  function prep() {
    spans = TL.spans;
    speechBySeg = TL.segments.map((_, i) => TL.speech.filter((s) => s.seg === i).sort((a, b) => a.t0 - b.t0));
    // facing[seg][persona][i]: direction of the last move at or before step index i.
    facing = EX.segments.map((seg) => {
      const out = {};
      for (const [name, tr] of Object.entries(seg.tracks)) {
        const f = new Array(tr.xy.length);
        let d = "down";
        for (let i = 0; i < tr.xy.length; i++) {
          if (i > 0) {
            const dx = tr.xy[i][0] - tr.xy[i - 1][0], dy = tr.xy[i][1] - tr.xy[i - 1][1];
            if (dx || dy) d = dirOf(dx, dy);
          }
          f[i] = d;
        }
        out[name] = f;
      }
      return out;
    });
  }

  // (span, fraction) at reel time t.
  function spanAt(t) {
    let lo = 0, hi = spans.length - 1;
    if (t >= spans[hi].t1) return [spans[hi], 1];
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (spans[mid].t0 <= t) lo = mid; else hi = mid - 1;
    }
    const sp = spans[lo];
    return [sp, Math.min(1, Math.max(0, (t - sp.t0) / (sp.t1 - sp.t0)))];
  }

  function simAt(t) {
    const [sp, f] = spanAt(t);
    return { seg: sp.seg, span: sp, f, step: sp.s0 + f * (sp.s1 - sp.s0) };
  }

  // Pixel position, animation frame and step index of a persona at a fractional step.
  function personaAt(segIdx, name, step) {
    const seg = EX.segments[segIdx];
    const xy = seg.tracks[name].xy;
    const n = xy.length;
    const x = step - seg.step0;
    const i0 = Math.max(0, Math.min(n - 1, Math.floor(x)));
    const i1 = Math.min(i0 + 1, n - 1);
    const f = i1 > i0 ? Math.max(0, x - i0) : 0;
    const a = xy[i0], b = xy[i1];
    const moving = f > 0 && (a[0] !== b[0] || a[1] !== b[1]);
    const tx = lerp(a[0], b[0], moving ? f : 0), ty = lerp(a[1], b[1], moving ? f : 0);
    const dir = moving ? dirOf(b[0] - a[0], b[1] - a[1]) : facing[segIdx][name][i0];
    const frame = moving ? `${dir}-walk.${String(Math.floor(f * 4) % 4).padStart(3, "0")}` : dir;
    return { px: tx * TILE + TILE / 2, py: ty * TILE + TILE, frame, i: i0 };
  }

  function labelAt(segIdx, name, stepIdx) {
    const seg = EX.segments[segIdx];
    const labels = seg.tracks[name].labels;
    const step = seg.step0 + stepIdx;
    let best = labels[0];
    for (const lb of labels) { if (lb[0] <= step) best = lb; else break; }
    return best;
  }

  // ---------------------------------------------------------------------------
  // Camera: precomputed pans so that the camera is a pure function of t.
  // ---------------------------------------------------------------------------

  function clampCenter(x, y) {
    const vw = VIEW_W / CAM.zoom, vh = VIEW_H / CAM.zoom;
    const mw = 140 * TILE, mh = 100 * TILE;
    return [Math.min(Math.max(x, vw / 2), mw - vw / 2), Math.min(Math.max(y, vh / 2), mh - vh / 2)];
  }

  function evalPan(p, t) {
    const f = p.dur > 0 ? ease(Math.min(1, Math.max(0, (t - p.t) / p.dur))) : 1;
    return [lerp(p.from[0], p.to[0], f), lerp(p.from[1], p.to[1], f)];
  }

  function computeCamPath() {
    const path = [];
    const margin = CAM.edge_margin_tiles * TILE;
    const halfW = VIEW_W / CAM.zoom / 2, halfH = VIEW_H / CAM.zoom / 2;
    const dur = CAM.pan_ms / 1000;
    let lastSeg = -1;
    for (let k = 0; k <= Math.ceil(TL.duration * CAM_SAMPLE_HZ); k++) {
      const t = k / CAM_SAMPLE_HZ;
      const st = simAt(t);
      const p = personaAt(st.seg, EX.persona, st.step);
      const fy = p.py - TILE / 2;
      if (st.seg !== lastSeg) {
        const c = clampCenter(p.px, fy);
        path.push({ t, from: c, to: c, dur: 0 });
        lastSeg = st.seg;
        continue;
      }
      const cur = path[path.length - 1];
      if (t < cur.t + cur.dur) continue; // still panning
      const [cx, cy] = cur.to;
      if (Math.abs(p.px - cx) > halfW - margin || Math.abs(fy - cy) > halfH - margin) {
        const to = clampCenter(p.px, fy);
        if (Math.hypot(to[0] - cx, to[1] - cy) > TILE) path.push({ t, from: [cx, cy], to, dur });
      }
    }
    return path;
  }

  function cameraAt(t) {
    let p = camPath[0];
    for (const q of camPath) { if (q.t <= t) p = q; else break; }
    return evalPan(p, t);
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  function activeSpeech(segIdx, t) {
    return speechBySeg[segIdx].filter((s) => s.t0 <= t && t < s.t1);
  }

  function render(t) {
    const st = simAt(t);
    const seg = EX.segments[st.seg];
    const speaking = {};
    for (const s of activeSpeech(st.seg, t)) speaking[s.speaker] = s.kind === "monologue" ? "💭" : "💬";

    for (const name of EX.personas) {
      const p = personaAt(st.seg, name, st.step);
      const spr = sprites[name];
      spr.setPosition(p.px, p.py);
      spr.setFrame(p.frame);
      spr.setDepth(1 + p.py / 100000);
      const emo = emojis[name];
      emo.setText(speaking[name] || labelAt(st.seg, name, p.i)[1] || "");
      emo.setPosition(p.px, p.py - 44);
      if (name === EX.persona) sprites._tag.setPosition(p.px, p.py + 2);
    }
    const [cx, cy] = cameraAt(t);
    scene.cameras.main.centerOn(cx, cy);

    let fade = 0;
    if (st.span.mode === "fade_in") fade = 1 - st.f;
    else if (st.span.mode === "fade_out") fade = st.f;
    $("fade").style.opacity = fade.toFixed(3);

    renderPanel(st, seg, t);
    if (!$("debug").hidden) renderDebug(st, seg, t);
  }

  function clockText(seg, step) {
    const iso = seg.clock[Math.max(0, Math.min(seg.clock.length - 1, Math.floor(step - seg.step0)))];
    const d = new Date(iso);
    return {
      time: d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }),
      day: d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }),
    };
  }

  function placeText(seg, step) {
    const a = seg.activities.find((x) => x.start_step <= step && step <= x.end_step);
    if (!a) return "";
    if (a.chat_with) return `talking with ${a.chat_with}`;
    const parts = a.address.split(":").filter((p) => p && p !== "the Ville");
    return parts.slice(0, 2).join(" · ");
  }

  function renderPanel(st, seg, t) {
    const c = clockText(seg, st.step);
    $("clock").textContent = c.time;
    $("scene").textContent = `${c.day} · ${EX.persona} · ${placeText(seg, Math.floor(st.step))}`;

    const shown = speechBySeg[st.seg].filter((s) => s.t0 <= t).slice(-MAX_MESSAGES);
    const last = shown[shown.length - 1];
    const nWords = (s) => (t >= s.t1 ? s.words.length : s.words.filter((w) => w[1] <= t).length);
    const key = shown.map((s) => s.id + ":" + nWords(s)).join("|");
    if (key === lastPanelKey) return;
    lastPanelKey = key;

    const box = $("messages");
    box.innerHTML = "";
    for (const s of shown) {
      const el = document.createElement("div");
      el.className = "msg" + (s.kind === "monologue" ? " thought" : "") + (s.speaker === EX.persona ? " focal" : "") +
        (s.placeholder ? " placeholder" : "") + (last && s.beat_id !== last.beat_id ? " old" : "");
      const typing = t < s.t1;
      let text = s.placeholder ? `(${s.beat_id}: monologue not generated yet)` : s.words.slice(0, nWords(s)).map((w) => w[0]).join(" ");
      el.innerHTML = `<div class="who"><img alt=""><span></span></div><div class="body"><div class="name"></div><div class="text"></div></div>`;
      const img = el.querySelector("img");
      img.src = `/assets/characters/profile/${keyOf(s.speaker)}.png`;
      img.onerror = () => { img.style.visibility = "hidden"; };
      el.querySelector(".who span").textContent = initials(s.speaker);
      el.querySelector(".name").textContent = s.speaker;
      const tx = el.querySelector(".text");
      tx.textContent = text;
      if (typing && !s.placeholder) tx.insertAdjacentHTML("beforeend", '<span class="caret"></span>');
      box.appendChild(el);
    }
  }

  function renderDebug(st, seg, t) {
    const beat = activeSpeech(st.seg, t)[0];
    $("debug").textContent =
      `t=${t.toFixed(2)}/${TL.duration.toFixed(1)}s  seg=${seg.name}\n` +
      `step=${st.step.toFixed(2)}  mode=${st.span.mode}  sim=${seg.clock[Math.floor(st.step) - seg.step0] || ""}\n` +
      `speech=${beat ? beat.id : "-"}  timing=${TL.timing_source}`;
  }

  // ---------------------------------------------------------------------------
  // Audio (interactive playback only; video gets audio muxed by ffmpeg)
  // ---------------------------------------------------------------------------

  function syncAudio(t) {
    const st = simAt(t);
    for (const s of speechBySeg[st.seg]) {
      if (!s.audio || audioStarted.has(s.id) || t < s.t0 || t >= s.t1) continue;
      const a = audioEls[s.id] || (audioEls[s.id] = new Audio(`/data/audio/${s.audio.file}`));
      a.currentTime = t - s.t0;
      a.playbackRate = speed;
      a.play().catch(() => {});
      audioStarted.add(s.id);
    }
  }

  function stopAudio() {
    for (const a of Object.values(audioEls)) a.pause();
    audioStarted.clear();
  }

  // ---------------------------------------------------------------------------
  // Phaser scene
  // ---------------------------------------------------------------------------

  let scene;

  function preload() {
    for (const [key, , path] of TILESETS) this.load.image(key, path);
    this.load.tilemapTiledJSON("map", "/assets/the_ville/visuals/the_ville_jan7.json");
    this.load.atlas("_fallback", "/assets/characters/Yuriko_Yamamoto.png", "/assets/characters/atlas.json");
    for (const name of EX.personas) {
      this.load.atlas(keyOf(name), `/assets/characters/${keyOf(name)}.png`, "/assets/characters/atlas.json");
    }
    this.load.on("loaderror", (file) => missingAtlas.add(file.key));
  }

  function create() {
    scene = this;
    const map = this.make.tilemap({ key: "map" });
    const ts = {};
    for (const [key, tiledName] of TILESETS) ts[key] = map.addTilesetImage(tiledName, key);
    const group = TILESETS.filter(([k]) => k !== "blocks_1").map(([k]) => ts[k]);
    for (const name of LAYERS) {
      const tilesets = name === "Wall" ? [ts.CuteRPG_Field_C, ts.walls] : group;
      const layer = map.createLayer(name, tilesets, 0, 0);
      if (name.startsWith("Foreground")) layer.setDepth(2);
    }

    for (const name of EX.personas) {
      const key = missingAtlas.has(keyOf(name)) ? "_fallback" : keyOf(name);
      const spr = this.add.sprite(0, 0, key, "down").setOrigin(0.5, 1);
      spr.displayWidth = 40;
      spr.scaleY = spr.scaleX;
      sprites[name] = spr;
      emojis[name] = this.add.text(0, 0, "", { font: "22px sans-serif" }).setOrigin(0.5, 1).setDepth(3);
    }
    sprites._tag = this.add.text(0, 0, EX.persona.split(" ")[0], {
      font: "bold 14px sans-serif", color: "#ffffff", backgroundColor: "#2f6fde", padding: { x: 5, y: 1 },
    }).setOrigin(0.5, 0).setDepth(3);

    const cam = this.cameras.main;
    cam.setBounds(0, 0, map.widthInPixels, map.heightInPixels);
    cam.setZoom(CAM.zoom);
    camPath = computeCamPath();

    render(tNow);
    window.reel.ready = true;
  }

  function update(_time, delta) {
    if (!playing) return;
    tNow = Math.min(TL.duration, tNow + (delta / 1000) * speed);
    render(tNow);
    syncAudio(tNow);
    updateControls();
    if (tNow >= TL.duration) setPlaying(false);
  }

  // ---------------------------------------------------------------------------
  // Controls and public API
  // ---------------------------------------------------------------------------

  function setPlaying(p) {
    playing = p;
    $("play").textContent = p ? "Pause" : "Play";
    if (!p) stopAudio();
  }

  function seekTo(t) {
    tNow = Math.max(0, Math.min(TL.duration, t));
    stopAudio();
    render(tNow);
    updateControls();
  }

  function updateControls() {
    $("scrub").value = Math.round((tNow / TL.duration) * 1000);
    $("tlabel").textContent = `${tNow.toFixed(1)}s / ${TL.duration.toFixed(1)}s`;
  }

  function wireControls() {
    $("play").onclick = () => setPlaying(!playing);
    $("scrub").oninput = (e) => seekTo((e.target.value / 1000) * TL.duration);
    $("speed").onchange = (e) => { speed = parseFloat(e.target.value); stopAudio(); };
    $("dbg").onchange = (e) => { $("debug").hidden = !e.target.checked; render(tNow); };
    TL.segments.forEach((s) => {
      const b = document.createElement("button");
      b.textContent = s.name;
      b.onclick = () => seekTo(s.t0 + 0.01);
      $("segs").appendChild(b);
    });
    document.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" && e.target.type !== "range") return;
      if (e.code === "Space") { e.preventDefault(); setPlaying(!playing); }
      else if (e.key === "d") $("dbg").click();
      else if (e.key === "ArrowRight") seekTo(tNow + 5);
      else if (e.key === "ArrowLeft") seekTo(tNow - 5);
    });
  }

  const nextFrame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

  window.reel = {
    ready: false,
    get duration() { return TL ? TL.duration : 0; },
    async seek(t) { seekTo(t); await nextFrame(); return simAt(t); },
    info: () => ({ t: tNow, ...simAt(tNow), camPath: camPath && camPath.length }),
    cameraAt: (t) => cameraAt(t),
  };

  async function main() {
    if (CAPTURE) document.body.classList.add("capture");
    const base = params.get("data") || "/data";
    [EX, TL] = await Promise.all([
      fetch(`${base}/extract.json`).then((r) => r.json()),
      fetch(`${base}/timeline.json`).then((r) => r.json()),
    ]);
    CAM = Object.assign({ edge_margin_tiles: 6, zoom: 1, pan_ms: 600 }, TL.camera || {});
    prep();
    if (!CAPTURE) wireControls();
    if (params.has("t")) tNow = parseFloat(params.get("t"));
    new Phaser.Game({
      type: CAPTURE ? Phaser.CANVAS : Phaser.AUTO,
      width: VIEW_W, height: VIEW_H, parent: "map", pixelArt: true, backgroundColor: "#000000",
      scene: { preload, create, update },
    });
  }

  main().catch((err) => {
    console.error("[reel] failed to start", err);
    document.body.insertAdjacentHTML("afterbegin", `<pre style="color:#f88">${err}</pre>`);
  });
})();
