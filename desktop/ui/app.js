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

/* ── 資訊中心 ──────────────────────────────────
   §22。那塊流動顏料被 owner 拿掉了，換成一句可以照做的話。
   判斷在 Python（desktop_api.session_advice），這裡只呈現。 */

let adviceTarget = 0;
let uiId = "";
let currentSession = "";

function setAdvice(d) {
  const a = d.advice || {};
  $("adviceText").textContent = a.text || "還沒有資料";
  $("adviceText").dataset.tone = a.tone || "info";
  $("adviceWhy").textContent = a.why || "";

  // 建議要指得到東西。
  // owner:「我看著他沒感覺，因為我不知道他在指什麼。」
  adviceTarget = a.n || 0;
  const goto = $("adviceGoto");
  const box = $("adviceBox");
  const inView = adviceTarget && rows.some((r) => r.n === adviceTarget);
  goto.hidden = !inView;
  if (inView) goto.textContent = `看第 ${adviceTarget} 輪`;
  box.classList.toggle("can", Boolean(inView));
}

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

$("adviceBox").addEventListener("click", () => {
  if (adviceTarget) jumpTo(adviceTarget);
});

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

/* 分項。§2
/* 分項。§2
/* 分項。§2
   溫度計不合成單一分數 —— 每一格量的是一件說得出名字的事。

   工具失敗跟「宣稱跟證據對不上」是兩種不同的事：
   一次 Bash 回非零是誠實的失敗，一個白點是說了沒做。
   把它們加權混成一個數字，那個數字就沒有單位了。 */
function renderSubs(d) {
  const box = $("subs");
  box.textContent = "";
  const items = [];
  items.push({ k: "來回", n: d.strands || rows.length,
               tip: "你發一次話、它回完，算一個來回" });
  if (d.betrayal_total) {
    // 標籤講事情本身，不講內部詞彙。
    // 「白點」是這份規格裡的名字，第一次看的人不知道那是什麼。
    items.push({ cls: "hot", k: "說了沒做", n: d.betrayal_total,
                 tip: "它宣稱做了某件事，而那一輪的紀錄裡沒有那個動作" });
  }
  if (d.premature_total) {
    // §31 提早收工。兩個訊號都成立才算:帳本上有已授權的下一步，
    // 而且她下一句真的開口催了。
    items.push({ cls: "hot", k: "提早收工", n: d.premature_total,
                 tip: "帳本上還有事可做，它卻停下來等你開口" });
  }
  if (d.total_failed) {
    items.push({ k: "工具失敗", n: d.total_failed,
                 tip: "指令回了非零。這是誠實的失敗，不是騙人" });
  }
  if (d.claim_total) {
    // §7.3 宣稱對現實。**這一格不加 hot。**
    //
    // 上面兩格是紅的，因為「說了沒做」跟「提早收工」是判定。
    // 這一格絕大多數是 UNKNOWN，代表驗證器搆不到，不是判定。
    // 把它染紅等於用顏色講了一個資料沒講的話。
    items.push({ k: "宣稱沒證實", n: d.claim_total,
                 tip: "提到的檔案拿去 stat 磁碟查過，沒查到。" +
                      "查不到不等於它說謊，等於驗證器搆不到" });
  }
  const stalls = rows.reduce((a, s) =>
    a + (s.gaps || []).filter((g) => g[1] - g[0] >= GAP_SHOW).length, 0);
  if (stalls) {
    items.push({ k: "沒動作", n: stalls,
                 tip: `超過 ${GAP_SHOW} 秒完全沒有動作的段落` });
  }
  box.className = "subs";

  items.forEach((it) => {
    const el = document.createElement("div");
    el.className = "sub" + (it.cls ? " " + it.cls : "");
    el.title = it.tip;
    el.innerHTML = `<span class="k">${esc(it.k)}</span>` +
                   `<span class="n">${it.n}</span>`;
    box.appendChild(el);
  });
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
/* 溫度卡。工程書 §17.2 的預設畫面。 §11.3 的公式在後端算。
   這裡只負責呈現，而且只呈現一件最高槓桿的事。 */
const BAND_ZH = {NORMAL: "安靜", WATCH: "注意", DEGRADED: "退化",
                 CRITICAL: "嚴重", UNKNOWN: "量不到"};

/* 面板開合。預設收起,讓樹吃滿。§17.3 只顯示單一最高槓桿的事實。 */
function togglePanel(force) {
  const p = $("panel"), b = $("miniT");
  if (!p || !b) return;
  const open = force == null ? p.hidden : force;
  p.hidden = !open;
  b.setAttribute("aria-expanded", String(open));
  if (open) { renderVitals(lastSnap || {}); renderCards(lastSnap || {}); }
}

function renderVitals(d) {
  const t = d.temp || {};
  const el = $("vTemp"), band = $("vBand");
  if (!el) return;
  if (t.c == null) {
    el.textContent = "--";
    el.className = "vTemp";
    band.textContent = BAND_ZH.UNKNOWN;
  } else {
    el.textContent = t.c.toFixed(1);
    el.className = "vTemp " + (t.band || "").toLowerCase();
    // FS-RSK-001：低覆蓋率的高分不能裝作確定，所以覆蓋率跟著溫度走。
    band.textContent = `${BAND_ZH[t.band] || t.band}　證據 ${
      Math.round((t.coverage || 0) * 100)}%`;
  }

  const mt = $("miniT");
  if (mt) {
    mt.textContent = t.c == null ? "--" : t.c.toFixed(1);
    mt.className = "miniT" + (t.band === "WATCH" ? " warm"
      : (t.band === "HOT" || t.band === "CRITICAL") ? " hot" : "");
  }

  const trend = d.goal_trend || 0;
  const g = (d.rows || []).slice(-1)[0]?.goal;
  const sup = g && g.support != null ? Math.round(g.support * 100) : null;
  $("vChange").innerHTML =
    `主要變化　<b>${esc(t.why || "還看不出來")}</b>` +
    (sup == null ? "" :
      `　目標支持率 <b>${sup}%</b>${trend > 0.005
        ? "，<b>正在往外飄</b>" : trend < -0.005 ? "，正在回到中軸" : ""}`);

  // Activity / Task / Goal 永遠分開。FS-DET-FPR-001
  const pr = d.progress || {};
  $("vProg").innerHTML =
    `已驗證進度　活動 <b>${pr.activity ?? 0}</b>` +
    `　寫入 <b>${pr.task ?? 0}</b>` +
    `　目標 <span class="unk">未知</span>`;
}

/* 八個維度。§22.2 內部每個維度要能分開查詢，
   因為脈絡壓力的解法跟證據過期、工具死結、協作反轉完全不同。 */
function renderDims(d) {
  let box = document.querySelector(".dims");
  if (!box) {
    box = document.createElement("ul");
    box.className = "dims";
    $("vitals").appendChild(box);
  }
  const NM = {context: "脈絡", runtime: "工具", progress: "進度",
              collab: "協作", evidence: "證據", strategy: "策略",
              resource: "資源", continuity: "連續性"};
  const dims = d.dims || {};
  box.innerHTML = Object.keys(NM).map((k) => {
    const v = dims[k] || {};
    if (v.score == null)
      return `<li><span class="nm">${NM[k]}</span>` +
             `<span class="none">沒有資料，不是沒問題</span>` +
             `<span class="ev">${esc(v.evidence || "")}</span></li>`;
    const pct = Math.round(v.score * 100);
    const cls = v.score >= .5 ? " bad" : v.score >= .2 ? " hot" : "";
    return `<li><span class="nm">${NM[k]}</span>` +
      `<span class="track"><i class="${cls.trim()}" style="width:${
        Math.max(2, pct)}%"></i></span>` +
      `<span class="ev">${esc(v.evidence || "")}</span></li>`;
  }).join("");
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
// 這張圖的盲點在哪個檔第幾行。
//
// 先前這裡只有一個總數。總數是免責聲明,位置才查得下去 ——
// 差別跟「這份報告可能有錯」與「第 190 行這一句是錯的」一樣大。
//
// 兩半邊分開報,不合併成一張表,因為它們的解析方法不一樣:
// .py 走 ast(直譯器自己的剖析器),JS 走正則。合併會讓人以為
// 兩邊的位置一樣可靠。
//
// JS 半邊沒算成時寫「沒有資料」不寫 0,跟 live_conflicts 同一條:
// 一個 0 讀起來是「那半邊沒有盲點」,那是一句沒有根據的話。
function blindSpotWhere(b) {
  const rows = [];
  const add = (half, list) => {
    for (const w of list || []) {
      rows.push(`<li><span class="bsHalf">${esc(half)}</span>` +
        `<span class="bsWhere">${esc(w.from || "")}` +
        `<span class="bsLine">:${w.line == null ? "?" : w.line}</span> ` +
        `<span class="bsCall">${esc(w.call || "")}</span></span></li>`);
    }
  };
  add(".py", b.py_dynamic_where);
  // null 跟 [] 在這裡是兩件事:null 是沒算成,[] 是算過而且真的沒有。
  if (b.js_dynamic_where != null) add("JS", b.js_dynamic_where);

  const shown = rows.length;
  const total = (b.py_dynamic_opaque || 0) +
    (b.js_dynamic_opaque == null ? 0 : b.js_dynamic_opaque);
  if (!shown) {
    // 一筆位置都沒有時也要說話。空白讀起來像「沒有盲點」,
    // 而真相可能是「有盲點但位置沒帶出來」。
    return total
      ? `<p class="blNote">這 ${total} 筆盲點的位置沒有帶出來。</p>`
      : "";
  }
  const more = total > shown
    ? `，另外 ${total - shown} 筆沒有列出來（畫面每半邊只列前 20 筆）`
    : "";
  return `<p class="blNote">看不到的地方在這裡${more}：</p>` +
    `<ul class="blindSpots">${rows.join("")}</ul>` +
    (b.js_dynamic_where == null && b.js_dynamic_opaque == null
      ? `<p class="blNote">JS 半邊的位置沒有資料（不是沒有盲點）。</p>`
      : "");
}

// Blast Radius §16.1。M4 精確定義在五機制文件第 6 節。
//
// **這一格最容易說謊的地方是那些 0。** 第 6.4 節原話:一個會說謊的
// blast radius 比沒有 blast radius 危險得多,一旦它騙過她一次,
// 整個介面就變裝飾品。所以:
//
//   uncovered_d1 沒有 lcov 時是 null,畫面寫「沒有覆蓋資料」不寫 0
//   live_conflicts 沒有 WriteScope 來源時,畫面寫「沒有資料來源」不寫 0
//   整個向量永遠是下界,這句話印在格子裡,不是藏在註解
//
// 也不合成單一分數(第 6.8 節雷一):合成會把可行動的維度
// 壓平成不可行動的一個數字。
function renderBlast(d) {
  let box = document.querySelector(".blast");
  if (!box) {
    box = document.createElement("div");
    box.className = "blast";
    $("vitals").appendChild(box);
  }
  const b = d.blast;
  if (!b || !b.has) {
    box.innerHTML = `<p class="hd">波及範圍` +
      `<span class="none">${esc((b && b.why) || "沒有資料，不是沒問題")}</span></p>`;
    return;
  }
  // 重畫會把 innerHTML 整個換掉，包含使用者正在打字的那個輸入框。
  // 先記下焦點與游標位置，畫完再放回去 —— 不然每 2 秒一次的輪詢
  // 會在打字打到一半時把字跟游標吃掉。
  const oldQ = box.querySelector(".blQ");
  const qFocused = !!oldQ && document.activeElement === oldQ;
  const qCaret = oldQ ? oldQ.selectionStart : null;
  blastFiles = b.all_files || [];
  blastFilesWhy = b.all_files_why || "";

  const rows = (b.top || []).map((t) => {
    const v = t.vector;
    const name = String(t.target).split("/").pop();
    // 可點。owner 要的是「點一個節點，看得到哪些檔案依賴它」，
    // 而排行榜給的是「十」不是「哪十個」。
    return `<div class="blRow blHit" data-blast="${esc(t.target)}" ` +
      `role="button" tabindex="0">` +
      `<span class="blF" title="${esc(t.target)}">${esc(name)}</span>` +
      `<span class="blN">${v.d1_count}</span>` +
      `<span class="blN blDim">${v.d2_count}</span>` +
      `<span class="blN blDim">${v.cross_modules}</span></div>`;
  }).join("");

  // 這一格是不是剛算的。**一個舊數字看起來跟一個新數字一模一樣**，
  // 而後端每 2 秒被問一次、算一次要三秒，所以多半是快取回來的。
  // 不標就是讓人以為畫面上的數字反映的是此刻的原始碼。
  // 沒有這個標的時候有兩種情況，而先前這兩種在畫面上一模一樣：
  // 一種是這一次剛算的（下一次會命中），一種是快取根本寫不進去
  // （每一次都會整個重算）。後者是 `blast.py` 的 `_cache_put()`
  // 在 2026-09-17 之前靜默吞掉的那一種，實測快取目錄唯讀的時候
  // 回傳的 36 個鍵一個都沒少，所以這一格看不出任何差別。
  // **標成紅的，跟上面那個「快取」不同**：那個是事實不是錯誤，
  // 這個是一件壞掉的事，只是壞的是速度不是答案。
  const cw = String(b.cache_write || "");
  const fresh = b.cached
    ? `<span class="blStale" title="檔案沒變就不重算，改了會自己失效">快取</span>`
    : (cw.slice(0, 7) === "failed:"
      ? `<span class="blStale bad" title="${esc(b.cache_write_why || "")}">快取寫不進去</span>`
      : "");
  box.innerHTML =
    `<p class="hd">波及範圍` +
    `<span class="sub">${b.files} 個檔案　${b.edges} 條依賴邊</span>${fresh}</p>` +
    `<div class="blRow blHead"><span class="blF">改這個檔</span>` +
    `<span class="blN">直接</span><span class="blN">間接</span>` +
    `<span class="blN">模組</span></div>` + rows +
    `<p class="blNote">${esc(b.lower_bound_why)}。</p>` +
    `<p class="blNote">沒有覆蓋資料：${esc(b.coverage_why)}</p>` +
    `<p class="blNote">衝突面積無來源：${esc(b.live_why)}</p>` +
    `<p class="blNote">模組怎麼算：${esc(b.module_rule)}</p>` +
    `<p class="blNote">點一行看是哪些檔依賴它。` +
    `這張榜只有前 ${(b.top || []).length} 名，` +
    `其餘 ${Math.max(0, (b.files || 0) - (b.top || []).length)} 個檔用下面那格找。</p>` +
    `<div class="blFind"><input class="blQ" type="text" ` +
    `placeholder="搜尋這 ${b.files} 個節點的檔名或路徑" ` +
    `aria-label="搜尋要看波及範圍的檔案"></div>` +
    `<div class="blHits"></div>` +
    `<div class="blDetail" hidden></div>` +
    `<p class="blNote">跨語言斷點 ${(b.cross_language || []).length} 處，` +
    `未解析 import ${b.unresolved_total} 筆，解析率 ${b.resolution_rate}。` +
    `Python 呼叫 JS 走子行程，靜態分析連不起來，所以標成斷點不連邊。</p>` +
    // 兩半邊的組成與解析方法。**不標等於讓人以為整張圖是同一種品質。**
    // .py 走 ast（直譯器自己的剖析器），.js 走正則（src/imports.js
    // 的檔頭自己寫明它不用 AST，因為那會引入依賴）。
    `<p class="blNote">這張圖有兩半邊：` +
    `.py ${b.py_files} 個檔 ${b.py_edges} 條邊，` +
    `JS ${b.js_files} 個檔 ${b.js_edges} 條邊。</p>` +
    `<p class="blNote">解析方法不一樣：${esc(b.parser_why || "")}。</p>` +
    // 這張圖的盲點。`is_lower_bound` 先前只寫成一句話，
    // 讀起來像一句免責聲明 —— 這兩行是它的可查數字版本：
    // 下界差多少、其中哪一部分這一輪補回來了。
    `<p class="blNote">這張圖已知看不到的：` +
    `.py ${b.py_dynamic_opaque} 筆動態 import，JS ` +
    `${b.js_dynamic_opaque == null
        ? "沒有資料（不是 0，是 JS 半邊沒算成）"
        : b.js_dynamic_opaque + " 筆"}。` +
    `${esc(b.blind_spot_why || "")}。</p>` +
    // 盲點的位置，不只是盲點的數量。
    //
    // 一個總數說得出「這張圖有 23 個看不到的地方」，說不出
    // 「所以我該去看哪裡」。前者讀完就結束了，後者查得下去。
    // 兩半邊各自標明，因為它們的解析方法不一樣（.py 走 ast，
    // JS 走正則），而位置的可靠度跟著解析方法走。
    blindSpotWhere(b) +
    (b.py_deferred_edges
      ? `<p class="blNote">另外有 ${b.py_deferred_edges} 條延後 import ` +
        `解得出來，所以進圖了：${esc(b.deferred_why || "")}。</p>`
      : "") +
    ((b.js_unreadable || []).length
      ? `<p class="blNote">有 ${(b.js_unreadable || []).length} 個 JS 檔讀不到，` +
        `它們的邊不在圖裡，這不是它們沒有依賴。</p>`
      : "") +
    (b.js_why ? `<p class="blNote">JS 半邊沒算成：${esc(b.js_why)}</p>` : "");

  // 事件綁在容器上，不是每一行綁一個 —— renderBlast 每次輪詢都會
  // 重畫 innerHTML，逐行綁會隨著重畫次數累積成一堆孤兒 listener。
  // 容器本身只在第一次建立，所以這個旗標保證只綁一次。
  if (!box.dataset.wired) {
    box.dataset.wired = "1";
    const hit = (e) => {
      const row = e.target.closest("[data-blast]");
      if (!row || !box.contains(row)) return;
      showBlastDetail(row.dataset.blast);
    };
    box.addEventListener("click", hit);
    box.addEventListener("keydown", (e) => {
      // 輸入框裡的空白鍵是空白，不是「點這一行」。
      if (e.target && e.target.classList.contains("blQ")) return;
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); hit(e); }
    });
    // 輸入事件一樣委派在容器上：.blQ 每次重畫都是新的節點，
    // 綁在它自己身上會隨重畫累積成一堆孤兒 listener。
    box.addEventListener("input", (e) => {
      if (!e.target || !e.target.classList.contains("blQ")) return;
      blastQuery = e.target.value;
      renderBlastHits(box);
    });
  }
  // 搜尋結果要先畫回來，`blastOpen` 標記的那一行才可能在裡面
  // （點搜尋結果展開的明細，它的那一行不在排行榜上）。
  const inp = box.querySelector(".blQ");
  if (inp) {
    inp.value = blastQuery;
    if (qFocused) {
      inp.focus();
      if (qCaret != null) {
        try { inp.setSelectionRange(qCaret, qCaret); } catch (e) { /* 有些瀏覽器不給 */ }
      }
    }
  }
  renderBlastHits(box);

  // 重畫之後把先前展開的那一個標回去（innerHTML 換掉了選取狀態）。
  // 用 querySelectorAll：同一個檔可能同時出現在排行榜跟搜尋結果裡，
  // 只標第一個會讓另一邊看起來沒被選到。
  if (blastOpen) {
    box.querySelectorAll(`[data-blast="${CSS.escape(blastOpen)}"]`)
      .forEach((row) => row.classList.add("on"));
    const d = box.querySelector(".blDetail");
    if (d && blastHtml) { d.innerHTML = blastHtml; d.hidden = false; }
  }
}

