/* 【2026-09-18 診斷】前端在 Tauri 裡掛掉的時候畫面是全白的，
   而 Tauri 的 console 從外面看不到、Rust 的 stderr 也不會收到它。
   於是「白畫面」跟「還在載入」「視窗沒開」長得一模一樣。

   所以把錯誤畫到畫面上。這一段刻意放在檔案最前面，
   而且不依賴任何其他函式 —— 它要能在別的東西都還沒定義的時候動。 */
window.addEventListener("error", (e) => {
  const box = document.createElement("pre");
  box.style.cssText = "position:fixed;inset:0;z-index:99999;margin:0;padding:12px;"
    + "background:#1C1C1E;color:#FFB3AE;font:11px/1.5 ui-monospace,monospace;"
    + "white-space:pre-wrap;overflow:auto";
  box.textContent = "前端掛了\n\n" + (e.message || "") + "\n\n"
    + (e.filename || "") + ":" + (e.lineno || "") + ":" + (e.colno || "")
    + "\n\n" + ((e.error && e.error.stack) || "");
  document.body && document.body.appendChild(box);
});
window.addEventListener("unhandledrejection", (e) => {
  const box = document.createElement("pre");
  box.style.cssText = "position:fixed;inset:0;z-index:99999;margin:0;padding:12px;"
    + "background:#1C1C1E;color:#FFCC80;font:11px/1.5 ui-monospace,monospace;"
    + "white-space:pre-wrap;overflow:auto";
  box.textContent = "有一個 Promise 沒有人接\n\n" + String(e.reason)
    + "\n\n" + ((e.reason && e.reason.stack) || "");
  document.body && document.body.appendChild(box);
});

// Forseti Widget 前端。
//
// 只做呈現。所有判斷來自 tracker.py —— 判斷邏輯只能有一份。
// 規格 `.forseti/WIDGET_SPEC.md`。

const invoke = window.__TAURI__?.core?.invoke;
const $ = (id) => document.getElementById(id);
const esc = (s) => { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; };
const flat = (s) => (s || "").split(/\s+/).filter(Boolean).join(" ");

let rows = [];
let follow = true;
let view = "tree";
/* 最後一次 snapshot。drill-down 展開時不必再打一次後端。 */
let lastSnap = null;
let dismissed = new Set();      // 關掉的卡片，§5.1 留點可以重開
let lastCount = 0;

// 空轉多短才值得標。
//
// tracker 給的是 20 秒以上的每一段,那是資料。
// 20 秒在這裡幾乎每一輪都有 —— 一個每一輪都亮的標記等於不亮。
const GAP_SHOW = 60;

let uiId = "";
let currentSession = "";


// 跳到某一輪並閃一下。捲到了卻不知道是哪一張，等於沒跳。
function jumpTo(n) {
  const el = $("lane").querySelector(`[data-n="${n}"]`);
  if (!el) return false;
  follow = false;
  $("followBtn").setAttribute("aria-pressed", "false");
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  const card = el.querySelector(".body") || el;
  card.classList.remove("flash");
  void card.offsetWidth;          // 重新觸發動畫
  card.classList.add("flash");
  return true;
}

/* Context 預警。§28
   壓縮發生後畫一個黑點是事後，這一條是事前。
   門檻用這個 session 自己壓縮過的實際觸發點，不是拿模型上限去猜 ——
   一個猜出來的百分比會在錯的時候讓人放心。 */
function setContext(d) {
  const c = d.context || {};
  const box = $("ctx");
  if (!c.ok || c.pct === null || c.pct === undefined) {
    box.hidden = true;
    return;
  }
  // 【2026-09-14】平常不顯示這條。
  //
  // bible.md Q-03 引 owner 原話:「真正的溫度不是 Token Usage。
  // Temperature = Cognitive/Runtime degradation，不是 Context fullness。」
  // v5.0 §10 講得更細:單一 token 百分比解釋不了路由汙染、過期證據、
  // 記憶矛盾或快取中毒，所以它被拆成六個維度。
  //
  // 容量仍然是八維度裡的「脈絡」那一格，按「為什麼」看得到。
  // 只有真的快壓縮了才浮上來 —— 那時它不是統計，是預警。
  if (c.pct < 80) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.dataset.level = c.level || "ok";
  $("ctxFill").style.width = c.pct + "%";
  const k = (n) => (n >= 1000 ? Math.round(n / 1000) + "K" : String(n));
  $("ctxText").textContent =
    `記憶用了 ${c.pct}%，離壓縮還有 ${k(c.headroom)} token` +
    (c.compactions ? `。這段對話壓縮過 ${c.compactions} 次` : "");
}


/* ── 線 ────────────────────────────────────── */

const hhmmss = (ts) => {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toTimeString().slice(0, 8);
};
const dur = (s) => (s < 60 ? Math.round(s) + "s"
  : s < 3600 ? Math.round(s / 60) + "m" : (s / 3600).toFixed(1) + "h");

