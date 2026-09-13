// Forseti 桌面版前端。
//
// 這一層只做呈現。所有判斷來自 desktop_api.py,一個字都不在這裡重算 ——
// 兩份判斷邏輯遲早會分歧,而分歧的那天沒有人會發現。

const invoke = window.__TAURI__?.core?.invoke;
const listen = window.__TAURI__?.event?.listen;

const $ = (id) => document.getElementById(id);
const esc = (s) => { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; };
const flat = (s) => (s || "").split(/\s+/).filter(Boolean).join(" ");

let nodes = [];
let active = null;
let filter = null;
let currentSession = null;

function setStatus(t) { $("statusText").textContent = t; }
function stamp() {
  $("stamp").textContent = new Date().toLocaleTimeString("zh-TW", { hour12: false });
}

async function call(cmd, args) {
  if (!invoke) throw new Error("不在 Tauri 環境裡,拿不到後端");
  const raw = await invoke(cmd, args);
  return JSON.parse(raw);
}

/* ── 狀態 ─────────────────────────────────────── */

const LV_TEXT = { OK: "正常", WATCH: "留意", ATTENTION: "要處理" };

function renderHealth(s) {
  const o = s.overall || {};
  const lv = o.level || "OK";

  const lamp = $("lamp");
  lamp.dataset.lv = lv;
  lamp.querySelector(".lv").textContent = LV_TEXT[lv] || lv;
  $("repo").textContent = s.repo || "";

  const b = $("banner");
  b.dataset.lv = lv;
  b.innerHTML =
    '<div class="lv">' + esc(lv) + "</div>" +
    "<h2>" + esc(o.because || "沒有需要處理的事") + "</h2>" +
    '<p>' + esc(o.coverage || "") + "</p>" +
    '<div class="note">' + esc(o.note || "") + "</div>";

  const g = $("gauges");
  g.textContent = "";
  (s.gauges || []).forEach((x) => {
    const d = document.createElement("div");
    d.className = "gauge";
    d.dataset.lv = x.level || "OK";
    // 進度條的意義:現值相對門檻。超過門檻就滿格,那是刻意的 ——
    // 一個「超過多少」的細節不如「超過了」這件事本身重要。
    let pct = 0;
    const th = Number(x.threshold);
    const v = Number(x.value);
    if (Number.isFinite(th) && Number.isFinite(v)) {
      pct = th === 0 ? (v > 0 ? 100 : 0) : Math.min(100, Math.round((v / th) * 100));
    }
    d.innerHTML =
      '<div class="row"><span class="val">' + esc(String(x.value)) + "</span>" +
      '<span class="unit">' + esc(x.unit || "") + "</span>" +
      '<span class="lbl">' + esc(x.label || "") + "</span></div>" +
      '<div class="bar"><i style="width:' + pct + '%"></i></div>' +
      '<div class="why">' + esc(x.why || "") + "</div>" +
      '<div class="src">' + esc(x.source || "") + "</div>";
    g.appendChild(d);
  });

  const a = $("advice");
  a.textContent = "";
  (s.advice || []).forEach((x) => {
    const c = document.createElement("div");
    c.className = "card";
    c.dataset.sev = x.severity || "WATCH";
    c.innerHTML =
      "<h3>" + esc(x.title || "") + "</h3>" +
      "<p>" + esc(x.detail || "") + "</p>" +
      '<div class="do"><code>' + esc(x.action || "") + "</code>" +
      '<button class="cp">複製</button></div>';
    const btn = c.querySelector(".cp");
    btn.addEventListener("click", () => copy(x.action, btn));
    a.appendChild(c);
  });
  if (!(s.advice || []).length) {
    a.innerHTML = '<div class="card" data-sev="OK"><h3>沒有要提醒的事</h3>' +
      "<p>分項全部在門檻內。這不代表沒有問題,代表量得到的那幾項沒有問題。</p></div>";
  }
  stamp();
}

function copy(text, btn) {
  if (!navigator.clipboard) { btn.textContent = "複製不了"; return; }
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = "已複製";
    setTimeout(() => { btn.textContent = "複製"; }, 1400);
  }).catch(() => { btn.textContent = "複製不了"; });
}

/* ── 路徑 ─────────────────────────────────────── */