/* 搜尋框那一格。

   `blast_detail` 對圖裡**任何**一個節點都算得出來，但畫面上先前
   只有排行榜那 8 行能點，另外 96 個檔沒有入口。缺的一直是入口，
   不是後端能力。

   過濾在前端做，不打後端 —— 完整清單本來就在快照的 `all_files`
   裡，每打一個字去跑一次 node 只會讓輸入卡住。 */
let blastQuery = "";
let blastFiles = [];
let blastFilesWhy = "";
const BLAST_HITS_MAX = 10;

function renderBlastHits(box) {
  const wrap = box && box.querySelector(".blHits");
  if (!wrap) return;
  const raw = blastQuery.trim();
  if (!raw) {
    wrap.innerHTML = blastFilesWhy
      ? `<p class="blNote">${esc(blastFilesWhy)}</p>` : "";
    return;
  }
  const q = raw.toLowerCase();
  const hit = blastFiles.filter((f) => String(f).toLowerCase().includes(q));
  if (!hit.length) {
    // 找不到不是「沒有人依賴它」，是「這張圖裡沒有這個節點」。
    // 跟 `blast.detail()` 對未知路徑回 known:false 同一條理由：
    // 兩者在畫面上長得一樣，而前者讀起來像「改它很安全」。
    wrap.innerHTML = `<p class="blNote">這張圖的 ${blastFiles.length} 個節點裡` +
      `沒有叫「${esc(raw)}」的。${esc(blastFilesWhy)}</p>`;
    return;
  }
  const rows = hit.slice(0, BLAST_HITS_MAX).map((f) =>
    `<div class="blRow blHit" data-blast="${esc(f)}" role="button" tabindex="0">` +
    `<span class="blF" title="${esc(f)}">${esc(f)}</span></div>`).join("");
  wrap.innerHTML = rows + (hit.length > BLAST_HITS_MAX
    ? `<p class="blNote">符合的有 ${hit.length} 個，這裡只列前 ` +
      `${BLAST_HITS_MAX} 個。打精確一點，或連目錄一起打。</p>`
    : `<p class="blNote">符合的 ${hit.length} 個都在這裡。</p>`);
}

/* 目前展開的是哪一個檔，加上它算出來的內容。
   存起來是因為 renderBlast 每 1 到 3 秒重畫一次 innerHTML，
   不存的話她點開的明細會在下一次輪詢自己消失。 */
let blastOpen = null;
let blastHtml = "";