// 一列裡最有資訊的那一段。
//
// 事件清單裡十筆「Bash · cd "/Volumes/NewDrive/AI Projec…」長得一模一樣，
// 因為每一條指令都用同一個 cd 開頭 —— 真正的內容在 && 後面，
// 而那正好是被截掉的部分。截斷點不對，等於整欄沒有資訊。
const shortCmd = (s) =>
  (s || "").replace(/^cd\s+(?:"[^"]*"|'[^']*'|\S+)\s*&&\s*/, "");

// mcp__Claude_Browser__navigate → Browser.navigate
const shortTool = (s) => {
  const m = /^mcp__(.+?)__(.+)$/.exec(s || "");
  if (!m) return s;
  return m[1].replace(/_/g, " ").split(" ").pop() + "." + m[2];
};

// §3.1 線有長度。換算成畫面高度，但要有上下限 ——
// 一條三小時的線不能把畫面撐爆，一條兩秒的線也要看得見。
function laneHeight(sec, dotCount) {
  const byTime = Math.log2(1 + sec / 8) * 9;
  const byDots = dotCount * 5;
  return Math.max(26, Math.min(200, Math.max(byTime, byDots) + 18));
}

// §4.1 紅點密度把綠線漸層染成橘。
//
// 【2026-09-14 owner 問「線條幾乎都是綠色的？」】
// 查了真實資料:180 條線裡 163 綠 14 橘 3 紅,失敗率 3.1%,綠是對的。
// 但橘那 14 條的 tint 落在 0.02 到 0.17,舊公式 amber 比例 = tint/0.5,
// tint=0.05 只染 10% 橘,肉眼跟純綠沒差。一條 129 個點、6 個失敗的線
// 畫出來跟零失敗的線長一樣,顏色這個通道等於沒在傳資訊。
// 改成:有失敗就先跳到 45% 橘(看得出來),再往上補滿。
// 純綠從此只代表一件事,這一輪零失敗。
function strandColor(tint) {
  // owner 2026-09-14：「讀文件沒有全部讀好並且擅自作主，這也是重大事件，
  // 也是標注紅色，一開始就是紅色，後面不可能會出現綠色。」
  // 根基不合格的時候不做漸層,直接紅。工具一次都沒失敗也一樣紅 ——
  // 照著錯的規格做，做得再順也是錯的。
  if (foundationBad) return "var(--red)";
  if (tint <= 0) return "var(--green)";
  if (tint >= 0.5) return "var(--red)";
  const t = 0.45 + (tint / 0.5) * 0.55;
  return `color-mix(in srgb, var(--amber) ${Math.round(t * 100)}%, var(--green))`;
}

// 資料層只分 read / write / other（Bash 算 write，因為它會改東西）。
// 呈現層再細一階:「跑了指令」跟「改了檔案」對讀的人是兩件事。
// 不動資料層的分類 —— 判斷邏輯只能有一份。
const RUN_TOOLS = new Set(["Bash", "BashOutput", "KillShell"]);

// 誰把線拉回中軸的。latency.RECOVERY 那三個值,對到畫面上三個顏色。
// 這裡不給預設值以外的東西:認不得的 recovery 一律當成「還開著」,
// 因為把不認得的狀態畫成「已經收尾」會讓人以為那段結束了。
const LT_KIND = {
  OWNER_CORRECTION: "owner",
  SELF_RECOVERED: "self",
  STILL_OPEN: "open",
};

// 這一輪落在哪一段偏離裡,以及它是不是那一段的收尾。
//
// 抽成純函式不是為了好看,是為了測得到:渲染跑在瀏覽器裡,
// 而「區間怎麼算」是判斷不是畫圖。測試從這個檔抽這一支出來跑,
// 所以不會有第二份會分歧的實作。
function ltMarkFor(n, episodes) {
  for (const ep of episodes || []) {
    if (ep.from_n == null || ep.to_n == null) continue;
    if (n < ep.from_n || n > ep.to_n) continue;
    // end 判斷吃 kind 不吃原始字串。吃原始字串的話,
    // 一個認不得的 recovery 會同時是「還開著」跟「已收尾」,
    // 兩個標記互相矛盾而畫面上只看得到後者。
    const kind = LT_KIND[ep.recovery] || "open";
    return {
      kind,
      // 還開著的那一段不畫收尾端點,因為它還沒收尾。
      // 畫了等於說「這裡結束了」,而那是假的。
      end: n === ep.to_n && kind !== "open",
    };
  }
  return null;
}

function dotClass(d) {
  if (d.label === "對話壓縮") return "d big";
  if (d.failed) return "d fail";
  if (RUN_TOOLS.has(d.label)) return "d run";
  return "d " + (d.kind || "other");
}


// 跨天的 session 只看 hh:mm:ss 會把昨天當今天。
const dayOf = (ts) => (ts ? new Date(ts * 1000).toDateString() : "");
const dayLabel = (ts) => {
  const d = new Date(ts * 1000);
  const today = new Date();
  const same = (a, b) => a.toDateString() === b.toDateString();
  if (same(d, today)) return "今天";
  const y = new Date(today); y.setDate(y.getDate() - 1);
  if (same(d, y)) return "昨天";
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
};

/* 把每一輪的目標距離畫成一條連續的線。§22.7
   在 DOM 排好之後量實際位置，因為每一輪的高度是時間算出來的。 */

/* 面板開合。預設收起,讓樹吃滿。§17.3 只顯示單一最高槓桿的事實。 */
function togglePanel(force) {
  const p = $("panel"), b = $("miniT");
  if (!p || !b) return;
  const open = force == null ? p.hidden : force;
  p.hidden = !open;
  b.setAttribute("aria-expanded", String(open));
}


/* 可靠度曲線。§16.1 八視圖之一:Health Curve。

   **這一格回答的是「從哪一輪開始退化」，不是「現在幾度」。**
   上面那個大數字只講現在，而 owner 要看的是它在變好還是變壞 ——
   一個點沒有方向。

   三件刻意的事:

   一，y 軸下限釘死 36.3，上限至少到 38.0。自適應 y 軸會把
   0.7 度的波動畫成滿版的山谷，那是 FS-RSK-001 禁止的
   「把不確定的東西畫成確定」。真實主線的溫度在 36.9 到 37.6 之間，
   它本來就該看起來是平的。

   二，脈絡與連續性兩維沒有算進這條線，而且這件事寫在畫面上，
   不是只寫在程式碼的註解裡。理由見 vitals.CURVE_EXCLUDED。

   三，算不出來就說算不出來，不畫一條平線假裝正常。 */


/* 退回去的話，退到哪一輪。ROADMAP P0 第 1 項、Vol4 Stage 4 的出口條件。

   **算不出來的時候它講缺什麼，不給輪號。** Python 端的 `rescue.plan()`
   在沒有可回去的點的時候回 can:false 加一句 hint，這裡照實顯示 ——
   猜一個輪號出來會把還好的工作一起丟掉，而且不會有人發現，
   因為 fork 出來的新線看起來很正常。

   憑據只有兩種，畫面上要講出是哪一種：人親手標的，
   或是第一個真的造成後果的區段。兩者的可信度不一樣。 */
function renderRescue(d) {
  const box = $("rescue");
  if (!box) return;
  const r = d.rescue;
  if (!r) { box.hidden = true; return; }
  box.hidden = false;

  const back = $("rBack"), why = $("rWhy"), cost = $("rCost");
  const go = $("rGo"), hist = $("rHist");

  if (!r.can) {
    back.innerHTML = "<b>現在退不回去</b>";
    why.textContent = "";
    cost.textContent = r.hint || r.why || "";
    go.hidden = true;
  } else {
    back.innerHTML = `退回去的話：<b>第 ${r.back_to} 輪</b>`;
    why.textContent = r.source === "OWNER_MARKED_CHECKPOINT"
      ? "你自己標的" : "第一個造成後果的地方";
    const q = r.quarantined || [];
    cost.textContent = q.length
      ? `會排除第 ${q[0]} 到 ${q[1]} 輪，共 ${r.turns_excluded} 輪。原本的一個字都不動`
      : "";
    go.hidden = false;
    go.dataset.n = String(r.back_to);
  }

  const h = d.rescue_history || {};
  hist.textContent = h.total
    ? `這條線救過 ${h.total} 次，走完的 ${h.complete || 0} 次`
    : "";
}

/* 一條軌道 = 一個沒被解決的問題。顏色給語意不給隨機。
   工具失敗是誠實的失敗，跟「說了沒做」不是同一件事（§4.1），
   所以它們不能共用一個顏色。 */
const LANE_CLS = {
  COMPACT: "lc", BETRAYAL: "lb", DRIFT: "ld",
  TOOL_FAIL: "lf", BLIND_WRITE: "lw",
};

/* 同時開著的軌道要各佔一條 x。貪心配置:找第一條已經空出來的，
   沒有就開新的。軌道編號一旦給出去就不再變，眼睛才追得住。 */
function packLanes(items) {
  const ends = [];
  return items.map((it) => {
    let i = ends.findIndex((e) => e < it.from_n);
    if (i < 0) { i = ends.length; ends.push(it.to_n); }
    else ends[i] = it.to_n;
    return Object.assign({}, it, {lane: i});
  });
}

function drawDrift() {
  const lane = $("lane");
  if (!lane) return;
  lane.querySelector(".drift")?.remove();
  const guts = [...lane.querySelectorAll(".st .gut")];
  if (guts.length < 2) return;

  const NS = "http://www.w3.org/2000/svg";
  const MAIN = 10;
  const GAP = 8;
  const laneTop = lane.getBoundingClientRect().top;

  const pts = guts.map((g) => {
    const r = g.getBoundingClientRect();
    const st = g.closest(".st");
    return {
      n: Number(st?.dataset.n ?? -1),
      d: Number(st?.dataset.dist || 0),
      k: st?.dataset.klass || "UNKNOWN",
      acts: Number(st?.dataset.acts || 0),
      y0: r.top - laneTop,
      y1: r.bottom - laneTop,
    };
  });
  const yOf = new Map(pts.map((p) => [p.n, p]));
  const lo = pts[0].n, hi = pts[pts.length - 1].n;

  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "drift");
  svg.setAttribute("height", String(lane.scrollHeight));
  const add = (el, cls) => { el.setAttribute("class", cls); svg.appendChild(el); return el; };

  /* 問題軌道。裁到可見範圍再配置，不然畫面外的長軌道會把
     所有短的擠到很右邊。 */
  const raw = (((lastSnap || {}).lanes || {}).lanes || [])
    .filter((x) => x.to_n >= lo && x.from_n <= hi)
    .map((x) => Object.assign({}, x, {
      from_n: Math.max(x.from_n, lo), to_n: Math.min(x.to_n, hi),
    }))
    .sort((p, q) => p.from_n - q.from_n);
  const packed = packLanes(raw);

  packed.forEach((it) => {
    const A = yOf.get(it.from_n), B = yOf.get(it.to_n);
    if (!A || !B) return;
    const x = MAIN + GAP * (it.lane + 1);
    const cls = "lane " + (LANE_CLS[it.kind] || "ld") + (it.open ? " open" : "");
    const bend = 14;

    const out = document.createElementNS(NS, "path");
    out.setAttribute("d",
      `M ${MAIN} ${A.y0} C ${MAIN} ${A.y0 + bend * .6}, ` +
      `${x} ${A.y0 + bend * .4}, ${x} ${A.y0 + bend}`);
    add(out, cls);

    if (B.y1 > A.y0 + bend) {
      const run = document.createElementNS(NS, "path");
      run.setAttribute("d", `M ${x} ${A.y0 + bend} L ${x} ${B.y1 - (it.open ? 0 : bend)}`);
      add(run, cls);
    }
    // 收回來的才畫回收曲線。一路開著的就讓它走到底 ——
    // 沒解決的問題不會自己回到主線。
    if (!it.open && B.y1 - bend > A.y0 + bend) {
      const back = document.createElementNS(NS, "path");
      back.setAttribute("d",
        `M ${x} ${B.y1 - bend} C ${x} ${B.y1 - bend * .4}, ` +
        `${MAIN} ${B.y1 - bend * .6}, ${MAIN} ${B.y1}`);
      add(back, cls);
    }
  });

  /* 主線。一輪一段，顏色跟著那一輪走。 */
  const colorOf = (k, d) => {
    if (k === "CONFLICTING") return "var(--red)";
    if (d >= 0.34) return "var(--amber)";
    if (d > 0.08) return `color-mix(in srgb, var(--amber) ${
      Math.round(d * 180)}%, var(--green))`;
    return "var(--green)";
  };
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i], prev = i ? pts[i - 1] : null;
    const seg = document.createElementNS(NS, "path");
    seg.setAttribute("d", prev
      ? `M ${MAIN} ${prev.y1} L ${MAIN} ${p.y1}`
      : `M ${MAIN} ${p.y0} L ${MAIN} ${p.y1}`);
    seg.setAttribute("stroke", colorOf(p.k, p.d));
    add(seg, "main");
  }

  /* 節點。半徑吃那一輪的動作數 —— 每個點一樣大的話，
     再多點也只是一條虛線。 */
  pts.forEach((p) => {
    const r = Math.max(2.2, Math.min(6.5, 2.2 + Math.sqrt(p.acts) * 0.85));
    const cy = (p.y0 + p.y1) / 2;
    const halo = document.createElementNS(NS, "circle");
    halo.setAttribute("cx", String(MAIN)); halo.setAttribute("cy", String(cy));
    halo.setAttribute("r", String(r + 3.2));
    halo.setAttribute("fill", colorOf(p.k, p.d));
    add(halo, "halo");
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("cx", String(MAIN)); c.setAttribute("cy", String(cy));
    c.setAttribute("r", String(r));
    c.setAttribute("fill", colorOf(p.k, p.d));
    add(c, "node");
  });

  lane.appendChild(svg);
}