const LEVELS = ["OK", "STALLED", "WATCH", "CORRECTED", "BROKEN"];
const LV_DESC = {
  OK: "往下走了", STALLED: "只是叫我繼續", WATCH: "要我澄清",
  CORRECTED: "糾正了我", BROKEN: "糾正且驗不過",
};
const LV_COLOR = {
  OK: "var(--ok)", STALLED: "var(--watch)", WATCH: "var(--clarify)",
  CORRECTED: "var(--attention)", BROKEN: "var(--attention)",
};

function renderTree() {
  const counts = {};
  LEVELS.forEach((l) => (counts[l] = 0));
  nodes.forEach((n) => (counts[n.level] = (counts[n.level] || 0) + 1));

  const t = $("tally");
  t.textContent = "";
  LEVELS.forEach((l) => {
    if (!counts[l] && l === "BROKEN") return;
    const d = document.createElement("div");
    d.innerHTML = '<div class="n" style="color:' + LV_COLOR[l] + '">' +
      counts[l] + '</div><div class="k">' + l + "</div>";
    t.appendChild(d);
  });

  const m = $("mini");
  m.textContent = "";
  nodes.forEach((n) => {
    const i = document.createElement("i");
    i.style.background = LV_COLOR[n.level] || "var(--ink3)";
    i.title = "第 " + n.n + " 輪 · " + n.level;
    i.addEventListener("click", () => select(n.n));
    m.appendChild(i);
  });
  const stalled = nodes.filter((n) => n.level === "STALLED");
  $("miniNote").textContent = stalled.length
    ? "琥珀色是 STALLED,共 " + stalled.length + " 個。那些輪次裡她只是叫我繼續,代表上一輪停在不該停的地方。"
    : "沒有 STALLED。";

  drawFilters(counts);
  drawList();
}

function drawFilters(counts) {
  const f = $("filters");
  f.textContent = "";
  const mk = (label, val) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.setAttribute("aria-pressed", String(filter === val));
    b.addEventListener("click", () => { filter = filter === val ? null : val; renderTree(); });
    return b;
  };
  f.appendChild(mk("全部 " + nodes.length, null));
  LEVELS.forEach((l) => { if (counts[l]) f.appendChild(mk(l + " " + counts[l], l)); });
}

function drawList() {
  const list = $("list");
  list.textContent = "";
  nodes.forEach((n) => {
    if (filter && n.level !== filter) return;
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.className = "node";
    b.dataset.lv = n.level;
    b.dataset.n = n.n;
    b.setAttribute("aria-current", String(active === n.n));
    b.innerHTML =
      '<span class="i">' + n.n + "</span>" +
      '<span class="rail-col"><span class="dot" style="background:' +
      (LV_COLOR[n.level] || "var(--ink3)") + '"></span></span>' +
      '<span class="t"></span>';
    b.querySelector(".t").textContent = flat(n.owner_text).slice(0, 120) || "(無)";
    b.addEventListener("click", () => select(n.n));
    li.appendChild(b);
    list.appendChild(li);
  });
}