/** 點一個節點，問後端誰依賴它。§16.1 */
async function showBlastDetail(target) {
  const box = document.querySelector(".blast");
  if (!box) return;
  const panel = box.querySelector(".blDetail");
  if (!panel) return;

  // 再點一次收起來。
  if (blastOpen === target) {
    blastOpen = null; blastHtml = "";
    panel.hidden = true; panel.innerHTML = "";
    box.querySelectorAll("[data-blast].on").forEach((r) => r.classList.remove("on"));
    return;
  }
  blastOpen = target;
  box.querySelectorAll("[data-blast]").forEach((r) =>
    r.classList.toggle("on", r.dataset.blast === target));
  panel.hidden = false;
  blastHtml = `<p class="blNote">算中…</p>`;
  panel.innerHTML = blastHtml;

  let d;
  try {
    d = JSON.parse(await invoke("blast_detail", { target }));
  } catch (e) {
    blastHtml = `<p class="blNote bad">${esc(String(e))}</p>`;
    panel.innerHTML = blastHtml;
    return;
  }
  if (!d.has) {
    // 算不出來跟沒有人依賴它是兩件事，畫面不准把前者畫成 0。
    blastHtml = `<p class="blNote bad">${esc(d.why || "算不出來")}</p>`;
    panel.innerHTML = blastHtml;
    return;
  }

  const list = (arr, cls) => (arr || []).map((f) =>
    `<span class="blChip ${cls}" title="${esc(f)}">${
      esc(String(f).split("/").pop())}</span>`).join("");

  const mods = (d.modules || []).map(([m, n]) =>
    `${esc(m)} ${n}`).join("　");

  blastHtml =
    `<p class="hd2">${esc(d.target)}</p>` +
    `<p class="blNote">直接依賴它的 ${d.d1_count} 個：</p>` +
    `<div class="blChips">${list(d.d1, "d1") || '<span class="none">沒有</span>'}</div>` +
    `<p class="blNote">間接波及的 ${d.d2_count} 個：</p>` +
    `<div class="blChips">${list(d.d2plus, "d2") || '<span class="none">沒有</span>'}</div>` +
    `<p class="blNote">波及模組：${mods || "沒有"}（${esc(d.module_rule)}）</p>` +
    `<p class="blNote">它自己用了 ${(d.depends_on || []).length} 個專案內的檔` +
    `${(d.depends_on || []).length ? "：" : ""}` +
    `${(d.depends_on || []).map((f) => esc(String(f).split("/").pop())).join("、")}。` +
    `${esc(d.depends_on_note)}</p>` +
    `<p class="blNote">外部 import ${(d.external || []).length} 個` +
    `${(d.external_third_party || []).length
        ? `，其中第三方 ${(d.external_third_party || []).map(esc).join("、")}`
        : "，全部是標準庫"}。` +
    `跨語言斷點 ${(d.cross_language || []).length} 處` +
    `${(d.cross_language || []).length
        ? `：${(d.cross_language || []).map(esc).join("、")}` : ""}。</p>` +
    // 誠實條款。答得出來的只有檔案那一種，另外兩種講清楚為什麼，
    // 不留一個空清單讓人讀成「沒有任務依賴它」。
    `<p class="blNote">任務依賴：${esc(d.tasks_why)}</p>` +
    `<p class="blNote">session 依賴：${esc(d.sessions_why)}</p>` +
    `<p class="blNote">${esc(d.lower_bound_why)}。</p>`;
  panel.innerHTML = blastHtml;
}

// §40 污染登記簿。**後端從 2026-09-16 19:2x 就算得出來，
// 缺的一直是入口** —— 跟 blast 明細那一次同一種缺口。
//
// 這一格上每一筆的重點不是「正確答案是多少」，是**當初為什麼會錯**
// （§40 開頭那一句：數字改掉就沒事，機制不改掉會再犯一次）。
// 所以機制那一行不是附註，是這一格存在的理由。
//
// 三條誠實條款都在畫面上，不在註解裡:
//
//   半徑 null 印「算不出來」加原因，**不印 0** —— 規格列了欄位沒定義單位
//   0 筆印「登記簿是空的」，**不印「沒有被推翻的結論」** ——
//     這份沒有自動掃描（B-05），沒人登不等於沒有
//   有偵測器攔著的筆數單獨報，其餘那些現在只靠人記得
const POL_ZH = {OPEN: "還沒收", PARTIAL: "收了一半",
                REVERIFIED: "重驗過", RESOLVED: "收乾淨了"};

/* 底部那層漸層要跟著捲動位置變，不是只看內容有沒有超出。

   **第一版只看超出，結果捲到底最後一筆的出處被淡掉**，讀起來像
   「下面還有」而其實已經到底了 —— 一個永遠亮著的「還有更多」
   跟沒有這個提示一樣沒有用，而且它還會蓋掉真的內容。
   截圖加實測抓到的:到底時 lastRowBottom 跟 listBottom 都是 295，
   內容是完整的，只有漸層把它遮掉。 */
function syncPlCut(list, moreSel = ".plMore") {
  if (!list) return;
  const rest = list.scrollHeight - list.clientHeight - list.scrollTop;
  list.classList.toggle("cut", rest > 1);
  const more = list.parentElement?.querySelector(moreSel);
  if (more) more.hidden = list.scrollHeight - list.clientHeight <= 1;
}

function renderPollution(d) {
  let box = document.querySelector(".pollution");
  if (!box) {
    box = document.createElement("div");
    box.className = "pollution";
    $("vitals").appendChild(box);
  }
  // **這一格是捲動的，而它每 1 到 3 秒整塊換 innerHTML。**
  // 預設行為是使用者捲到第 3 筆，兩秒後自己彈回頂端，而且沒有任何
  // 錯誤訊息 —— 實測捲到底 450px、6.5 秒後回到 0，節點已經不是同一個。
  // 症狀是「後面那幾筆永遠看不到」。跟搜尋框吃字是同一個根因。
  const oldList = box.querySelector(".plList");
  const keepScroll = oldList ? oldList.scrollTop : 0;
  const p = d.pollution;
  if (!p || !p.has) {
    box.innerHTML = `<p class="hd">已經被推翻的` +
      `<span class="none">${esc((p && p.why)
        || "讀不到登記簿，不是沒有污染")}</span></p>`;
    return;
  }
  const rows = p.rows || [];
  if (!rows.length) {
    // 空的跟乾淨的不是同一件事，而它們在一個數字上長得一模一樣。
    box.innerHTML = `<p class="hd">已經被推翻的` +
      `<span class="sub">登記簿是空的</span></p>` +
      `<p class="plNote">${esc(p.not_scanned_why || "")}</p>`;
    return;
  }
  const items = rows.map((r) => {
    const zh = POL_ZH[r.status] || r.status;
    const guard = r.guarded
      ? `<span class="plGuard" title="有預防規則或回歸偵測器攔著">有攔著</span>`
      : `<span class="plGuard off" title="現在只靠人記得">只靠人記得</span>`;
    // null 不是 0。畫面上這兩個差很多:0 讀起來是「量過了，沒有擴散」。
    const radius = r.radius == null
      ? `<p class="plNote">擴散半徑算不出來：${esc(r.radius_basis || "")}</p>`
      : `<p class="plNote">擴散半徑 ${esc(String(r.radius))}</p>`;
    const src = (r.sources || []).map((s) =>
      `<span class="plSrc">${esc(s)}</span>`).join("");
    return `<div class="plRow">` +
      `<p class="plHead"><span class="plSt ${esc(r.status)}">${esc(zh)}</span>` +
      `${guard}<span class="plId">${esc(r.id)}</span></p>` +
      `<p class="plOld">${esc(r.original)}</p>` +
      `<p class="plNew">實際是：${esc(r.corrected)}</p>` +
      `<p class="plWhy">當初為什麼會錯：${esc(r.mechanism)}</p>` +
      radius +
      (src ? `<p class="plSrcs">出處 ${src}</p>` : "") +
      `</div>`;
  }).join("");

  const bs = p.by_status || {};
  const tail = ["PARTIAL", "REVERIFIED", "RESOLVED"]
    .filter((k) => bs[k]).map((k) => `${POL_ZH[k]} ${bs[k]}`).join("　");
  box.innerHTML =
    `<p class="hd">已經被推翻的` +
    `<span class="sub">${p.total} 筆，${p.open} 筆還沒收乾淨` +
    `${tail ? "　" + esc(tail) : ""}</span></p>` +
    `<div class="plList">${items}</div>` +
    `<p class="plMore" hidden></p>` +
    `<p class="plNote">${esc(p.guard_note || "")}：${p.guarded} 筆。</p>` +
    (p.radius_unknown
      ? `<p class="plNote">${p.radius_unknown} 筆量不到擴散半徑。` +
        `${esc(p.radius_note || "")}</p>` : "") +
    `<p class="plNote">${esc(p.not_scanned_why || "")}</p>` +
    `<p class="plNote">出處 ${esc(p.source || "")}。</p>`;

  // 捲動位置放回去。**放回去之前不能讓它超出新的內容高度**，
  // 不然筆數變少的時候會停在一個空白的位置。
  const list = box.querySelector(".plList");
  if (list) {
    list.scrollTop = Math.min(keepScroll,
      Math.max(0, list.scrollHeight - list.clientHeight));
    // 「下面還有」要看得見。捲動區把最後一筆切成半截，而半截讀起來
    // 像畫面壞了，不像還有內容 —— 這個專案為同一件事付過一次代價（5c）。
    // 量出來才標:內容塞得下的時候標一句「往下捲」是假的。
    const more = box.querySelector(".plMore");
    if (more) {
      more.textContent = `這一格捲得動，${rows.length} 筆不是全部都看得見`;
    }
    syncPlCut(list);
    // 捲動事件委派在只建立一次的 box 上。`.plList` 每次重畫都是新節點，
    // 逐次綁會累積成一堆孤兒 listener —— 跟 `.blQ` 那次同一條。
    // scroll 不冒泡，所以走捕獲階段。
    if (!box.dataset.scrollBound) {
      box.dataset.scrollBound = "1";
      box.addEventListener("scroll", (e) => {
        const l = e.target;
        if (l && l.classList && l.classList.contains("plList")) syncPlCut(l);
      }, true);
    }
  }
}

const SOT_ZH = {
  BOUND: "接上了",
  PARTIAL: "接了一半",
  NO_SOURCE: "沒有來源",
  NOT_APPLICABLE: "不適用",
};

/* §12.2 來源優先序。這一格回答「這一類狀態該信哪個來源」。

   兩件事在這裡最容易被畫成謊話，所以都寫在畫面上不寫在註解裡：

   一，七行裡只有一行有即時量測。其餘六行如果也給一個燈，那個燈
       代表的是「沒有人檢查過」，而它看起來跟「檢查過，沒事」一樣。
       所以沒量的那幾行印的是「這一行沒有即時量測」。
   二，「不適用」跟「還沒接」要分得出來。兩個都畫成灰色的話，
       欠的那一塊會從畫面上消失，而那正是要看到的東西。 */
function renderSot(d) {
  let box = document.querySelector(".sot");
  if (!box) {
    box = document.createElement("div");
    box.className = "sot";
    $("vitals").appendChild(box);
  }
  // 捲動位置要留住。跟 .plList 同一個根因:每 1 到 3 秒整塊換 innerHTML。
  const oldList = box.querySelector(".sotList");
  const keepScroll = oldList ? oldList.scrollTop : 0;
  const t = d.sot;
  if (!t || !t.has) {
    box.innerHTML = `<p class="hd">這一類狀態該信誰` +
      `<span class="none">${esc((t && t.why)
        || "算不出來，不是沒有來源問題")}</span></p>`;
    return;
  }
  const rows = t.rows || [];
  const items = rows.map((r) => {
    const zh = SOT_ZH[r.state] || r.state;
    const uses = r.uses
      ? `<p class="sotUse">現在用：${esc(r.uses)}</p>`
      : "";
    // null 不是「正常」。沒量的那幾行要自己講出來。
    let live = `<p class="sotNote">這一行沒有即時量測</p>`;
    if (r.live && r.live.measured) {
      const ok = r.live.git_authoritative;
      live = `<p class="sotLive ${ok ? "ok" : "no"}">量出來：` +
        `${esc(r.live.why || "")}</p>`;
    } else if (r.live && !r.live.measured) {
      live = `<p class="sotNote">這一行量不到：${esc(r.live.why || "")}</p>`;
    }
    const stale = r.evidence_ok
      ? ""
      : `<p class="sotStale">憑據找不到了，這一條登記不能再信</p>`;
    const drift = r.evidence_drifted
      ? `<p class="sotNote">憑據行號漂了 ${r.evidence_drifted} 處，` +
        `原文還在</p>`
      : "";
    const no = (r.not_source || []).map((x) =>
      `<span class="sotNo">${esc(x)}</span>`).join("");
    return `<div class="sotRow">` +
      `<p class="sotHead"><span class="sotSt ${esc(r.state)}">${esc(zh)}` +
      `</span><span class="sotTy">${esc(r.state_type)}</span></p>` +
      `<p class="sotPref">該信：${esc(r.preferred_zh)}</p>` +
      (no ? `<p class="sotNos">不該信 ${no}</p>` : "") +
      uses + live + stale + drift +
      (r.note ? `<p class="sotNote">${esc(r.note)}</p>` : "") +
      `</div>`;
  }).join("");

  const bs = t.by_state || {};
  const tail = ["BOUND", "PARTIAL", "NO_SOURCE", "NOT_APPLICABLE"]
    .filter((k) => bs[k]).map((k) => `${SOT_ZH[k]} ${bs[k]}`).join("　");
  box.innerHTML =
    `<p class="hd">這一類狀態該信誰` +
    `<span class="sub">${t.total} 類${tail ? "　" + esc(tail) : ""}` +
    `</span></p>` +
    `<div class="sotList">${items}</div>` +
    `<p class="sotMore" hidden></p>` +
    `<p class="sotNote">${esc(t.live_note || "")}</p>` +
    `<p class="sotNote">${esc(t.not_applicable_note || "")}</p>` +
    (t.evidence_stale
      ? `<p class="sotStale">有 ${t.evidence_stale} 條憑據過期了</p>` : "") +
    `<p class="sotNote">出處 ${esc(t.source || "")}。</p>`;

  const list = box.querySelector(".sotList");
  if (list) {
    list.scrollTop = Math.min(keepScroll,
      Math.max(0, list.scrollHeight - list.clientHeight));
    const more = box.querySelector(".sotMore");
    if (more) {
      more.textContent = `這一格捲得動，${rows.length} 類不是全部都看得見`;
    }
    syncPlCut(list, ".sotMore");
    if (!box.dataset.scrollBound) {
      box.dataset.scrollBound = "1";
      box.addEventListener("scroll", (e) => {
        const l = e.target;
        if (l && l.classList && l.classList.contains("sotList")) {
          syncPlCut(l, ".sotMore");
        }
      }, true);
    }
  }
}