function renderTree() {
  const lane = $("lane");
  lane.textContent = "";
  let lastDay = "";
  rows.forEach((s) => {
    const day = dayOf(s.started_at);
    if (day && day !== lastDay) {
      lastDay = day;
      const dm = document.createElement("div");
      dm.className = "daymark";
      dm.innerHTML = `<span>${esc(dayLabel(s.started_at))}</span>`;
      lane.appendChild(dm);
    }
    const wrap = document.createElement("div");
    wrap.className = "st" + (s.growing ? " grow" : "");
    wrap.dataset.growing = s.growing ? "1" : "0";
    wrap.dataset.n = s.n;
    // 線的水平位置從這裡來。§22.7
    // 跟 Forseti 建議的分岔。owner 2026-09-15:
    // 「每個決定都會跟 forseti 的建議做分岔」。
    // 橫向吃這個，顏色吃目標距離 —— 兩個軸分開，不合成成一個數字。
    wrap.dataset.n = String(s.n ?? -1);
    // 有注記的那一輪要在圖上看得見,不然寫了等於沒寫。
    if ((s.notes || []).length) wrap.dataset.notes = String(s.notes.length);
    if (s.checkpoint) {
      wrap.dataset.cp = s.checkpoint.last_good ? "good" : "mark";
    }
    // 第一個分歧點。§6.3 三種,不是一種。
    // fork 的基準是「造成後果」那一個,不是最早的警訊 ——
    // 最早的警訊常常是誤報,回太早會把好的工作一起丟掉。
    const dvg = (lastSnap || {}).divergence;
    if (dvg && dvg.has) {
      const inRange = (r) => r && s.n >= r[0] && s.n <= r[1];
      if (inRange(dvg.first_consequential)) wrap.dataset.dv = "cons";
      else if (inRange(dvg.earliest_confirmed)) wrap.dataset.dv = "conf";
      else if (inRange(dvg.earliest_suspicious)) wrap.dataset.dv = "susp";
    }
    // 修正延遲。白皮書 §5.4 / 工程規格書 §13.3
    //
    // 它回答的是這個專案最核心的那個問題:她被消耗了多少。
    // 先前只活在一份清單裡,而清單要人自己把「第幾段偏離」對回
    // 「那是什麼時候的事」,§5.1 說的就是這個對照動作,
    // 壓在線上就沒有它。
    //
    // 區間內每一輪各標一段,連起來的長度就是那一段橫跨的輪數。
    const lt = (lastSnap || {}).latency;
    if (lt && lt.has) {
      const mark = ltMarkFor(s.n, lt.episodes);
      if (mark) {
        wrap.dataset.lt = mark.kind;
        if (mark.end) wrap.dataset.ltEnd = "1";
      }
    }
    wrap.dataset.acts = String((s.dots || []).length);
    wrap.dataset.dist = String((s.goal && s.goal.distance) || 0);
    wrap.dataset.klass = (s.goal && s.goal.klass) || "UNKNOWN";
    if (s.corrected_by_owner) wrap.dataset.corrected = "1";

    // 紫點的框。§5.4 三條件同時成立才跳，而且壓在線上不是躺在側邊，
    // 因為「你看到的位置就是它發生的位置」(§5.1)。
    if (s.drift_alert) wrap.dataset.drift = "1";

    const h = laneHeight(s.duration, s.dots.length);
    const col = strandColor(s.tint);

    const gut = document.createElement("div");
    gut.className = "gut";
    gut.style.minHeight = h + "px";
    const bigCap = s.compaction ? " big" : "";
    gut.innerHTML =
      `<span class="v" style="background:linear-gradient(var(--green),${col})"></span>` +
      `<span class="cap s${bigCap}" style="background:${s.compaction ? "" : col}"></span>` +
      (s.growing ? "" :
        `<span class="cap e" style="background:${col}"></span>`);

    const body = document.createElement("button");
    body.className = "body";
    body.title = "點一下看這一輪能做什麼";
    body.addEventListener("click", () => openNode(s));
    body.innerHTML = `<div class="txt">${esc(flat(s.owner_text).slice(0, 110) || "(無)")}</div>`;

    const bts = s.betrayals || [];
    // 白點常常正好落在「那一輪一個工具都沒叫」的線上,
    // 所以這個條件不能只看 dots,不然最該亮的那幾條反而不亮。
    const bigGap = s.gaps.some((g) => g[1] - g[0] >= GAP_SHOW);
    if (s.dots.length || bigGap || bts.length) {
      // 人話摘要。
      //
      // owner 2026-09-14：一排 115 個小圓點是 geek 的東西。
      // 「讀了 12 個檔案，跑了 8 個指令」是人看得懂的。
      // 點陣留著（紅點的密度是規格 §4.1 的核心），但退成次要。
      const sum = { read: 0, run: 0, write: 0, fail: 0 };
      s.dots.forEach((d) => {
        if (d.label === "對話壓縮") return;
        const k = d.count || 1;
        if (d.failed) sum.fail += k;
        else if (RUN_TOOLS.has(d.label)) sum.run += k;
        else if (d.kind === "write") sum.write += k;
        else sum.read += k;
      });
      if (sum.read || sum.run || sum.write || sum.fail) {
        const sm = document.createElement("div");
        sm.className = "sum";
        const bit = (label, n, cls) => n
          ? `<span class="${cls || ""}">${label} <b>${n}</b></span>` : "";
        sm.innerHTML =
          bit("讀了", sum.read) + bit("跑了", sum.run) +
          bit("改了", sum.write) + bit("失敗", sum.fail, "bad");
        body.appendChild(sm);
      }

      // 點陣只在那一輪有異常時展開。
      //
      // owner 2026-09-14：「每個節點下面都有一塊東西，然後裡面一堆小點。」
      // 正常的一輪，那排點全是同一個灰，摘要已經把它講完了。
      // 只有失敗或壓縮的時候，密度才有意義（§4.1 紅點密度染色整條線）。
      const worthShowing = sum.fail > 0 || s.compaction ||
        s.dots.some((d) => d.label === "對話壓縮");
      const dd = document.createElement("div");
      dd.className = "dots";
      if (!worthShowing) dd.hidden = true;
      s.dots.forEach((d) => {
        const el = document.createElement("span");
        el.className = dotClass(d);
        const lbl = shortTool(d.label);
      el.dataset.tip = (d.count > 1 ? `${lbl} x${d.count}` : lbl) +
          (d.detail ? " · " + shortCmd(d.detail) : "");
        dd.appendChild(el);
        if (d.count > 1) {
          const n = document.createElement("span");
          n.className = "dn";
          n.textContent = "x" + d.count;
          dd.appendChild(n);
        }
      });
      bts.forEach((b) => {
        const el = document.createElement("span");
        el.className = "d white";
        el.dataset.tip = b.why;
        dd.appendChild(el);
      });
      // §3.5 空轉看得出來
      if (s.premature) {
        const pm = document.createElement("div");
        pm.className = "starve premature";
        pm.textContent = "停在這裡等你開口";
        pm.title = `帳本上還有：${(s.premature.outstanding || []).join("；")}`;
        body.appendChild(pm);
      }
      if (s.starving) {
        const sv = document.createElement("div");
        sv.className = "starve" +
          (s.starving.basis === "INFERRED" ? " inferred" : "");
        sv.textContent = {
          BLANK_OUTPUT_SEQUENCE: "連續沒有輸出",
          OUTPUT_STARVATION: "做完了但沒說出來",
          PROCESS_STALL: "沒動作也沒輸出",
          STALE_WATCHER: "可能是觀測落後",
        }[s.starving.klass] || s.starving.klass;
        sv.title = s.starving.detail;
        body.appendChild(sv);
      }
      const worst = s.gaps.length
        ? Math.max(...s.gaps.map((x) => x[1] - x[0])) : 0;
      if (worst >= GAP_SHOW) {
        const g = document.createElement("span");
        g.className = "gapmark";
        g.textContent = `${dur(worst)} 沒動作`;
        g.title = `${s.gaps.length} 段沒有任何動作，最長 ${dur(worst)}`;
        dd.appendChild(g);
      }
      body.appendChild(dd);
    }

    /* 宣稱拿去對現實查過的結果。desktop_api.verified_claims()，
       底下是 claims.py —— 整套裡唯一真的去 stat 磁碟的一支，
       不是文字比對。

       **標籤講「沒被證實」，不講「說謊」。** claims.can_refute() 的規則
       是驗證器沒資格判假就不判假，所以這裡絕大多數會停在 UNKNOWN，
       意思是搆不到那個檔案，不是它騙人。把 UNKNOWN 寫成「說謊」
       等於用這個面板再犯一次它自己在抓的那個錯（§32 講太滿）。

       強度是 v5.0 §7.2 的 E0-E4，值由 claims.verify() 決定，
       前端不算也不推。 */
    const claimHits = s.claims || [];
    if (claimHits.length) {
      const allUnknown = claimHits.every((c) => c.state === "UNKNOWN");
      const cb = document.createElement("div");
      cb.className = "claimchk" + (allUnknown ? " unknown" : "");
      cb.textContent = allUnknown
        ? `${claimHits.length} 個宣稱查不到`
        : `${claimHits.length} 個宣稱沒被證實`;
      cb.title = allUnknown
        ? "驗證器搆不到這些東西，所以不判它真也不判它假。點開看是哪些"
        : "這些宣稱對著現實查過，沒有通過。點開看是哪些";
      const ul = document.createElement("ul");
      ul.className = "claimlist";
      claimHits.slice(0, 8).forEach((c) => {
        const li = document.createElement("li");
        li.title = c.why || "";
        li.innerHTML =
          `<span class="cst">${esc(c.state || "")}</span>` +
          `<span class="csub">${esc(c.subject || "")}</span>` +
          `<span class="cev" title="v5.0 §7.2 證據強度，E0 最弱 E4 最強"` +
          `>${esc(c.strength || "?")}</span>`;
        ul.appendChild(li);
      });
      cb.addEventListener("click", (e) => {
        // body 自己是個 button，不擋的話點開清單會順便跳進那一輪。
        e.stopPropagation();
        ul.classList.toggle("open");
      });
      body.appendChild(cb);
      body.appendChild(ul);
    }

    const time = document.createElement("div");
    time.className = "time";
    time.innerHTML = hhmmss(s.started_at) +
      `<span class="dur">${s.growing ? "長中" : dur(s.duration)}</span>`;

    wrap.append(gut, body, time);
    // 用真實元素不用偽元素:`.st::after` 被粉紅點的角標佔著、
    // `::before` 被 checkpoint 佔著、左緣的 inset 陰影被分歧點佔著。
    // 同一輪可能同時是這幾種,共用任何一個都會讓後寫的蓋掉前面的。
    // 這是 TC-LT-03 釘住的那件事。
    if (wrap.dataset.lt) {
      const ltm = document.createElement("i");
      ltm.className = "ltm";
      wrap.append(ltm);
    }
    lane.appendChild(wrap);

    // §5.1 白點卡片。黑底白字白光。
    //
    // 文字寫成「下一句該講什麼」，不是描述問題 ——
    // 一個看得懂卻不知道要做什麼的提醒，跟沒有提醒差不多。
    bts.forEach((b, i) => {
      const key = "b" + s.n + "-" + i;
      if (dismissed.has(key)) return;
      const c = document.createElement("div");
      c.className = "card warn";
      c.style.setProperty("--linkcol", col);   // 線穿過卡片時顏色要接得上
      // 層級:結論 → 標的 → 證據 → 下一句該講什麼。
      // 每一層講一件不重複的事。
      c.innerHTML =
        `<button class="x" aria-label="關閉">×</button>` +
        `<b>${esc(b.title || b.fp_name)}</b>` +
        (b.target ? `<div class="tg">${esc(b.target)}</div>` : "") +
        `<div class="ev">${esc(b.why)}</div>` +
        `<div class="adv">${esc(b.advice)}` +
        `<span class="fp">${esc(b.fp)}</span></div>`;
      c.querySelector(".x").addEventListener("click", () => {
        dismissed.add(key); renderTree();
      });
      lane.appendChild(c);
    });

    // §6 壓縮的黑點卡片。它是錨，不只是警告。
    if (s.compaction && !dismissed.has("c" + s.n)) {
      const m = s.compaction_meta || {};
      const c = document.createElement("div");
      c.className = "card black-note";
      const kept = (m.pre_tokens && m.post_tokens)
        ? `<span class="num">${m.pre_tokens.toLocaleString()}</span> → ` +
          `<span class="num">${m.post_tokens.toLocaleString()}</span> token，留下 ` +
          `<span class="num">${(m.post_tokens / m.pre_tokens * 100).toFixed(1)}%</span>`
        : "";
      c.innerHTML =
        `<button class="x" aria-label="關閉">×</button>` +
        `<b>對話壓縮</b>` +
        (kept ? kept + "<br>" : "") +
        `AI 的記憶從這裡開始不完整。` +
        `<div class="adv">錨在全量紀錄第 <span class="num">${m.line || "?"}</span> 行。` +
        `之後有問題，回頭看這一行之前。</div>`;
      c.querySelector(".x").addEventListener("click", () => {
        dismissed.add("c" + s.n); renderTree();
      });
      lane.appendChild(c);
    }
  });
  // 紫框。插在那一輪的卡片上方。
  lane.querySelectorAll('.st[data-drift="1"]').forEach((st) => {
    const s = rows.find((x) => String(x.n) === st.dataset.n);
    const a = s && s.drift_alert;
    if (!a || st.querySelector(".driftBox")) return;
    const body = st.querySelector(".body");
    if (!body) return;
    const box = document.createElement("div");
    box.className = "driftBox";
    box.innerHTML =
      `<div class="dT">它可能正在偏離你的目標</div>` +
      `<p class="dW">從第 ${a.from_n} 輪到第 ${a.n} 輪，連續 ${a.turns} 輪` +
      `你沒有出手，而它跟目標的距離從 ${a.from_distance} 升到 ${a.distance}。</p>` +
      `<p class="dW dim">${esc(a.state)}　信心 ${a.confidence}　` +
      `已排除：${esc((a.excluded || []).join("、"))}</p>` +
      `<div class="dRow">` +
      `<button class="dGo" type="button">複製這段給他</button>` +
      `<button class="dNo" type="button">不用</button></div>`;
    box.querySelector(".dGo").addEventListener("click", async (e) => {
      e.stopPropagation();
      try {
        await navigator.clipboard.writeText(a.prompt || "");
        e.target.textContent = "複製好了，貼給他";
      } catch { e.target.textContent = "複製不了，請手動選取"; }
    });
    box.querySelector(".dNo").addEventListener("click", (e) => {
      e.stopPropagation();
      box.remove();
      st.dataset.drift = "0";   // 關掉之後這一輪不再跳
    });
    // 插在整個 .st 前面，不要插進它的 grid。
    //
    // 【2026-09-15 實測】第一版插在 .body 前面，於是紫框變成
    // grid 的第二個 item，把時間戳那一欄擠到下一列，
    // 畫面上出現一張只有兩個字寬的卡片。
    // .st 是三欄 grid(線道 | 內容 | 時間)，多一個 item 就整列錯位。
    st.parentNode.insertBefore(box, st);
  });

  drawDrift();
}