function select(num) {
  active = num;
  const i = nodes.findIndex((n) => n.n === num);
  if (i < 0) return;
  const n = nodes[i];
  const prev = i > 0 ? nodes[i - 1] : null;
  const bad = n.level !== "OK";

  let h =
    '<div class="dh"><span class="r">第 ' + n.n + " 輪</span>" +
    '<span class="badge b-' + n.level + '">' + n.level + "</span>" +
    '<span class="m">' + esc((n.at || "").slice(11, 16)) +
    " · owner L" + n.owner_line +
    ((n.tools || []).length ? " · " + n.tools.length + " 次工具" : "") +
    "</span></div>";

  h += '<p class="why-box">' + esc(n.why || LV_DESC[n.level] || "") + "</p>";
  h += '<div class="seg owner"><h4>她說</h4><p>' + esc(flat(n.owner_text).slice(0, 900)) + "</p></div>";
  h += '<div class="seg"><h4>我那一輪</h4><p>' +
    esc(flat(n.ai_text).slice(0, 1400) || "(這一輪沒有文字輸出)") + "</p></div>";

  if ((n.refuted || []).length) {
    h += '<div class="seg"><h4>驗不過的宣稱</h4><p>' +
      esc(n.refuted.join("\n")) + "</p></div>";
  }

  h += '<div class="fork"><h4>從哪裡 fork</h4>';
  if (bad && prev) {
    const cmd = "python3 tools/fork-session.py " + (currentSession || "<session>") +
      " --at-line " + prev.owner_line;
    h += "<p>退回第 " + prev.n + " 輪(owner 訊息在 transcript 第 " +
      prev.owner_line + " 行),那是這一節變色之前最後一個乾淨的節點。</p>" +
      '<div class="cmd"><code>' + esc(cmd) + '</code>' +
      '<button class="cp" data-cmd="' + esc(cmd) + '">複製</button></div>' +
      '<p class="fine">切點之後的紀錄會被丟掉,祖先鏈整條留著,原檔一個位元組都不動。' +
      "跑完會給一個新的 session id。</p>";
  } else if (bad) {
    h += "<p>這是第一輪,前面沒有可以退回的節點。</p>";
  } else {
    h += '<p style="color:var(--ink3)">這一節沒有變色,不需要 fork。</p>';
  }
  h += "</div>";

  const d = $("detail");
  d.innerHTML = h;
  const cp = d.querySelector(".fork .cp");
  if (cp) cp.addEventListener("click", () => copy(cp.dataset.cmd, cp));

  drawList();
  const el = $("list").querySelector('[data-n="' + num + '"]');
  if (el) el.scrollIntoView({ block: "nearest" });
}

/* ── 啟動與事件 ───────────────────────────────── */

async function refreshHealth() {
  try {
    setStatus("量測中");
    const s = await call("snapshot");
    renderHealth(s);
    setStatus("就緒");
  } catch (e) {
    setStatus("量不到:" + e);
    // 量不到要說出來,不是畫一個綠燈。
    $("lamp").dataset.lv = "";
    $("lamp").querySelector(".lv").textContent = "量不到";
    $("banner").innerHTML = '<div class="lv">量不到</div><h2>' +
      esc(String(e)) + "</h2><p>這不是「沒問題」,是「這一輪沒有量到」。</p>";
  }
}

async function loadSessions() {
  try {
    const s = await call("sessions");
    const pick = $("sessionPick");
    pick.textContent = "";
    (s.sessions || []).forEach((x) => {
      const o = document.createElement("option");
      o.value = x.id;
      const mb = (x.size / 1048576).toFixed(1);
      o.textContent = x.id.slice(0, 8) + " · " + mb + " MB";
      o.title = x.project + " / " + x.id;
      pick.appendChild(o);
    });
    $("loadHint").textContent = (s.sessions || []).length + " 個 session。大的要跑幾分鐘。";
  } catch (e) {
    $("loadHint").textContent = "拿不到 session 清單:" + e;
  }
}

async function loadTimeline() {
  const id = $("sessionPick").value;
  if (!id) return;
  const btn = $("loadBtn");
  btn.disabled = true;
  btn.textContent = "跑中";
  setStatus("算路徑中,大的 session 要幾分鐘");
  try {
    const t = await call("timeline", { session: id });
    if (t.error) throw new Error(t.error);
    nodes = t.rounds || [];
    currentSession = id;
    active = null;
    filter = null;
    renderTree();
    const firstBad = nodes.find((n) => n.level !== "OK");
    if (firstBad) select(firstBad.n);
    setStatus("路徑好了,共 " + nodes.length + " 輪");
    switchView("tree");
  } catch (e) {
    setStatus("算不出來:" + e);
    $("detail").innerHTML = '<p class="empty">' + esc(String(e)) + "</p>";
  } finally {
    btn.disabled = false;
    btn.textContent = "載入路徑";
  }
}

function switchView(v) {
  document.querySelectorAll(".tab").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.view === v)));
  $("view-tree").hidden = v !== "tree";
  $("view-health").hidden = v !== "health";
}

document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => switchView(b.dataset.view)));
$("loadBtn").addEventListener("click", loadTimeline);

(async function start() {
  switchView("health");
  await refreshHealth();
  await loadSessions();
  if (listen) {
    // .forseti/ 變了就重量。不是定時輪詢 ——
    // 一個自己就很吵的監控工具,正是這個系統要抓的東西(§24.2)。
    await listen("forseti://changed", () => { refreshHealth(); });
  }
})();