const ID_ZH = {
  SEPARABLE: "分得開",
  CONFLATED: "混在一起",
  NO_SOURCE: "沒有來源",
};

/* §11.1 持久身份。這一格回答「身份跟那五樣東西分得開嗎」。

   三件事在這裡最容易被畫成謊話，所以都寫在畫面上不寫在註解裡：

   一，沒有來源不是沒問題。三個軸現在是 NO_SOURCE，如果畫成灰色的
       中性狀態，讀起來就像「這三軸沒事」，而實情是這三軸答不出來。
   二，分母要跟分子一起印。「10 條換過模型」在 80 條裡跟在 354 條裡
       不是同一件事，只印 10 就是讓人自己補一個錯的分母。
   三，alias 沒人認領這件事本身就是結論，不是待辦清單。 */
function renderIdentity(d) {
  let box = document.querySelector(".idn");
  if (!box) {
    box = document.createElement("div");
    box.className = "idn";
    $("vitals").appendChild(box);
  }
  // 捲動位置要留住。跟 .sotList 同一個根因:每 1 到 3 秒整塊換 innerHTML。
  const oldList = box.querySelector(".idnList");
  const keepScroll = oldList ? oldList.scrollTop : 0;
  const t = d.identity;
  if (!t || !t.has) {
    box.innerHTML = `<p class="hd">身份跟什麼分得開` +
      `<span class="none">${esc((t && t.why)
        || "算不出來，不是身份沒問題")}</span></p>`;
    return;
  }
  const rows = t.rows || [];
  const items = rows.map((r) => {
    const zh = ID_ZH[r.state] || r.state;
    // null 不是 0。沒量的那一軸要自己講出來。
    const live = (r.live && r.live.value !== null
      && r.live.value !== undefined)
      ? `<p class="idnLive">量出來：${esc(String(r.live.value))}` +
        ` / ${esc(String(r.live.of))}</p>`
      : `<p class="idnNote">這一軸沒有數字可以量</p>`;
    return `<div class="idnRow">` +
      `<p class="idnHead"><span class="idnSt ${esc(r.state)}">${esc(zh)}` +
      `</span><span class="idnTy">身份 ≠ ${esc(r.axis)}` +
      `（${esc(r.axis_zh)}）</span></p>` +
      `<p class="idnQ">問的是：${esc(r.question)}</p>` +
      live +
      `<p class="idnEv">${esc(r.evidence)}</p>` +
      `</div>`;
  }).join("");

  const bs = t.by_state || {};
  const tail = ["SEPARABLE", "CONFLATED", "NO_SOURCE"]
    .filter((k) => bs[k]).map((k) => `${ID_ZH[k]} ${bs[k]}`).join("　");
  const un = t.unregistered_total
    ? `<p class="idnStale">帳本裡有 ${t.unregistered_total} 個 alias ` +
      `沒有任何持久身份認領</p>`
    : "";
  const st = t.stale_total
    ? `<p class="idnStale">登記裡有 ${t.stale_total} 個 alias ` +
      `帳本一次都沒出現過，那幾條不能再當證據</p>`
    : "";
  box.innerHTML =
    `<p class="hd">身份跟什麼分得開` +
    `<span class="sub">${t.total} 個軸${tail ? "　" + esc(tail) : ""}` +
    `</span></p>` +
    `<div class="idnList">${items}</div>` +
    `<p class="idnMore" hidden></p>` +
    `<p class="idnNote">登記 ${t.registered} 個持久身份，` +
    `帳本出現 ${t.actors_seen} 個 alias</p>` +
    un + st +
    (t.cache_note
      ? `<p class="idnCache">${esc(t.cache_note)}</p>` : "") +
    `<p class="idnNote">${esc(t.no_source_note || "")}</p>` +
    `<p class="idnNote">${esc(t.sampled_note || "")}</p>` +
    `<p class="idnNote">${esc(t.no_fuzzy_note || "")}</p>` +
    `<p class="idnNote">${esc(t.synthetic_note || "")}</p>` +
    `<p class="idnNote">出處 ${esc(t.source || "")}。</p>`;

  const list = box.querySelector(".idnList");
  if (list) {
    list.scrollTop = Math.min(keepScroll,
      Math.max(0, list.scrollHeight - list.clientHeight));
    const more = box.querySelector(".idnMore");
    if (more) {
      more.textContent = `這一格捲得動，${rows.length} 個軸不是全部都看得見`;
    }
    syncPlCut(list, ".idnMore");
    if (!box.dataset.scrollBound) {
      box.dataset.scrollBound = "1";
      box.addEventListener("scroll", (e) => {
        const l = e.target;
        if (l && l.classList && l.classList.contains("idnList")) {
          syncPlCut(l, ".idnMore");
        }
      }, true);
    }
  }
}

// §5 Workflow / WorkflowStep 加 §17.1 Workflow Reconstruction。
// 這一格回答的是:程序剛死掉，我現在接哪一步。
//
// 四條誠實條款在畫面上，不在註解裡:
//   一，commit_boundary 沒登記印「沒有人登記過」，不印「不跨邊界」。
//   二，缺的欄位直接列出來加原因，不只給一個覆蓋率數字。
//   三，規格 §6.2 那四種事件幾種有出現，直接寫。0 種就印 0 種。
//   四，dangling 單獨一格，不併進 blocked。
const WF_BD_ZH = {
  UNDECLARED: "沒有人登記過",
  NONE: "有人看過，不跨邊界",
  CROSSES: "會跨邊界",
  CROSSED: "已經跨過邊界",
};

function renderWorkflow(d) {
  let box = document.querySelector(".wfl");
  if (!box) {
    box = document.createElement("div");
    box.className = "wfl";
    $("vitals").appendChild(box);
  }
  // 捲動位置要留住。跟 .idnList / .sotList / .plList 同一個根因:
  // 每 1 到 3 秒整塊換 innerHTML，不留就會自己彈回頂端。
  const oldList = box.querySelector(".wflList");
  const keepScroll = oldList ? oldList.scrollTop : 0;
  const t = d.workflow;
  if (!t || !t.has) {
    box.innerHTML = `<p class="hd">接哪一步` +
      `<span class="none">${esc((t && t.why)
        || "算不出來，不是沒有待續的 workflow")}</span></p>`;
    return;
  }
  const rs = t.resumable || [];
  const items = rs.map((r) => {
    const c = r.counts || {};
    // ready 是 0 的時候不留白 —— 空白讀起來像還沒算，
    // 而實情是「這件的步驟都做完了，等的是收尾」。
    const ready = (r.ready_ids || []).length
      ? `<p class="wflReady">現在能做：${
          (r.ready_ids || []).map(esc).join("　")}</p>`
      : `<p class="wflNote">${c.done === c.total && c.total
          ? "步驟全部完成，等的是收尾" : "沒有現在能做的步驟"}</p>`;
    const blocked = (r.blocked_ids || []).length
      ? `<p class="wflBlocked">等依賴：${
          (r.blocked_ids || []).map(esc).join("　")}</p>`
      : "";
    const dang = c.dangling
      ? `<p class="wflBad">${c.dangling} 步的依賴指到不存在的 step，` +
        `那是資料壞了不是在等人</p>`
      : "";
    const bdZh = WF_BD_ZH[r.boundary] || r.boundary;
    return `<div class="wflRow">` +
      `<p class="wflHead"><span class="wflSt ${esc(r.state)}">` +
      `${esc(r.state)}</span><span class="wflId">${esc(r.workflow_id)}` +
      `</span></p>` +
      `<p class="wflObj">${esc(r.objective || "")}</p>` +
      `<p class="wflCnt">能做 ${c.ready || 0}　等依賴 ${c.blocked || 0}` +
      `　完成 ${c.done || 0} / ${c.total || 0}</p>` +
      ready + blocked + dang +
      `<p class="wflBd ${esc(r.boundary)}">不可逆邊界：${esc(bdZh)}</p>` +
      `</div>`;
  }).join("");

  const miss = (t.missing || []).map((m) =>
    `<p class="wflMiss"><span class="wflMs ${esc(m.state)}">` +
    `${esc(m.state === "NO_SOURCE" ? "沒有來源" : "有值但不是那個性質")}` +
    `</span>${esc(m.field)}　${esc(m.why)}</p>`).join("");

  const wc = t.wf_coverage || {}, sc = t.step_coverage || {};
  const ev = t.spec_events_present || 0;
  const evTotal = t.spec_events_total || 4;
  const top = (t.actual_top || []).map((x) =>
    `${x.kind} ${x.count}`).join("　");
  const und = (t.undeclared_live || []).length
    ? `<p class="wflNote">${(t.undeclared_live || []).length} 件在跑的` +
      `沒有人登記過不可逆邊界。那是一個待回答的問題，不是「不跨邊界」</p>`
    : "";

  box.innerHTML =
    `<p class="hd">接哪一步` +
    `<span class="sub">${t.live} 件在跑　共 ${t.total} 件</span></p>` +
    `<div class="wflList">${items || "<p class=\"wflNote\">" +
      "沒有在跑的 workflow</p>"}</div>` +
    `<p class="wflMore" hidden></p>` +
    `<p class="wflNote">規格那兩行十個欄位，` +
    `Workflow ${wc.present || 0} / ${wc.total || 5}、` +
    `WorkflowStep ${sc.present || 0} / ${sc.total || 5} 對得上。` +
    `兩個數字不合成一個，它們答的不是同一個問題</p>` +
    miss +
    `<p class="wflNote">規格 §6.2 那四種 Workflow 事件，` +
    `帳本裡 ${ev} / ${evTotal} 種有出現。` +
    `${ev === 0 ? "帳本用的是自己的命名（" + esc(top) +
      "），不做同義詞對映" : ""}</p>` +
    und +
    `<p class="wflNote">出處 ${esc(t.source || "")}。</p>`;

  const list = box.querySelector(".wflList");
  if (list) {
    list.scrollTop = Math.min(keepScroll,
      Math.max(0, list.scrollHeight - list.clientHeight));
    const more = box.querySelector(".wflMore");
    if (more) {
      more.textContent = `這一格捲得動，${rs.length} 件不是全部都看得見`;
    }
    syncPlCut(list, ".wflMore");
    if (!box.dataset.scrollBound) {
      box.dataset.scrollBound = "1";
      box.addEventListener("scroll", (e) => {
        const l = e.target;
        if (l && l.classList && l.classList.contains("wflList")) {
          syncPlCut(l, ".wflMore");
        }
      }, true);
    }
  }
}