/* ── 一輪的動作面板 §27 ───────────────────────
   owner:「點了某個節點，就要跳回到那個桌面 APP 相應對話位置啊，
   這樣才能 Fork 啊。」 */

let nodeN = 0;
const nodeSheet = $("nodeSheet");

function openNode(s) {
  nodeN = s.n;
  $("nodeTitle").textContent = `第 ${s.n} 輪`;
  $("nodeSaid").textContent = flat(s.owner_text).slice(0, 160) || "(沒有文字)";
  $("forkOut").hidden = true;
  $("forkOut").textContent = "";
  $("actFork").disabled = false;
  $("actFork").classList.remove("go");
  $("actFork").querySelector("b").textContent = "從這一輪開一個新的";
  $("forkHint").textContent = "算算看會留下什麼";
  $("actOpen").disabled = !uiId;
  renderNotes(s);
  nodeSheet.hidden = false;
  dryRun();
}

/* 粉紅點。§5.5
   只增不改:寫下去的當下就是證據，事後改掉就不是了。
   所以這裡只有「寫下來」，沒有編輯也沒有刪除。 */
async function markGood() {
  const b = $("actMark"), hint = $("markHint");
  b.disabled = true;
  hint.textContent = "存中…";
  try {
    const r = JSON.parse(await invoke("act", {
      kind: "checkpoint", target: "-", worker: "",
    }));
    hint.textContent = r.ok ? (r.say || "標好了") : (r.why || "存不起來");
  } catch (e) { hint.textContent = String(e); }
  b.disabled = false;
}