const PRB_ZH = {
  PASS: "通過",
  REGRESSED: "退化了",
  NEW: "沒有基準線可比",
  NO_VERIFIER: "沒有東西可量",
};

/* §15 Probe Packs。這一格回答「換了東西之後，哪一類判準退化了」。

   四件事在這裡最容易被畫成謊話，所以都寫在畫面上不寫在註解裡：

   一，沒有東西可量不是通過。它們不進通過率的分母，畫面上也不跟
       PASS 用同一個顏色 —— 一張全綠的表會讓人以為十類都量過了。
   二，還沒有基準線的時候，十個 NEW 一樣沒有紅字。那句話要自己講，
       不能讓人從 NEW 自己推。
   三，基準線是誰按的、什麼時候按的要印出來。「跟基準線一致」
       這句話的分量完全取決於那條線多舊。
   四，跨不了的那兩軸每一次都要印。這一版量得到程式碼改動造成的
       退化，量不到換模型或改路由造成的退化。 */
function renderProbe(d) {
  let box = document.querySelector(".prb");
  if (!box) {
    box = document.createElement("div");
    box.className = "prb";
    $("vitals").appendChild(box);
  }
  // 捲動位置要留住。跟 .wflList / .idnList / .sotList 同一個根因：
  // 每 1 到 3 秒整塊換 innerHTML，不留就會自己彈回頂端。
  const oldList = box.querySelector(".prbList");
  const keepScroll = oldList ? oldList.scrollTop : 0;
  const t = d.probe;
  if (!t || !t.has) {
    box.innerHTML = `<p class="hd">哪一類退化了` +
      `<span class="none">${esc((t && t.why)
        || "算不出來，不是沒有哪一類退化")}</span></p>`;
    return;
  }
  const rows = t.rows || [];
  const items = rows.map((r) => {
    const zh = PRB_ZH[r.state] || r.state;
    const chg = (r.changed || []).length
      ? `<p class="prbChg">跟基準線不同的欄位：${
          (r.changed || []).map(esc).join("　")}</p>`
      : "";
    return `<div class="prbRow">` +
      `<p class="prbHead"><span class="prbSt ${esc(r.state)}">${esc(zh)}` +
      `</span><span class="prbId">${esc(r.id)}</span>` +
      `<span class="prbDm">${esc(r.domain)}　${esc(r.risk_class)}</span>` +
      `</p>` +
      `<p class="prbWhy">${esc(r.why || "")}</p>` + chg +
      `</div>`;
  }).join("");

  const c = t.counts || {};
  const nv = c.NO_VERIFIER || 0;
  const rate = (t.pass_rate === null || t.pass_rate === undefined)
    ? "算不出來"
    : `${Math.round(t.pass_rate * 100)}%`;
  // 沒有基準線的時候不准只印一排 NEW 就算了。
  const baseLine = t.has_baseline
    ? `<p class="prbNote">基準線是 ${esc(t.baseline_by || "沒有署名")}` +
      `${t.baseline_at ? "　" + esc(dayLabel(t.baseline_at)) : ""}` +
      ` 按下去的。它不會自己更新 —— 自動更新的基準線等於沒有基準線，` +
      `每一次退化都會在下一次變成新常態</p>`
    : `<p class="prbWarn">還沒有基準線，所以每一條都是「沒有基準線可比」，` +
      `不是通過。要有基準線才談得上退化</p>`;
  // 蓋不滿的時候，通過率那個數字的分母本來就少算了。
  const spec = t.spec_ok
    ? `<p class="prbNote">§15.2 的 ${t.spec_total} 類都在這一包裡</p>`
    : `<p class="prbWarn">§15.2 的 ${t.spec_total} 類少了 ${
        (t.spec_missing || []).map(esc).join("、")}。` +
      `少的那幾類不在分母裡，所以上面那個通過率偏高</p>`;

  box.innerHTML =
    `<p class="hd">哪一類退化了` +
    `<span class="sub">可量的 ${t.measurable} 個　通過率 ${esc(rate)}` +
    `</span></p>` +
    `<div class="prbList">${items}</div>` +
    `<p class="prbMore" hidden></p>` +
    `<p class="prbNote">通過 ${c.PASS || 0}　退化 ${c.REGRESSED || 0}` +
    `　沒有基準線可比 ${c.NEW || 0}</p>` +
    (nv
      ? `<p class="prbNv">另外 ${nv} 個沒有東西可量，` +
        `不算進通過率的分母。一個沒有東西可量的情境，跟一個量過而且` +
        `通過的情境，在一張綠色的表上長得一模一樣</p>`
      : "") +
    baseLine + spec +
    `<p class="prbNote">跨得了的軸：${(t.axes_covered || []).map(esc)
      .join("、")}；跨不了的：${(t.axes_missing || []).map(esc)
      .join("、")}。${esc(t.axes_why || "")}</p>` +
    `<p class="prbNote">出處 ${esc(t.source || "")}。</p>`;

  const list = box.querySelector(".prbList");
  if (list) {
    list.scrollTop = Math.min(keepScroll,
      Math.max(0, list.scrollHeight - list.clientHeight));
    const more = box.querySelector(".prbMore");
    if (more) {
      more.textContent = `這一格捲得動，${rows.length} 類不是全部都看得見`;
    }
    syncPlCut(list, ".prbMore");
    if (!box.dataset.scrollBound) {
      box.dataset.scrollBound = "1";
      box.addEventListener("scroll", (e) => {
        const l = e.target;
        if (l && l.classList && l.classList.contains("prbList")) {
          syncPlCut(l, ".prbMore");
        }
      }, true);
    }
  }
}

function renderHealthCurve(d) {
  let box = document.querySelector(".hcurve");
  if (!box) {
    box = document.createElement("div");
    box.className = "hcurve";
    // 放在 .dims 後面是為了讓 `.dims.open ~ .hcurve` 這條 CSS 成立 ——
    // 展開與收起只有一個開關(那個 open)，不要再長出第二套狀態。
    $("vitals").appendChild(box);
  }
  const c = d.health_curve;
  if (!c || !c.has || !(c.points || []).length) {
    box.innerHTML = `<p class="hd">可靠度曲線` +
      `<span class="none">${esc((c && c.why) || "沒有資料，不是沒問題")}</span></p>`;
    return;
  }
  const pts = c.points;
  const LO = 36.3;
  const HI = Math.max(38.0, Math.max(...pts.map((p) => p.t)) + 0.3);
  const W = 300, H = 62, PAD = 3;
  const x = (i) => PAD + (W - PAD * 2) * (pts.length < 2 ? 1 : i / (pts.length - 1));
  const y = (t) => PAD + (H - PAD * 2) * (1 - (t - LO) / (HI - LO));

  // band 分界線。分界值來自 vitals.temperature()，不在這裡另定一套。
  const marks = [[37.0, "var(--amber)"], [38.0, "var(--amber)"],
                 [39.0, "var(--red)"]].filter((m) => m[0] > LO && m[0] < HI);
  const grid = marks.map(([t, col]) =>
    `<line x1="${PAD}" y1="${y(t).toFixed(1)}" x2="${W - PAD}" y2="${
      y(t).toFixed(1)}" stroke="${col}" stroke-width=".5"
      stroke-dasharray="2 3" opacity=".35"/>`).join("");

  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${
    y(p.t).toFixed(1)}`).join("");
  const last = pts[pts.length - 1];
  const col = last.band === "CRITICAL" || last.band === "DEGRADED"
    ? "var(--red)" : last.band === "WATCH" ? "var(--amber)" : "var(--green)";

  // 最熱的那一點。標出來是因為「最壞的時候有多壞」跟「現在多少度」
  // 是兩個不同的問題，而後者常常把前者蓋掉。
  const hi = c.hottest || last;
  const hii = pts.findIndex((p) => p.i === hi.i);
  const dot = hii < 0 ? "" :
    `<circle cx="${x(hii).toFixed(1)}" cy="${y(hi.t).toFixed(1)}" r="2.4"
      fill="var(--red)" opacity=".8"/>`;

  // 退化起點。定義在 vitals._rising_since，一句話:
  // 從最後一點往回走，只要前一點不比後一點高就繼續。
  const rs = c.rising_since;
  const rsi = rs ? pts.findIndex((p) => p.i === rs.from.i) : -1;
  const rsl = rsi < 0 ? "" :
    `<line x1="${x(rsi).toFixed(1)}" y1="${PAD}" x2="${x(rsi).toFixed(1)}"
      y2="${H - PAD}" stroke="var(--ink-4)" stroke-width=".6"
      stroke-dasharray="1 3"/>`;

  const ex = (c.excluded || []).length;
  box.innerHTML =
    `<p class="hd">可靠度曲線` +
    `<span class="sub">第 ${esc(String(pts[0].n))} 到 ${
      esc(String(last.n))} 輪　${pts.length} 個取樣點</span></p>` +
    `<svg class="hcSvg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"
      role="img" aria-label="可靠度曲線">${grid}` +
    `<path d="${line}" fill="none" stroke="${col}" stroke-width="1.4"
      stroke-linejoin="round" stroke-linecap="round"/>${dot}${rsl}</svg>` +
    `<p class="hcFoot">` +
    (rs ? `最後一段從第 <b>${esc(String(rs.from.n))}</b> 輪起沒有降下來，` +
          `升了 <b>${rs.rise.toFixed(1)}</b> 度`
        : `最後一段沒有持續上升`) +
    `　最高 <b>${hi.t.toFixed(1)}</b> 度在第 ${esc(String(hi.n))} 輪` +
    `（${esc(hi.why || "")}）</p>` +
    `<p class="hcFoot dim">${ex} 個維度沒算進這條線` +
    `（${esc((c.excluded || []).map((k) => ({context: "脈絡",
      continuity: "連續性"})[k] || k).join("、"))}）：` +
    `它們的來源是現在這一刻的快照，不是那一輪的歷史</p>`;
}

/* 目標錨點閘門。FS-GOL-001:GAC 不夠不得輸出 CONFIRMED_DRIFT。
   單獨一塊，不混進八維度 —— 它不是維度，是一道閘門。§28.8 把工具失敗、
   沒動作、對話壓縮排除在三層之外是同一個理由:混進去會讓那幾格失真。 */
function renderGate(d) {
  let box = document.querySelector(".gate");
  if (!box) {
    box = document.createElement("div");
    box.className = "gate";
    $("vitals").appendChild(box);
  }
  const g = d.goal_gate;
  if (!g) {
    box.innerHTML = `<p class="hd">目標錨點` +
      `<span class="none">沒有資料，不是沒問題</span></p>`;
    return;
  }
  const gac = g.gac == null ? null : Number(g.gac);
  // 算不出來跟分數低是兩件事。前者沒有參考系，後者有但很弱。
  const head = gac == null
    ? `<span class="bad">算不出來</span>`
    : `<b>${gac.toFixed(2)}</b>`;
  const ceiling = g.may_confirm_drift
    ? `門檻過了，但 §6.2 另外四條未實作，仍只到 SUSPECTED`
    : `偏離最高只到 SUSPECTED`;

  const miss = (g.missing_factors || []).map((m) => m.factor);
  const gaps = ((g.factors || {}).provenance_integrity || {}).gaps || [];

  box.innerHTML =
    `<p class="hd">目標錨點　GAC ${head}` +
    (g.thresholds_uncalibrated ? `<span class="tag">門檻未校準</span>` : "") +
    `</p>` +
    `<p class="sub">${esc(ceiling)}</p>` +
    (miss.length
      ? `<p class="sub">算不出來是因為缺　<b>${esc(miss.join("、"))}</b></p>`
      : "") +
    (gaps.length
      ? `<p class="hd2">等你拍板 ${gaps.length} 件</p>` +
        `<ul>${gaps.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
      : "");
}