function renderNotes(s) {
  const list = $("noteList"), cnt = $("noteCount"), out = $("noteOut");
  if (!list) return;
  const ns = s.notes || [];
  cnt.textContent = ns.length ? `　${ns.length} 則` : "";
  list.innerHTML = ns.map((x) =>
    `<li>${esc(x.text)}<span>${x.at ? esc(hhmmss(x.at)) : ""}</span></li>`).join("");
  $("noteText").value = "";
  out.textContent = "";
  out.className = "noteOut";
}

async function saveNote() {
  const ta = $("noteText"), out = $("noteOut"), btn = $("noteSave");
  const text = (ta.value || "").trim();
  if (!text) { out.textContent = "空的不寫"; out.className = "noteOut bad"; return; }
  btn.disabled = true;
  try {
    const r = JSON.parse(await invoke("note_add", {
      session: currentSession, n: nodeN, text,
    }));
    if (r.ok) {
      out.textContent = "寫下了";
      out.className = "noteOut good";
      ta.value = "";
      const li = document.createElement("li");
      li.innerHTML = `${esc(text)}<span>剛剛</span>`;
      $("noteList").appendChild(li);
      $("noteCount").textContent = `　${$("noteList").children.length} 則`;
    } else {
      out.textContent = r.why || "寫不進去";
      out.className = "noteOut bad";
    }
  } catch (e) {
    out.textContent = String(e);
    out.className = "noteOut bad";
  }
  btn.disabled = false;
}
function closeNode() { nodeSheet.hidden = true; }

// 先乾跑。**預設絕不寫檔** ——
// 一個手滑就產生檔案的按鈕，遲早會在沒人打算 fork 的時候產生檔案。
async function dryRun() {
  try {
    const raw = await invoke("fork",
      { session: currentSession, n: nodeN, go: false });
    const d = JSON.parse(raw);
    if (d.error) { $("forkHint").textContent = d.error; return; }
    $("forkHint").textContent =
      `會留下 ${d.kept} 筆對話，丟掉這一輪之後的 ${d.dropped} 筆。原本的一個字都不動`;
    $("actFork").classList.add("go");
  } catch (e) {
    $("forkHint").textContent = String(e).slice(0, 60);
  }
}

async function doFork() {
  $("actFork").disabled = true;
  $("forkHint").textContent = "切出來中";
  try {
    const raw = await invoke("fork",
      { session: currentSession, n: nodeN, go: true });
    const d = JSON.parse(raw);
    if (d.error) throw new Error(d.error);
    const out = $("forkOut");
    out.hidden = false;
    // 【實測到的限制】桌面版的側邊欄清單在記憶體裡，不會即時重掃目錄，
    // 所以這裡不騙人說「已經開好了」。給兩條真的走得通的路。
    out.innerHTML =
      `<b>切出來了，留下 ${d.kept} 筆</b>` +
      "重新啟動 Claude 之後，它會出現在側邊欄，名字是這個 session 加上「從第 " +
      `${d.n} 輪」。要現在就接下去的話，在終端跑這一行：` +
      `<code>${esc(d.resume || "")}</code>`;
    $("actFork").querySelector("b").textContent = "已經切出來了";
    $("forkHint").textContent = "原本的對話沒有被動到";
  } catch (e) {
    $("forkOut").hidden = false;
    $("forkOut").textContent = "切不出來：" + String(e).slice(0, 120);
    $("actFork").disabled = false;
  }
}

// 「看那一輪」。跳過去而不是直接 fork ——
// fork 是不可逆的，讓她先看到那一輪講了什麼再決定。
//
// **用 jumpTo 不用 jump。** 兩支都會 scrollIntoView，差別是 jumpTo
// 會把「跟著最新」關掉。跟隨還開著的話，下一輪 render 立刻把畫面
// 拉回最底，捲過去的那一下等於沒發生 —— 實測捲到 15886 之後
// 目標節點還在視窗上方 14273px。
$("rGo")?.addEventListener("click", () => {
  const n = Number($("rGo").dataset.n || 0);
  if (!n) return;
  view = "tree";
  syncView();
  if (!jumpTo(n)) $("stat").textContent = `畫面上找不到第 ${n} 輪`;
});

$("actFork").addEventListener("click", doFork);
$("actOpen").addEventListener("click", () => { openInApp(); closeNode(); });
$("nodeClose").addEventListener("click", closeNode);
$("noteSave")?.addEventListener("click", saveNote);
$("actMark")?.addEventListener("click", markGood);
nodeSheet.addEventListener("click", (e) => {
  if (e.target === nodeSheet) closeNode();
});