/* 三張卡片。bible.md I-04。
   點「用這句」把話放進剪貼簿 —— 她要做的事就只剩貼上去。 */
let cardsOpen = false;
/* 展開過的卡片。renderCards 每次 tick 會重建 innerHTML，
   不記住的話她點開的東西兩秒後就自己關上。 */
const cardsWhy = new Set();

function renderCards(d) {
  const box = $("cards");
  if (!box) return;
  const cs = d.cards || [];
  if (!cs.length) { box.innerHTML = ""; return; }
  const show = cardsOpen ? cs : cs.slice(0, 1);
  box.innerHTML = show.map((c, i) => `
    <div class="card2${i === 0 ? " hot" : ""}" data-k="${esc(c.key)}">
      <div class="t">${esc(c.title)}</div>
      ${c.say ? `<p class="say">${esc(c.say)}</p>` : ""}
      <div class="row">
        ${c.say ? '<button class="use" type="button">用這句</button>' : ""}
        <button class="why" type="button">為什麼是現在</button>
        ${c.n ? `<button class="goto2" type="button">看第 ${c.n} 輪</button>` : ""}
      </div>
      <ul class="five${cardsWhy.has(c.key) ? " open" : ""}">
        <li><span class="k">為什麼現在</span><span>${esc(c.why_now || "")}</span></li>
        <li><span class="k">證據</span><span>${esc(c.evidence || "")}</span></li>
        <li><span class="k">信心</span><span>${esc(c.confidence || "")}</span></li>
        <li><span class="k">不理會</span><span>${esc(c.if_ignored || "")}</span></li>
      </ul>
    </div>`).join("") +
    (cs.length > 1
      ? `<button class="more" type="button">${
          cardsOpen ? "收起" : `還有 ${cs.length - 1} 個建議`}</button>`
      : "");

  box.querySelectorAll(".card2").forEach((el, i) => {
    const k = el.dataset.k;
    el.querySelector(".why")?.addEventListener("click", () => {
      if (cardsWhy.has(k)) cardsWhy.delete(k); else cardsWhy.add(k);
      el.querySelector(".five").classList.toggle("open");
    });
    el.querySelector(".goto2")?.addEventListener("click", () => {
      view = "tree"; syncView(); jump(show[i].n);
    });
    el.querySelector(".use")?.addEventListener("click", async (e) => {
      const txt = show[i].say || "";
      try { await navigator.clipboard.writeText(txt); e.target.textContent = "複製好了"; }
      catch { e.target.textContent = "複製不了，請手動選取"; }
      setTimeout(() => { e.target.textContent = "用這句"; }, 1800);
    });
  });
  box.querySelector(".more")?.addEventListener("click", () => {
    cardsOpen = !cardsOpen;
    renderCards(lastSnap || d);
  });
}

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
    // 先前只活在自我審計那一頁的清單裡,而清單要人自己把
    // 「第幾段偏離」對回「那是什麼時候的事」,§5.1 說的就是這個
    // 對照動作,壓在線上就沒有它。
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

/* ── 功能自檢 §33 ─────────────────────────────
   每一項跑兩次:真實資料看現況，合成違規確認它會叫。 */

let featCache = null;

async function renderFeat() {
  const lane = $("lane");
  lane.textContent = "";
  if (!featCache) {
    lane.innerHTML = '<div class="fam plain"><div class="none">逐項驗證中</div></div>';
    try {
      featCache = JSON.parse(await invoke("features", {}));
    } catch (e) {
      lane.innerHTML =
        `<div class="fam"><div class="none">驗不了：${esc(String(e))}</div></div>`;
      return;
    }
    if (view !== "feat") return;
    lane.textContent = "";
  }
  const r = featCache;
  const bad = r.alive < r.total;
  const sc = r.scale || {};

  const head = document.createElement("div");
  head.className = "fHead";
  head.innerHTML =
    `<span class="fBig${bad ? " bad" : ""}">${r.alive}/${r.total}</span>` +
    '<span class="fSub">每一項都餵過一筆刻意造的違規，抓得到才算活的。' +
    '右邊的數字是這段對話的真實結果，不是測試資料</span>' +
    '<div class="fScale">' +
    `<span>模組 <b>${sc.modules || 0}</b></span>` +
    `<span>公開函式 <b>${sc.functions || 0}</b></span>` +
    `<span>Python <b>${(sc.lines || 0).toLocaleString()}</b> 行</span>` +
    `<span>JavaScript <b>${(sc.js_lines || 0).toLocaleString()}</b> 行</span>` +
    `<span>測試 <b>${sc.tests || 0}</b> 支</span></div>`;
  lane.appendChild(head);

  (r.items || []).forEach((x) => {
    const el = document.createElement("div");
    el.className = "fi" + (x.alive ? "" : " dead");
    el.innerHTML =
      '<div class="fiTop">' +
      `<span class="fiTag">${x.alive ? "活的" : "沒反應"}</span>` +
      `<span class="fiName">${esc(x.name)}</span>` +
      `<span class="fiLive">${x.live}</span></div>` +
      `<div class="fiWhat">${esc(x.what)}</div>` +
      `<div class="fiSpec">${esc(x.spec)}</div>`;
    lane.appendChild(el);
  });

  if ((r.not_wired || []).length) {
    const h = document.createElement("div");
    h.className = "fGap";
    h.textContent = "做好了但還沒接到畫面上";
    lane.appendChild(h);
    r.not_wired.forEach((g) => {
      const el = document.createElement("div");
      el.className = "gi";
      el.innerHTML =
        `<span class="n"><b>${esc(g.name)}</b>　${g.lines.toLocaleString()} 行</span>` +
        `<span class="w">${esc(g.why)}</span>`;
      lane.appendChild(el);
    });
  }
}

/* ── 自我審計 §39 ─────────────────────────────
   帳本裡的 SELF_FAULT 事件。append-only，刪不掉也改不了。 */

/* 根基。必讀文件沒讀完 = 這一整條線從第一格就是紅的。§40 */
let foundationBad = false;
/* ── 在做什麼 ─────────────────────────────────────
   【2026-09-15】這一頁先前是死的:`renderWork()` 被呼叫兩次，
   但整個專案裡沒有這個函式的定義,點下去直接 ReferenceError。
   Tauri 的 `work` command 早就寫好也註冊了，資料一路都通，
   缺的只有前端最後一哩。

   `gap.py` 抓不到這種缺口,因為它只比對函式名有沒有出現 ——
   而這裡的問題是「有人呼叫它，但它不存在」。 */
let workCache = null;

function wkEvent(e) {
  // HUMAN_CONTINUE 是「她必須開口說繼續」被記進帳本的樣子。
  // 那是這整套東西存在的理由，所以它不跟其他事件同色。
  const hot = e.kind === "HUMAN_CONTINUE";
  const warn = e.kind === "HANDOFF" || e.kind === "STOP";
  return `<li class="${hot ? "hot" : warn ? "warn" : ""}">` +
    `<span class="k">${esc(e.kind || "")}</span>` +
    `<span class="c">${esc(e.cause || "")}</span>` +
    `<span class="t">${e.at ? esc(hhmmss(e.at)) : ""}</span></li>`;
}

/* 動作按鈕。**按兩次才執行。**

   這些會真的改帳本，而帳本是 append-only —— 按錯了改不掉，
   只能再寫一筆事件蓋上去。所以第一次點只是把按鈕變成「確定？」，
   第二次才送出。五秒沒有第二次就自己退回去。

   這不是防呆裝飾:`finish` 會把任務標成 VERIFIED_COMPLETE，
   那是終局狀態，標錯了整條線的「還有幾件沒做」就從此說謊。 */
function wireActs(box) {
  if (!box) return;
  const task = box.dataset.task || "";
  const out = box.querySelector(".acOut");
  box.querySelectorAll(".ac").forEach((b) => {
    const label = b.textContent;
    let armed = false, timer = null;
    b.addEventListener("click", async () => {
      if (!armed) {
        armed = true;
        b.textContent = "再按一次確定";
        b.classList.add("armed");
        timer = setTimeout(() => {
          armed = false; b.textContent = label; b.classList.remove("armed");
        }, 5000);
        return;
      }
      clearTimeout(timer);
      armed = false; b.classList.remove("armed");
      b.textContent = "做中…";
      b.disabled = true;
      try {
        const r = JSON.parse(await invoke("act", {
          kind: b.dataset.kind, target: task, worker: "",
        }));
        // 做不動要講出卡在哪一個條件。安靜的沒反應正是這整套東西
        // 要消滅的東西（cmd_auto 的原註解）。
        out.textContent = r.ok ? (r.say || "done") : (r.why || "做不動");
        out.className = "acOut" + (r.ok ? " good" : " bad");
        if (r.ok) { workCache = null; setTimeout(() => renderWork(), 600); }
      } catch (e) {
        out.textContent = String(e);
        out.className = "acOut bad";
      }
      b.textContent = label;
      b.disabled = false;
    });
  });
}

/* 使用者正按到一半的時候，輪詢不要把這一頁抽掉。

   【2026-09-17 實測抓到的，症狀是三顆動作鈕完全按不動】
   `wireActs` 是兩段式的：第一下把鈕改成「再按一次確定」，
   第二下才真的送出。那個確認窗是 5 秒（`app.js` 同一支的 setTimeout）。
   而輪詢是這個檔案最底下那個 tick 的 setInterval，兩秒一輪，
   每一輪 `renderWork()` 第一行
   `lane.textContent = ""` 把整塊清掉重建 —— 重建出來的是新的節點、
   新的 closure，`armed` 就沒了。

   所以只要兩下之間跨過一次輪詢（也就是超過兩秒），第二下會被當成
   新的第一下，永遠送不出去。實測：兩下間隔 300 毫秒，指令清單裡
   有 `act`；間隔 2500 毫秒，指令清單裡一個 `act` 都沒有，
   而畫面上沒有任何錯誤訊息 —— 使用者看到的是「按了沒反應」。
   `wireActs` 自己的註解寫著「安靜的沒反應正是這整套東西要消滅的東西」。

   跟 `renderBlast` 那個搜尋框是同一種病（整塊 innerHTML 重畫沖掉
   使用者的狀態），只是那邊沖掉的是打到一半的字，這邊沖掉的是
   確認窗。那邊的修法是重畫前記下再放回去；這邊放不回去，因為
   剩餘的那幾秒算不出來，所以改成**這一輪不重畫**。

   最多凍結 5 秒，因為那個計時器到時一定會把 `armed` 還原。
   `disabled` 是送出中的那一段，同理。

   **只守輪詢那一條路，不守 `syncView`。** 換分頁是使用者自己的
   動作，那時候本來就該整頁重畫。 */
function workBusy() {
  return !!document.querySelector("#lane .ac.armed, #lane .ac:disabled");
}

async function renderWork() {
  const lane = $("lane");
  lane.textContent = "";
  if (!workCache) {
    lane.innerHTML = '<div class="fam plain"><div class="none">讀任務帳本</div></div>';
    try { workCache = JSON.parse(await invoke("work", {})); }
    catch (e) {
      lane.innerHTML =
        `<div class="fam"><div class="none">讀不到帳本：${esc(String(e))}</div></div>`;
      return;
    }
    if (view !== "work") return;
    lane.textContent = "";
  }
  const d = workCache;
  if (!d.ok) {
    lane.innerHTML = `<div class="fam"><div class="none">${esc(d.why || "沒有帳本")}</div></div>`;
    return;
  }

  const head = document.createElement("div");
  head.className = "aHead" + (d.total ? " redHead" : "");
  head.innerHTML = `<span class="${d.total ? "aBig" : "fBig"}">${d.total}</span>` +
    `<span class="aSub">件還沒做完　進行中 ${d.active}</span>`;
  lane.appendChild(head);

  (d.tasks || []).forEach((t) => {
    const c = t.continuity || {};
    const burden = c.burden ?? null;
    const score = c.score ?? null;
    const box = document.createElement("div");
    box.className = "wk";
    box.innerHTML =
      `<div class="wkTop"><span class="st">${esc(t.state || "")}</span>` +
      `<span class="id">${esc(t.id || "")}</span></div>` +
      `<p class="obj">${esc(t.objective || "")}</p>` +
      `<div class="mets">` +
        (score == null ? "" :
          `<span class="met${score < 0.2 ? " bad" : ""}">自動接續 ` +
          `<b>${Math.round(score * 100)}%</b></span>`) +
        (burden == null ? "" :
          `<span class="met${burden > 8 ? " bad" : ""}">你說了 ` +
          `<b>${burden}</b> 次繼續</span>`) +
        `<span class="met">事件 <b>${t.events_total ?? 0}</b></span>` +
      `</div>` +
      // 2026-09-16 19:0x：做完沒收尾不准染成琥珀色的「派不動」。
      // 正本兩件任務的步驟全部 VERIFIED_COMPLETE，畫面卻寫著
      // 「派不動　7 個步驟都不在可動狀態」，那是一句假話配一個警示色。
      // kind 由 stuck.diagnose 算，這裡不自己判斷。
      (t.next_step
        ? `<p class="nx">下一步　<b>${esc(t.next_step.objective || "")}</b></p>`
        : (t.stuck && t.stuck.kind === "ALL_VERIFIED")
          ? `<p class="nx fin">做完了　${esc(t.stuck_why || "")}</p>`
          : `<p class="nx stuck">派不動　${esc(t.stuck_why || "原因不明")}</p>`) +
      `<div class="acts" data-task="${esc(t.id || "")}">` +
        `<button class="ac" data-kind="finish" type="button">收尾</button>` +
        `<button class="ac" data-kind="dispatch" type="button">派下一步</button>` +
        `<button class="ac" data-kind="drain" type="button">一路派到底</button>` +
        `<span class="acOut"></span>` +
      `</div>` +
      ((t.events || []).length
        ? `<ul class="evs">${t.events.map(wkEvent).join("")}</ul>` : "");
    lane.appendChild(box);
    wireActs(box.querySelector(".acts"));
  });

  if ((d.active_rows || []).length) {
    const a = document.createElement("div");
    a.className = "wk";
    a.innerHTML = `<div class="wkTop"><span class="st">進行中</span>` +
      `<span class="id">最久沒動靜的排前面</span></div>` +
      `<ul class="evs">${d.active_rows.map((x) =>
        `<li><span class="k">${esc(x.state || "")}</span>` +
        `<span class="c">${esc(x.objective || "")}</span>` +
        `<span class="t">${esc(x.worker || "")}</span></li>`).join("")}</ul>`;
    lane.appendChild(a);
  }
}

let specCache = null;

async function loadFoundation() {
  try {
    const d = JSON.parse(await invoke("spec_reading", {}));
    foundationBad = d && d.has === true && d.ok === false;
    specCache = d;
  } catch (e) { /* 讀不到就不亂標紅，維持原狀 */ }
}

async function renderSpec() {
  const lane = $("lane");
  lane.textContent = "";
  if (!specCache) {
    lane.innerHTML = '<div class="fam plain"><div class="none">算必讀清單</div></div>';
    try { specCache = JSON.parse(await invoke("spec_reading", {})); }
    catch (e) {
      lane.innerHTML = `<div class="fam"><div class="none">算不出來：${esc(String(e))}</div></div>`;
      return;
    }
    if (view !== "spec") return;
    lane.textContent = "";
  }
  const d = specCache;
  if (!d.has) {
    lane.innerHTML = `<div class="fam"><div class="none">${esc(d.why || "")}</div></div>`;
    return;
  }
  const bad = d.partial + d.missing + d.stale;
  const head = document.createElement("div");
  head.className = "aHead" + (bad ? " redHead" : "");
  head.innerHTML =
    `<span class="${bad ? "aBig" : "fBig"}">${d.full} / ${d.total}</span>` +
    `<span class="aSub">${bad
      ? "必讀文件沒有全部讀完。照著沒讀完的規格做，做得再順也是錯的，" +
        "所以左邊每一條線都是紅的。這不是估的，沒有閱讀紀錄一律算沒讀。"
      : "必讀文件全部讀完，而且讀的版本跟現行檔案一致。"}</span>`;
  lane.appendChild(head);

  const ul = document.createElement("div");
  ul.className = "fam";
  ul.innerHTML = (d.rows || []).map((r) => {
    const ok = r.state === "讀完";
    return `<li class="${ok ? "" : "gone"}"><span class="dot"></span>` +
      `<span>${esc(r.name)}</span>` +
      `<span class="ct">${esc(r.state)}${
        r.state === "只讀一部分" ? "　" + Math.round(r.ratio * 100) + "%" : ""}</span></li>`;
  }).join("");
  lane.appendChild(ul);

  const box = document.createElement("div");
  box.className = "fam plain";
  box.innerHTML = '<div class="none">算區塊</div>';
  lane.appendChild(box);
  try {
    const b = JSON.parse(await invoke("block_reading", {}));
    if (view !== "spec") return;
    if (!b.has) { box.innerHTML = `<div class="none">${esc(b.why || "")}</div>`; return; }
    box.className = "fam";
    box.innerHTML =
      `<div class="famT">區塊閱讀　${b.done} / ${b.blocks} 塊讀完，` +
      `題庫 ${b.quiz} 題</div>` +
      (b.files || []).slice(0, 12).map((f) =>
        `<li><span class="dot"></span><span>${esc(f.name)}</span>` +
        `<span class="ct">${f.done}/${f.blocks} 塊　${f.quiz} 題</span></li>`).join("");
    const qs = b.questions || [];
    const qb = document.createElement("div");
    qb.className = "fam";
    qb.innerHTML = `<div class="famT">要你裁的問題　${qs.length} 條</div>` +
      (qs.length
        ? qs.map((q) => `<li><span class="dot"></span><span>${esc(q.q)}</span>` +
            `<span class="ct">${esc(q.file)}</span></li>`).join("")
        : '<div class="none">還沒有。讀過的區塊裡沒有寫下疑問</div>');
    lane.appendChild(qb);
  } catch (e) {
    box.innerHTML = `<div class="none">讀不到：${esc(String(e))}</div>`;
  }

  await renderTakeoverGate(lane);
}

// 接管閘門。v5.0 §17.3 / §19.2 / §39
//
// B-08 記的是「閘門攔不住寫程式的人，只列題目不驗答案」。
// 所以 REQUIRED_READING 那張七級量表上，任何文件最高只能到 level 5
// （我說我讀完了），到不了 level 6（有人考過我）。
//
// 這一塊顯示那道門現在的狀態。**沒考過就是唯讀**，不管它自己怎麼說。
async function renderTakeoverGate(lane) {
  const box = document.createElement("div");
  box.className = "fam plain";
  box.innerHTML = '<div class="none">算接管閘門</div>';
  lane.appendChild(box);
  let g;
  try { g = JSON.parse(await invoke("sufficiency", {})); }
  catch (e) {
    box.innerHTML = `<div class="none">讀不到：${esc(String(e))}</div>`;
    return;
  }
  if (view !== "spec") return;
  if (!g.has) { box.innerHTML = `<div class="none">${esc(g.why || "")}</div>`; return; }

  const ok = g.write === true;
  box.className = "fam" + (ok ? "" : " plain");
  box.innerHTML =
    `<div class="famT">接管閘門　${ok ? "這條線可以寫" : "這條線唯讀"}　` +
    `${esc(g.verdict || "還沒考")}</div>` +
    `<li><span class="dot"></span><span>${esc(g.why || "")}</span>` +
    `<span class="ct">考過 ${g.attempts} 次</span></li>` +
    g.dims.map((d) =>
      `<li class="${d.state === "OK" ? "" : "gone"}"><span class="dot"></span>` +
      `<span>${esc(d.zh)}（${esc(d.en)}）</span>` +
      `<span class="ct">${d.state === "OK"
        ? esc(d.source) + "　" + d.asked + " 題"
        : esc(d.state) + "：" + esc(d.why)}</span></li>`).join("") +
    `<li><span class="dot"></span><span>門檻 ${Math.round(g.threshold * 100)}%，` +
    `逐維度算，共 ${g.questions} 題</span>` +
    `<span class="ct">${g.enforced ? "會擋人" : "只記錄不擋"}</span></li>`;

  const how = document.createElement("div");
  how.className = "fam plain";
  how.innerHTML = '<div class="none">' +
    '出卷與交卷走 CLI：forseti gate takeover，答完 forseti gate submit。' +
    '題目從原文抽，答案不寫進考卷（§39 第 2 步：先看到答案再推導，' +
    '推導出來的就是那個答案）。</div>';
  lane.appendChild(how);
}

let auditCache = null;