/* 跳回桌面版。
   owner:「不然都是單向的還要自己慢慢往前面翻。」

   deep link 只到 session 這一層 —— 跳到某一輪的入口還沒找到，
   所以不假裝有:切過去之後還是要自己找那一輪。 */
async function openInApp() {
  if (!uiId) {
    $("stat").textContent = "找不到桌面版的 session id";
    return;
  }
  try {
    await invoke("open_session", { uiId });
  } catch (e) {
    $("stat").textContent = String(e).slice(0, 40);
  }
}

/* ── List：§12 事件是事故類型，不是時間區段 ──── */

function renderList() {
  const lane = $("lane");
  lane.textContent = "";

  /* 三層結構。WIDGET_SPEC §12.2、§12.3。
     第一層按嚴重度不按病症，理由是 §12.3：
     分類幫你整理了，但沒幫你決定。在開發中間打開這個東西，
     要的是一眼知道現在該停下來還是可以繼續。

     家族定義出自 spec-v2.0 §21.1，欄位從 src/primitives.js 的
     registry 讀，不在前端另寫一份。 */
  const FAM = [
    {k: "C", name: "編造", weight: 3,
     why: "宣稱的東西在帳本裡根本不存在。這一格有東西，後面所有判斷都不能信"},
    {k: "B", name: "沒做卻說做了", weight: 2,
     why: "沒毀掉信任基礎，但你交代的事沒在動"},
    {k: "A", name: "講太滿", weight: 1,
     why: "證據範圍不夠、驗證方法不對、抽樣推整體。不是騙"},
  ];

  // 收集帶得出 FP 編號的發現。只有這些進得了三層 ——
  // 工具失敗與空轉不是 FP，它們是執行層的事，另外一區。
  const found = [];
  rows.forEach((s) => {
    (s.betrayals || []).forEach((b) => found.push({s, x: b}));
    (s.overclaims || []).forEach((o) => found.push({s, x: o}));
  });

  const head = document.createElement("div");
  head.className = "famHead";
  head.innerHTML = found.length
    ? `<span>照嚴重度分三格。點開看是哪一條，編號對得回規格 §21</span>`
    : `<span>目前沒有查到帶編號的發現。查不到不等於沒有</span>`;
  lane.appendChild(head);

  FAM.forEach((f) => {
    const mine = found.filter((it) => (it.x.family || "") === f.k);
    const box = document.createElement("div");
    box.className = "fam sev sev" + f.k;
    box.innerHTML =
      `<h3><i class="sevDot"></i>${esc(f.name)}<em>${mine.length}</em></h3>` +
      `<p class="sevWhy">${esc(f.why)}</p>`;
    if (!mine.length) {
      box.insertAdjacentHTML("beforeend",
        '<div class="none">沒有查到</div>');
      lane.appendChild(box);
      return;
    }
    // 第二層：用 registry 自己的 axis 分組。
    //
    // §12.2 寫的第二層是「五個病症分類」，但規格沒有給
    // FP 對病症的對應表。自己編一個等於發明分類，
    // 所以這裡用 registry 本來就有的 axis，並在畫面上講明。
    const byAxis = {};
    mine.forEach((it) => {
      const a = it.x.axis || "未分類";
      (byAxis[a] = byAxis[a] || []).push(it);
    });
    Object.keys(byAxis).sort().forEach((axis) => {
      const sub = document.createElement("div");
      sub.className = "axis";
      sub.innerHTML = `<div class="axisT">${esc(axis)}` +
        `<em>${byAxis[axis].length}</em></div>`;
      const ul = document.createElement("ul");
      byAxis[axis].slice(-20).reverse().forEach((it) => {
        const li = document.createElement("li");
        li.innerHTML =
          `<span class="fp">${esc(it.x.fp || "")}</span>` +
          `<span class="fpT">${esc(it.x.title || it.x.name || "")}</span>` +
          `<span class="ct">#${it.s.n}</span>`;
        li.title = it.x.why || "";
        li.addEventListener("click", () => {
          view = "tree"; syncView(); jump(it.s.n);
        });
        ul.appendChild(li);
      });
      sub.appendChild(ul);
      box.appendChild(sub);
    });
    lane.appendChild(box);
  });

  /* 執行層的事另外一區。它們不是 FP，混進三層會讓嚴重度失真 ——
     一次 Bash 回非零是誠實的失敗，跟「說了沒做」不是同一件事。 */
  const fails = [], stalls = [], compacts = [];
  rows.forEach((s) => {
    s.dots.forEach((d) => {
      if (d.failed) fails.push({s, d});
      if (d.label === "對話壓縮") compacts.push({s, d});
    });
    s.gaps.forEach((g) => {
      if (g[1] - g[0] >= GAP_SHOW) stalls.push({s, sec: g[1] - g[0]});
    });
  });

  const plain = (title, items, render, note) => {
    const box = document.createElement("div");
    box.className = "fam";
    box.innerHTML = `<h3>${esc(title)}<em>${items.length}</em></h3>` +
      (note ? `<p class="sevWhy">${esc(note)}</p>` : "");
    if (!items.length) {
      box.insertAdjacentHTML("beforeend", '<div class="none">沒有</div>');
    } else {
      const ul = document.createElement("ul");
      items.slice(-30).reverse().forEach((it) => {
        const li = document.createElement("li");
        li.innerHTML = render(it);
        li.addEventListener("click", () => {
          view = "tree"; syncView(); jump(it.s.n);
        });
        ul.appendChild(li);
      });
      box.appendChild(ul);
    }
    lane.appendChild(box);
  };

  plain("工具失敗", fails,
        (it) => `<span>${esc(it.d.label || "")}</span>` +
                `<span class="ct">#${it.s.n}</span>`,
        "執行層的事，不是 FP。一次非零退出是誠實的失敗");
  plain("長時間沒動作", stalls,
        (it) => `<span>${dur(it.sec)}</span>` +
                `<span class="ct">#${it.s.n}</span>`,
        "實線是有動作的時間，淡的是什麼都沒發生的時間");
  plain("對話壓縮", compacts,
        (it) => `<span>這裡之後它記不得前面</span>` +
                `<span class="ct">#${it.s.n}</span>`,
        "不是問題，是一條分界線");
}


/* 根基。必讀文件沒讀完 = 這一整條線從第一格就是紅的。§40 */
let foundationBad = false;


let specCache = null;

async function loadFoundation() {
  try {
    const d = JSON.parse(await invoke("spec_reading", {}));
    foundationBad = d && d.has === true && d.ok === false;
    specCache = d;
  } catch (e) { /* 讀不到就不亂標紅，維持原狀 */ }
}


function jump(n) {
  const el = $("lane").querySelector(`[data-n="${n}"]`);
  if (el) el.scrollIntoView({ block: "center" });
}

/* ── 漢堡浮層 §3.4 ───────────────────────────── */

const pop = $("pop");
document.addEventListener("mouseover", (e) => {
  const d = e.target.closest(".d");
  if (!d || !d.dataset.tip) { pop.hidden = true; return; }
  const host = d.closest(".dots");
  const sibs = [...host.querySelectorAll(".d")].filter((x) => x.dataset.tip);
  // 同一時間點擠了很多工具 → 一列一列像漢堡疊起來
  const list = sibs.length > 1 ? sibs : [d];
  pop.innerHTML = list.slice(0, 14).map((x) =>
    `<div class="r"><i style="background:${getComputedStyle(x).backgroundColor}"></i>` +
    `<span>${esc(x.dataset.tip)}</span></div>`).join("");
  pop.hidden = false;
  const r = d.getBoundingClientRect();
  pop.style.left = Math.max(6, Math.min(window.innerWidth - 290, r.left - 8)) + "px";
  pop.style.top = (r.bottom + 6) + "px";
});
document.addEventListener("mouseout", (e) => {
  if (!e.relatedTarget || !e.relatedTarget.closest(".pop, .d")) pop.hidden = true;
});