async function renderAudit() {
  const lane = $("lane");
  lane.textContent = "";
  if (!auditCache) {
    lane.innerHTML = '<div class="fam plain"><div class="none">讀帳本</div></div>';
    try {
      auditCache = JSON.parse(await invoke("audit", {}));
    } catch (e) {
      lane.innerHTML =
        `<div class="fam"><div class="none">讀不到：${esc(String(e))}</div></div>`;
      return;
    }
    if (view !== "audit") return;
    lane.textContent = "";
  }
  const a = auditCache;
  if (!a.has) {
    lane.innerHTML = `<div class="fam"><div class="none">${esc(a.why || "")}</div></div>`;
    return;
  }

  const head = document.createElement("div");
  head.className = "aHead";
  head.innerHTML =
    `<span class="aBig">${a.count}</span>` +
    `<span class="aSub">這一輪 AI 自己造成的損害。帳本共 ${a.events} 筆事件，` +
    `其中 owner 必須開口說「繼續」的次數是 ${a.burden}。` +
    `${esc(a.note || "")}</span>`;
  lane.appendChild(head);

  (a.faults || []).forEach((f) => {
    const el = document.createElement("div");
    el.className = "af" + (f.severity === "critical" ? " crit" : "");
    el.innerHTML =
      (f.severity === "critical"
        ? '<div class="critTag">重大事故　owner 判定</div>' : "") +
      `<div class="afT">${esc(f.title)}</div>` +
      `<div class="afD">${esc(f.detail)}</div>` +
      `<div class="afH"><b>代價</b>　${esc(f.harm)}</div>`;
    lane.appendChild(el);
  });

  /* 沉默地圖。§39
     「我輸出之後她的反應是什麼」，包含她直接跳過不理我的那些段落。
     **MOVED_ON 不等於同意。** 那個模組自己帶 caveat:很大一部分底下
     是分類器的 UNKNOWN，量的是「分不出她在說什麼」而不是「她跳過了」。
     那個比例一定要跟數字一起顯示 —— 一個不講自己不確定度的指標，
     比沒有指標更危險。 */
  const sl = a.silence;
  if (sl && !sl.error) {
    const bk = sl.by_kind || {};
    const unk = Math.round((sl.moved_on_unknown_share || 0) * 100);
    const box = document.createElement("div");
    box.className = "wk";
    box.innerHTML =
      `<div class="wkTop"><span class="st">沉默地圖</span>` +
      `<span class="id">我輸出之後你的反應</span></div>` +
      `<div class="mets">` +
        `<span class="met">你回應 <b>${bk.RESPONDED || 0}</b></span>` +
        `<span class="met${(bk.MOVED_ON || 0) > (bk.RESPONDED || 0) ? " bad" : ""}">` +
        `你直接往下走 <b>${bk.MOVED_ON || 0}</b></span>` +
        `<span class="met">共 <b>${sl.total || 0}</b> 段</span>` +
      `</div>` +
      `<p class="nx">${esc(sl.note || "")}</p>` +
      (unk ? `<p class="nx stuck">不確定度　這裡面有 ${unk}% 底下是` +
             `分類器分不出你在說什麼，那部分量的不是「你跳過了」</p>` : "");
    lane.appendChild(box);
  }

  /* 修正延遲。白皮書 §5.4
     每一段偏離多久才被拉回來，以及**是誰拉的**。
     後者才是重點:她出手佔多數，就是「我變成你的工人」的量化版本。 */
  const lt = a.latency;
  if (lt && lt.has) {
    const box = document.createElement("div");
    box.className = "wk";
    const share = lt.owner_share == null ? null : Math.round(lt.owner_share * 100);
    box.innerHTML =
      `<div class="wkTop"><span class="st">誰把線拉回來</span>` +
      `<span class="id">${lt.count} 段偏離</span></div>` +
      `<div class="mets">` +
        `<span class="met${share && share >= 50 ? " bad" : ""}">你出手 ` +
        `<b>${lt.by_owner}</b> 段${share == null ? "" : `（${share}%）`}</span>` +
        `<span class="met">自己回來 <b>${lt.self_recovered}</b> 段</span>` +
        (lt.still_open ? `<span class="met bad">還開著 <b>${lt.still_open}</b> 段</span>` : "") +
        `<span class="met">中位數 <b>${lt.median_turns}</b> 輪</span>` +
      `</div>` +
      `<ul class="evs">${(lt.episodes || []).slice(-6).map((e) =>
        `<li class="${e.still_open ? "hot" : e.recovery === "OWNER_CORRECTION" ? "warn" : ""}">` +
        `<span class="k">${e.from_n}→${e.to_n}</span>` +
        `<span class="c">${esc(e.recovered_by || "還沒回來")}</span>` +
        `<span class="t">${e.turns} 輪 ${e.minutes}m</span></li>`).join("")}</ul>` +
      `<p class="nx stuck">${esc(lt.caveat || "")}</p>`;
    lane.appendChild(box);
  }

  /* 停在 commit 邊界前面的東西。§9.3
     準備跟提交是兩個權限等級。停在 PREPARED 不等於沒做，
     它是做到最後一步為止在等人按 —— 那個差別要看得見，
     不然人會以為它沒做，然後再做一次。 */
  const cm = a.commits;
  if (cm && (cm.pending || []).length) {
    const box = document.createElement("div");
    box.className = "wk";
    box.innerHTML =
      `<div class="wkTop"><span class="st">等你按</span>` +
      `<span class="id">做到最後一步，還沒跨過去</span></div>` +
      `<ul class="evs">${cm.pending.map((e) =>
        `<li class="${e.state === "AWAITING_APPROVAL" ? "hot" : ""}">` +
        `<span class="k">${esc(e.kind || "")}</span>` +
        `<span class="c">${esc(e.subject || "")}　${esc(e.state || "")}</span>` +
        `<span class="t">${esc(e.waiting_for || "")}</span></li>`).join("")}</ul>` +
      `<p class="nx">${esc(cm.note || "")}</p>`;
    lane.appendChild(box);
  }

  /* 權威衝突。§9.1
     同一個資源上有兩個來源說自己說了算。**平常不會報錯** ——
     兩邊各自都成功，然後結果不一致，而且沒有人知道從什麼時候開始。
     所以它只能靠主動列出來，不能等它自己浮現。 */
  const au = a.authority;
  if (au && (au.collisions || []).length) {
    const box = document.createElement("div");
    box.className = "wk";
    box.innerHTML =
      `<div class="wkTop"><span class="st">誰說了算</span>` +
      `<span class="id">同一個東西有兩個來源</span></div>` +
      `<ul class="evs">${au.collisions.map((c) =>
        `<li class="warn"><span class="k">${esc(c.winner)}</span>` +
        `<span class="c">${esc(c.resource)}　輸的是 ${esc((c.losers || []).join("、"))}</span>` +
        `<span class="t">${esc(c.winner_reason || "")}</span></li>`).join("")}</ul>` +
      `<p class="nx">${esc((au.collisions[0] || {}).why_it_matters || "")}</p>`;
    lane.appendChild(box);
  }

  /* 方向改變對上北極星換版。owner.goal_change_gap
     它刻意不自動換北極星 —— 換版是權威行為，自動換會讓
     authority 變成「系統」，那個欄位就失去意義了。
     所以這裡產生的是一個問題，不是一個動作。 */
  if (a.goal_gap && !a.goal_gap.error) {
    const g = a.goal_gap;
    const box = document.createElement("div");
    box.className = "wk";
    box.innerHTML =
      `<div class="wkTop"><span class="st">北極星</span>` +
      `<span class="id">方向改變對上換版次數</span></div>` +
      `<div class="mets">` +
        `<span class="met">你改變方向 <b>${g.goal_changes ?? 0}</b> 次</span>` +
        `<span class="met${g.needs_review ? " bad" : ""}">北極星換版 ` +
        `<b>${g.north_star_bumps ?? 0}</b> 次</span>` +
        `<span class="met">你發言 <b>${g.owner_messages ?? 0}</b> 則</span>` +
      `</div>` +
      `<p class="nx">${esc(g.note || "")}</p>` +
      (g.caveat ? `<p class="nx stuck">${esc(g.caveat)}</p>` : "");
    lane.appendChild(box);
  }
}

/* ── 這台機器 §31 ─────────────────────────────
   換機器該搬什麼、現在有幾個。
   2026-09-14 漏掉的是「工作目錄綁定」那 142 個檔，
   而那件事沒有任何東西主動說出來，是人一個個發現的。 */

let machCache = null;

async function renderMachine() {
  const lane = $("lane");
  lane.textContent = "";
  if (!machCache) {
    lane.innerHTML = '<div class="fam plain"><div class="none">掃描中</div></div>';
    try {
      machCache = JSON.parse(await invoke("machine", {}));
    } catch (e) {
      lane.innerHTML =
        `<div class="fam"><div class="none">掃不出來：${esc(String(e))}</div></div>`;
      return;
    }
    if (view !== "machine") return;
    lane.textContent = "";
  }
  const m = machCache;
  if (m.error) {
    lane.innerHTML = `<div class="fam"><div class="none">${esc(m.error)}</div></div>`;
    return;
  }

  const box = document.createElement("div");
  box.className = "mach";
  box.innerHTML =
    '<div class="machHead">' +
    `<span class="machHost">${esc(m.host || "")}</span>` +
    `<span class="machModel">${esc(m.model || "")}</span></div>`;
  (m.items || []).forEach((r) => {
    const el = document.createElement("div");
    el.className = "mi" + (r.ok ? "" : " gone");
    const rows = r.rows
      ? Object.entries(r.rows).map(([k, v]) => `${k} ${v}`).join("、") : "";
    el.innerHTML =
      '<span class="dot"></span>' +
      `<span class="nm">${esc(r.name)}` +
      (rows ? `<span class="sub">${esc(rows)}</span>` : "") +
      (r.ok ? "" : `<span class="sub">${esc(r.lose)}</span>`) +
      "</span>" +
      `<span class="ct">${r.count}</span>`;
    box.appendChild(el);
  });
  lane.appendChild(box);

  const note = document.createElement("div");
  note.className = "fam plain";
  note.innerHTML =
    '<div class="none">換機器的時候拿這串數字去對另一台，' +
    '少的那一項會自己跳出來。2026-09-14 漏掉的是「工作目錄綁定」，' +
    '少了它新機器只能走遠端連回舊機。</div>';
  lane.appendChild(note);
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
  $("subs").innerHTML = '<span class="none">量不到，不是沒問題</span>';
  $("subs").className = "subs empty";
  $("adviceText").textContent = title;
  $("adviceText").dataset.tone = "warn";
  $("adviceWhy").textContent = detail;
}

async function tick() {
  if (!invoke) {
    fatal("拿不到 Tauri",
      "window.__TAURI__ 不存在。tauri.conf.json 要設 app.withGlobalTauri = true，" +
      "否則前端呼叫不到後端，畫面會是空的。");
    return;
  }
  try {
    const raw = await invoke("strands", { session: picked });
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
    // 健康度 = 1 - 失敗點比例。成分疊加，不是合成分數。
    setAdvice(d);
    setContext(d);
    renderSubs(d);
    const grew = rows.length !== lastCount;
    lastCount = rows.length;
    lastSnap = d;
    renderVitals(d);
    renderCards(d);
    renderRescue(d);
    if (document.querySelector(".dims.open")) {
      renderDims(d); renderHealthCurve(d); renderBlast(d); renderGate(d);
      renderPollution(d); renderSot(d); renderIdentity(d);
      renderWorkflow(d); renderProbe(d);
    }
    if (view === "tree") renderTree();
    else if (view === "work") { if (!workBusy()) renderWork(); }
    else if (view === "machine") renderMachine();
    else if (view === "feat") renderFeat();
    else if (view === "audit") renderAudit();
    else if (view === "spec") renderSpec();
    else renderList();
    if (follow && view === "tree")
      $("scroll").scrollTop = $("scroll").scrollHeight;
    $("stat").textContent = `${d.strands} 線 · ${d.total_dots} 點`;
  } catch (e) {
    // 量不到要說出來，不是畫一個綠燈。
    fatal("讀不到 transcript", String(e).slice(0, 200));
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
  else if (view === "work") { workCache = null; renderWork(); }
  else if (view === "machine") { machCache = null; renderMachine(); }
  else if (view === "feat") { featCache = null; renderFeat(); }
  else if (view === "audit") { auditCache = null; renderAudit(); }
  else if (view === "spec") { specCache = null; renderSpec(); }
  else renderList();
}
/* 檢視在漢堡裡。§42
   owner 2026-09-14：「我們有討論過用一堆分頁來呈現嗎？
   我不懂你分頁做一堆，然後用戶要？」

   她手繪的介面只有一個入口:左上角那個漢堡。底部那排分頁是我自己
   長出來的,而且把「功能」「這台機器」「自我審計」這種後設資訊
   擺到跟主畫面同一層 —— 等於說這七件事一樣重要。只有線是主體。 */
$("vWhy")?.addEventListener("click", () => {
  const box = document.querySelector(".dims");
  const open = box && box.classList.contains("open");
  if (open) { box.classList.remove("open"); $("subs").hidden = true; return; }
  renderDims(lastSnap || {});
  renderHealthCurve(lastSnap || {});
  renderBlast(lastSnap || {});
  renderGate(lastSnap || {});
  renderPollution(lastSnap || {});
  renderSot(lastSnap || {});
  renderIdentity(lastSnap || {});
  renderWorkflow(lastSnap || {});
  renderProbe(lastSnap || {});
  document.querySelector(".dims")?.classList.add("open");
  $("subs").hidden = false;
});

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