/* ── 圖例 §23 ──────────────────────────────────
   owner 2026-09-14：「你要加上 ? 這個功能，讓人知道節點是什麼意思，
   不同顏色節點是啥，然後每一個對話匡下面有一堆一排小圓點是啥，
   說實話我看不懂。」

   看不懂的介面等於沒有介面。

   每一個樣本用的是畫面上真正在用的那個 class，不是另外畫一張示意圖 ——
   示意圖會跟實作分岔，而分岔的那天沒有人會發現。 */

const LEGEND = [
  ["這條線", [
    ['<span class="swatch"><i class="lgLine" style="background:linear-gradient(var(--green),var(--green))"></i></span>',
     "一個來回", "你發一次話，到它回完為止。線的長度就是那一輪花了多久，它還在跑的時候會一直長"],
    ['<span class="swatch"><i class="lgLine" style="background:linear-gradient(var(--green),var(--amber))"></i></span>',
     "線變橘", "那一輪工具失敗的比例越高，線越往橘走。綠到橘是連續的，不是分級"],
    ['<span class="swatch"><i class="d" style="background:var(--green);width:8px;height:8px"></i></span>',
     "線頭線尾的圓點", "那一輪的起點跟終點。還在跑的那一輪沒有終點"],
    ['<span class="swatch"><i class="d big"></i></span>',
     "白色的環", "對話在這裡被壓縮過。AI 的記憶從這裡開始不完整，卡片上會寫錨在全量紀錄第幾行"],
  ]],
  ["卡片裡那一排小點", [
    ['<span class="swatch"><i class="d read"></i><i class="d read"></i><i class="d read"></i></span>',
     "深灰", "讀檔案、搜尋這類不改動東西的動作"],
    ['<span class="swatch"><i class="d run"></i><i class="d run"></i></span>',
     "淺灰", "跑指令"],
    ['<span class="swatch"><i class="d write"></i><i class="d write"></i></span>',
     "藍色", "真的改了檔案"],
    ['<span class="swatch"><i class="d fail"></i></span>',
     "紅色", "那個工具回了錯誤。這是誠實的失敗，不是騙人"],
    ['<span class="swatch"><i class="d white"></i></span>',
     "白色實心點", "它說做了某件事，而那一輪的紀錄裡沒有那個動作。會另外跳一張白卡告訴你下一句該問什麼"],
    ["", "那排點平常收起來",
     "正常的一輪，那排點全是同一個灰，上面的「讀了 10 · 跑了 34」已經講完了。只有那一輪有失敗或壓縮的時候才展開，因為那時候密度才有意義"],
  ]],
  ["其他標記", [
    ['<span class="gapmark">8m 沒動作</span>', "橘色標籤",
     "那一輪中間有一段時間完全沒有動作。超過一分鐘才標，不然每一輪都會出現"],
    ['<span class="dn">x2</span>', "x2",
     "同一個工具連續叫了幾次，合併成一個點"],
    ['<span class="swatch lgLt" data-lt="owner"><i class="ltm"></i></span>',
     "左邊那條紅線",
     "這一段你出手了。三種來源：你按下打斷、你貼終端機輸出替它跑指令（這兩種是系統記下來的），或者你那句話被判定成糾正。線的長度就是那一段拖了幾輪"],
    ['<span class="swatch lgLt" data-lt="self"><i class="ltm"></i></span>',
     "左邊那條斷續的綠線",
     "這一段沒偵測到你出手，所以算成它自己回到中軸。畫成斷續的是因為這是上限不是事實：三種來源裡「糾正句式」那一項走詞表，會漏抓，而漏抓的方向一律是把你的出手算成它自己回來的"],
    ['<span class="swatch lgLt" data-lt="open"><i class="ltm"></i></span>',
     "左邊那條琥珀線",
     "這一段還開著，到現在都沒回到中軸。它底下沒有收尾的那一橫，因為畫了就等於說這裡結束了"],
  ]],
  ["上面那塊", [
    ["", "Forseti 建議",
     "常態出現。有說了沒做的地方就先講那個，沒有就講這段對話裡其他值得看的事。接不接受是你的事"],
    ["", "跟著你",
     "它跟的是你最後送訊息的那個 session，不是最後寫檔的那個。你同時開十幾個的時候，背景在跑的不會把畫面搶走"],
  ]],
];

function buildLegend() {
  const box = $("legend");
  if (box.dataset.built) return;
  box.dataset.built = "1";
  LEGEND.forEach(([group, items]) => {
    const h = document.createElement("h3");
    h.textContent = group;
    box.appendChild(h);
    items.forEach(([icon, title, desc]) => {
      const row = document.createElement("div");
      row.className = "lg";
      row.innerHTML = `<div class="lgIcon">${icon}</div>` +
        `<div class="lgText"><b>${esc(title)}</b><span>${esc(desc)}</span></div>`;
      box.appendChild(row);
    });
  });
}

const sheet = $("sheet");
function openSheet() { buildLegend(); sheet.hidden = false; }
function closeSheet() { sheet.hidden = true; }
$("helpBtn").addEventListener("click", openSheet);
$("miniT")?.addEventListener("click", () => togglePanel());
$("sheetClose").addEventListener("click", closeSheet);
sheet.addEventListener("click", (e) => { if (e.target === sheet) closeSheet(); });
addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  closeSheet();
  closeNode();
});


/* ── Session 選擇器 §24 ────────────────────────
   owner 2026-09-14 手繪:左上角漢堡，按下去蓋住整個畫面，
   選完回到 Tree。「這樣就不用一直跳來跳去了。」

   自動跟隨判不準，因為她同時開十幾個 session，
   而判準只能從檔案痕跡推。與其猜，不如讓她自己指。
   自動仍然是預設 —— 選擇器第一項就是它。 */

const PICK_KEY = "forseti.session";
let picked = null;        // null = 跟著最新
try { picked = localStorage.getItem(PICK_KEY) || null; } catch (e) { picked = null; }

let allSessions = [];
const picker = $("picker");

function timeAgo(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 120) return "剛剛";
  if (s < 3600) return `${Math.round(s / 60)} 分鐘前`;
  if (s < 86400) return `${Math.round(s / 3600)} 小時前`;
  return dayLabel(ts);
}

// 分組照「找得到」排，不照專案排 ——
// owner 的 session 幾乎都開在同一個工作目錄，用專案分會全擠成一組。
// 她要找的是「我剛才在看的那個」，所以按最後活動時間分。
function bucketOf(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 300) return "剛剛還在動";
  const d = new Date(ts * 1000), now = new Date();
  if (d.toDateString() === now.toDateString()) return "今天稍早";
  return "更早";
}

function renderPicker() {
  const box = $("pickList");
  const q = ($("pickQuery").value || "").trim().toLowerCase();
  box.textContent = "";

  const auto = document.createElement("button");
  auto.className = "pk" + (picked ? "" : " live");
  auto.setAttribute("aria-current", picked ? "false" : "true");
  auto.innerHTML = '<span class="pkDot"></span><span class="pkBody">' +
    '<span class="pkTitle">跟著你切到哪一個</span>' +
    '<span class="pkMeta">你切過去看它就跟過去，不必發訊息</span>' +
    "</span>";
  auto.addEventListener("click", () => choose(null));
  box.appendChild(auto);

  const rows = allSessions.filter((x) =>
    !q || (x.title || "").toLowerCase().includes(q) || x.id.includes(q));
  if (!rows.length) {
    box.insertAdjacentHTML("beforeend",
      '<div class="pkNone">沒有符合的</div>');
    return;
  }

  // 每一列都印同一個工作目錄等於沒有資訊。只有分得出來的時候才印。
  const manyGroups = new Set(allSessions.map((x) => x.group)).size > 1;
  let bucket = "";
  rows.forEach((x) => {
    const b = bucketOf(x.focused_at || x.mtime);
    if (b !== bucket) {
      bucket = b;
      const h = document.createElement("h3");
      h.textContent = b;
      box.appendChild(h);
    }
    const live = Date.now() / 1000 - x.mtime < 300;
    const el = document.createElement("button");
    el.className = "pk" + (live ? " live" : "");
    el.setAttribute("aria-current", String(picked === x.id));
    // 輪數比檔案大小有意義。時間用「最後看的」，那才是她記得的。
    const seen = x.focused_at
      ? `看於 ${timeAgo(x.focused_at)}` : timeAgo(x.mtime);
    const meta = [x.turns ? `${x.turns} 個來回` : "", seen,
                  manyGroups ? x.group : ""].filter(Boolean).join(" · ");
    el.innerHTML =
      '<span class="pkDot"></span><span class="pkBody">' +
      `<span class="pkTitle">${esc(x.title || x.id.slice(0, 8))}</span>` +
      `<span class="pkMeta">${esc(meta)}</span></span>`;
    el.addEventListener("click", () => choose(x.id));
    box.appendChild(el);
  });
}

function choose(id) {
  picked = id;
  try {
    if (id) localStorage.setItem(PICK_KEY, id);
    else localStorage.removeItem(PICK_KEY);
  } catch (e) { /* 無痕視窗之類，選擇只在這次有效 */ }
  closePicker();
  rows = [];
  lastCount = 0;
  tick();
}

async function openPicker() {
  picker.hidden = false;
  $("pickQuery").value = "";
  $("pickList").innerHTML = '<div class="pkNone">讀取中</div>';
  try {
    const raw = await invoke("sessions", {});
    allSessions = (JSON.parse(raw).sessions) || [];
  } catch (e) {
    allSessions = [];
    $("pickList").innerHTML =
      `<div class="pkNone">讀不到 session 清單：${esc(String(e))}</div>`;
    return;
  }
  renderPicker();
}
function closePicker() { picker.hidden = true; }

$("burgerBtn").addEventListener("click", openPicker);
$("pickClose").addEventListener("click", closePicker);
$("pickQuery").addEventListener("input", renderPicker);
addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !picker.hidden) closePicker();
});

/* ── 輪詢 §13 1 到 3 秒 ──────────────────────── */

// 量不到就說出來，而且要說在看得見的地方。
//
// 【2026-09-14 實測】第一版只在底部印一行「不在 Tauri 裡」，
// 畫面其他地方一片空白 —— 看起來像「這個 session 沒有東西」，
// 而實際上是整個資料層沒接上。
// 一個安靜的失敗畫面跟一個沒有問題的畫面長一樣，
// 那正是這支工具存在的理由。
function fatal(title, detail) {
  $("stat").textContent = title;
  $("lane").innerHTML =
    `<div class="card black-note fatal"><b>${esc(title)}</b>` +
    `${esc(detail)}</div>`;
  // 主畫面那一塊就是最顯眼的地方,所以錯誤印在那裡。
  // 先前還會同時寫進頂部的建議列與那排數字,那兩塊 2026-09-18 砍掉了 ——
  // 少一個出口不影響這條:量不到一定要說出來,而 lane 是她一定會看到的。
}

/* 上一輪還沒回來就跳過這一輪。

   【2026-09-18 事故】輪詢是兩秒一輪（那一行在這個檔最底下），而
   `strands` 在真實資料上要 17.6 秒（冷）／6.7 秒（熱）。
   於是每一輪都在上一輪還沒回來的時候又起一個 Python 子行程，
   八九個同時跑互相搶 CPU，每一個因此更慢，累積得更多 ——
   **它不是慢，是永遠不會完成。**

   owner 看到的是視窗開著、整片黑、底部寫「啟動中」。
   `fatal()` 沒被觸發，因為 invoke 既沒成功也沒拋錯，它還在跑。
   實測 ps:App 跑了 5 分 50 秒，而它底下的 Python 子行程只有 8 秒大。

   這個旗標治的是「重疊」。真正的 17.6 秒要另外治，
   那是 `_meta_rows` 2.4 秒、四次 subprocess 1.4 秒、
   `claims.verify` 36 次 1 秒、`blast.summary` 0.9 秒加起來的
   （2026-09-18 砍掉畫面用不到的那幾塊之後這個組成會變,
    沒有重新量過之前不要把上面那些數字當成現況）。 */
let inFlight = false;
let slowSince = 0;

async function tick() {
  if (inFlight) {
    // 等太久要讓人看得出它在跑，不是死了。
    // 一片黑加一個小字「啟動中」，跟當掉長得一模一樣。
    if (slowSince && Date.now() - slowSince > 4000) {
      const s = $("stat");
      if (s) {
        s.textContent = `讀取中 ${Math.round((Date.now() - slowSince) / 1000)}s`;
      }
    }
    return;
  }
  if (!invoke) {
    fatal("拿不到 Tauri",
      "window.__TAURI__ 不存在。tauri.conf.json 要設 app.withGlobalTauri = true，" +
      "否則前端呼叫不到後端，畫面會是空的。");
    return;
  }
  inFlight = true;
  if (!slowSince) slowSince = Date.now();
  try {
    const raw = await invoke("strands", { session: picked });
    slowSince = 0;
    const d = JSON.parse(raw);
    if (d.error) throw new Error(d.error);
    rows = d.rows || [];
    // 它在看哪一個，以及憑什麼是那一個。
    //
    // owner 同時開十幾個 session。原本跟的是「哪份 jsonl 最後被寫」，
    // 那反映的是 AI 在做什麼，不是她在做什麼 ——
    // 她正在看的那個（AI 剛回完、等她決定）不寫檔，畫面就跳走。
    const first = rows[0];
    const when = first
      ? `${dayLabel(first.started_at)} ${hhmmss(first.started_at).slice(0, 5)} 起`
      : "";
    uiId = d.ui_id || "";
    currentSession = d.session || "";
    const how = picked ? "鎖定" : (d.picked_by || "");
    $("sessName").textContent = [how, when].filter(Boolean).join(" · ");
    $("sessName").title = "session " + (d.session || "");
    setContext(d);
    const grew = rows.length !== lastCount;
    lastCount = rows.length;
    lastSnap = d;
    renderRescue(d);
    if (view === "tree") renderTree();
    else renderList();
    if (follow && view === "tree")
      $("scroll").scrollTop = $("scroll").scrollHeight;
    $("stat").textContent = `${d.strands} 線 · ${d.total_dots} 點`;
  } catch (e) {
    // 量不到要說出來，不是畫一個綠燈。
    fatal("讀不到 transcript", String(e).slice(0, 200));
  } finally {
    // 【一定要放回去】放在 finally 不放在 try 的結尾:
    // 拋錯的時候旗標留在 true，之後每一輪都會被跳過，
    // 畫面從此不再更新，而那跟「沒有新的事情發生」長得一樣。
    //
    // （這裡刻意不用另外四個字描述那個狀態,
    //   `test_sot` 禁止這個檔出現它們 —— 沒量到不等於沒事。）
    inFlight = false;
  }
}

function syncView() {
  // 換分頁一定回到頂端。
  //
  // 【2026-09-14】切到「功能」那一頁，內容都在、樣式也對，
  // 畫面卻是全黑 —— 捲動位置還留在前一頁的 5075px，
  // 停在最底下的空白區。DOM 有東西不等於看得到。
  const sc = $("scroll");
  if (sc) sc.scrollTop = 0;
  document.querySelectorAll(".vw").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.view === view)));
  if (view === "tree") renderTree();
  else renderList();
}

document.querySelectorAll(".vw").forEach((b) =>
  b.addEventListener("click", () => {
    view = b.dataset.view;
    syncView();
    closePicker();
  }));

// §9 捲動獨立。往上捲就停止跟隨，回到底部恢復。
$("scroll").addEventListener("scroll", () => {
  const el = $("scroll");
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  if (!atBottom && follow) { follow = false; $("followBtn").setAttribute("aria-pressed", "false"); }
  if (atBottom && !follow) { follow = true; $("followBtn").setAttribute("aria-pressed", "true"); }
});
$("followBtn").addEventListener("click", () => {
  follow = !follow;
  $("followBtn").setAttribute("aria-pressed", String(follow));
  if (follow) $("scroll").scrollTop = $("scroll").scrollHeight;
});

// 根基先算。線色要用它,所以要在第一次畫線之前拿到。§40
loadFoundation().then(tick);
setInterval(tick, 2000);
// 讀文件的狀態會隨著我實際去讀而變,每分鐘重算一次。
setInterval(loadFoundation, 60000);
