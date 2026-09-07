/**
 * Forseti：從 shell 命令裡找出檔案操作
 *
 * 這個模組的存在理由，是拿真實資料跑出來的。
 *
 * 第一次把採集層接到真實的 session 記錄上，採集率只有 19.6%。
 * 985 筆工具呼叫裡 792 筆被跳過，原因全是「這個工具沒有 file_path」，
 * 而那 792 筆裡 754 筆是 Bash。也就是說,採集層看不見
 * 「用 shell 改檔案」這條路 —— 那恰好是這份程式碼自己被寫出來的方式。
 *
 * 沒有這一層，下游會給出一個看起來乾淨的錯答案:
 * 「零次撞車」不是因為沒撞車,是因為八成的寫入根本沒被看見。
 *
 * ── 這裡永遠只給下界,而且說得出為什麼 ──────────────────
 *
 * shell 是圖靈完備的,靜態看命令字串不可能知道它動了哪些檔案。
 * 三種情況一定看不到:
 *
 *   直譯器吃 heredoc     python3 - <<'PY' ... open(p,'w') ... PY
 *                        檔名在 Python 程式碼裡,命令列上沒有這個字
 *   變數展開             cp "$SRC" "$DST"
 *   執行腳本             ./deploy.sh、make、npm run build
 *
 * 這三種不會被猜,會被標成 opaque。opaque 的命令代表
 * 「這裡動了不知道哪些檔案」,那是一個有用的事實,
 * 遠比一份看起來完整的假清單有用。
 */

/** 讀取類命令。 */
const READ_CMDS = /^(cat|head|tail|less|more|wc|md5|shasum|sha256sum|file|stat|diff|grep|rg|jq)$/;
/** 寫入類命令,第一個非選項參數就是目標。 */
const WRITE_FIRST = /^(touch|truncate)$/;
/** 讀第一個、寫第二個。 */
const READ_THEN_WRITE = /^(cp|mv|ln|install|rsync)$/;
/** 破壞性,算寫入。 */
const DESTRUCTIVE = /^(rm|unlink|shred)$/;

/**
 * 命令內容不透明的訊號。命中任一就不再猜這條命令動了什麼。
 *
 * 順序有意義:先判斷不透明,再解析。一條命令既有明確重定向
 * 又餵 heredoc 給直譯器時,重定向照收,但整條仍標成 opaque,
 * 因為直譯器那半段可能寫了任何東西。
 */
const OPAQUE_PATTERNS = Object.freeze([
  { re: /(^|[\s|;&])(python3?|node|ruby|perl|bash|sh|zsh|osascript)\b[^|;&]*<<-?\s*['"]?\w+/, reason: 'HEREDOC_TO_INTERPRETER' },
  { re: /\$\{?\w+\}?/, reason: 'VARIABLE_EXPANSION' },
  { re: /\$\(|`/, reason: 'COMMAND_SUBSTITUTION' },
  { re: /(^|[\s|;&])(bash|sh|zsh|python3?|node|ruby|perl|make|npm|pnpm|yarn|cargo|go)\s/, reason: 'RUNS_A_PROGRAM' },
  { re: /(^|[\s|;&])\.\/\S+/, reason: 'RUNS_A_SCRIPT' },
  { re: /\bxargs\b/, reason: 'XARGS' },
  { re: /-exec\b/, reason: 'FIND_EXEC' },
]);

/**
 * 不是檔案的路徑。跑真實資料時抓到的:/dev/null 被當成一般檔案,
 * 於是「兩個執行者在 3.5 秒內同時寫 /dev/null」被判成撞車五次。
 * 那是雜訊,而且是會讓人不再相信告警的那種雜訊。
 */
const NOT_A_FILE = /^\/(dev|proc|sys)\//;

/**
 * 已知的檔案副檔名。不含斜線的字串必須是這裡面的才算路徑。
 *
 * 為什麼要這張清單:原本的判斷是「結尾像副檔名就算」,
 * 結果 JS 的屬性存取全部中招 —— a.at、r.k、rows.length 都被當成檔案,
 * 然後進了覆蓋範圍、進了可疑窗口、污染下游每一個數字。
 * 那是在真實 session 上跑可疑窗口選取時才看到的。
 */
const KNOWN_EXT = /\.(js|mjs|cjs|ts|tsx|jsx|json|md|txt|log|sh|bash|zsh|py|rb|go|rs|c|h|cpp|hpp|java|kt|swift|m|mm|html|htm|css|scss|yml|yaml|toml|ini|cfg|conf|xml|sql|csv|tsv|lock|gradle|plist|env|gguf|bin|img|apk|ipa|zip|tar|gz|pdf|png|jpg|jpeg|svg|ico)$/i;

/** 看起來像檔案路徑的東西。不含萬用字元,因為展開結果這裡看不到。 */
function looksLikePath(tok) {
  if (!tok || tok.startsWith('-')) return false;
  if (/[*?]/.test(tok)) return false;
  if (/^[|;&<>]+$/.test(tok)) return false;
  if (NOT_A_FILE.test(tok)) return false;
  // 含斜線的當路徑;不含斜線的必須帶已知副檔名,
  // 否則 a.at 這種屬性存取會被當成檔案。
  return tok.includes('/') || KNOWN_EXT.test(tok);
}

function stripQuotes(s) {
  if (s.length >= 2 && ((s[0] === '"' && s.at(-1) === '"') || (s[0] === "'" && s.at(-1) === "'"))) {
    return s.slice(1, -1);
  }
  return s;
}

/**
 * 極簡 tokenizer:認引號,不做展開。
 * 不是完整的 shell 剖析器,也不打算是 —— 完整剖析需要一個 shell,
 * 而有了 shell 就等於執行它,那不是靜態分析該做的事。
 */
function tokenize(cmd) {
  const out = [];
  let cur = '';
  let quote = null;
  for (let i = 0; i < cmd.length; i += 1) {
    const c = cmd[i];
    if (quote) {
      if (c === quote) { quote = null; cur += c; } else cur += c;
      continue;
    }
    if (c === '"' || c === "'") { quote = c; cur += c; continue; }
    if (/\s/.test(c)) { if (cur) { out.push(cur); cur = ''; } continue; }
    if (c === '|' || c === ';' || c === '&') {
      if (cur) { out.push(cur); cur = ''; }
      out.push(c);
      continue;
    }
    if (c === '>' || c === '<') {
      if (cur && !/^\d+$/.test(cur)) { out.push(cur); cur = ''; } else cur = '';
      let op = c;
      if (cmd[i + 1] === c) { op += c; i += 1; }
      out.push(op);
      continue;
    }
    cur += c;
  }
  if (cur) out.push(cur);
  return out;
}

/**
 * 從一條 shell 命令找出它讀了什麼、寫了什麼。
 *
 * @returns {{reads:string[], writes:string[], opaque:boolean, opaque_reasons:string[], is_lower_bound:true}}
 *   opaque 為 true 時,reads/writes 仍可能有內容(明確的重定向),
 *   但一定不完整。呼叫端必須把 opaque 當成「這裡還動了不知道什麼」。
 */
export function filesFromCommand(cmd) {
  const text = String(cmd ?? '');
  const reasons = [];
  for (const { re, reason } of OPAQUE_PATTERNS) {
    if (re.test(text)) reasons.push(reason);
  }

  const reads = new Set();
  const writes = new Set();
  const toks = tokenize(text);

  let head = null;          // 目前這一段的命令名
  let expectAfter = null;   // 上一個 token 是重定向或 cp/mv 之類,下一個 token 是目標
  let positional = 0;

  for (let i = 0; i < toks.length; i += 1) {
    const raw = toks[i];
    const tok = stripQuotes(raw);

    if (tok === '|' || tok === ';' || tok === '&' || tok === '&&' || tok === '||') {
      head = null; expectAfter = null; positional = 0;
      continue;
    }

    if (raw === '>' || raw === '>>') { expectAfter = 'write'; continue; }
    if (raw === '<') { expectAfter = 'read'; continue; }

    if (expectAfter) {
      if (looksLikePath(tok)) (expectAfter === 'write' ? writes : reads).add(tok);
      expectAfter = null;
      continue;
    }

    if (head === null) {
      head = tok.split('/').at(-1);
      // tee 的參數都是寫入目標
      continue;
    }

    if (tok.startsWith('-')) continue;
    positional += 1;

    if (head === 'tee') { if (looksLikePath(tok)) writes.add(tok); continue; }
    if (READ_CMDS.test(head)) { if (looksLikePath(tok)) reads.add(tok); continue; }
    if (WRITE_FIRST.test(head) || DESTRUCTIVE.test(head)) { if (looksLikePath(tok)) writes.add(tok); continue; }
    if (READ_THEN_WRITE.test(head)) {
      if (!looksLikePath(tok)) continue;
      // 最後一個位置參數是目的地,前面的都是來源。這裡看不到「最後一個」是誰,
      // 所以先全記成 read,收尾時把最末一個搬去 write。
      reads.add(tok);
      continue;
    }
    // sed 的第一個位置參數是表達式(s/x/y/ 這種,含斜線但不是路徑),從第二個起才是檔案
    if (head === 'sed') {
      if (positional > 1 && looksLikePath(tok)) {
        (/(^|\s)-i\b/.test(text) ? writes : reads).add(tok);
      }
      continue;
    }
  }

  // cp/mv/ln:把最後一個來源改判成目的地
  if (READ_THEN_WRITE.test(String(toks[0] ?? '').split('/').at(-1)) && reads.size >= 2) {
    const list = [...reads];
    const dest = list.at(-1);
    reads.delete(dest);
    writes.add(dest);
  }

  return Object.freeze({
    reads: Object.freeze([...reads].sort()),
    writes: Object.freeze([...writes].sort()),
    opaque: reasons.length > 0,
    opaque_reasons: Object.freeze([...new Set(reasons)]),
    /** shell 靜態分析永遠是下界。這個旗標不可關閉。 */
    is_lower_bound: true,
  });
}

/**
 * 給 capture.js 用的 adapter 擴充:把一筆 Bash 工具呼叫展成零到多筆事件。
 *
 * 傳給 normalizeStream 之前先跑這個,原本會因為沒有 file_path
 * 而整筆被跳過的 Bash 呼叫,就能貢獻它看得出來的部分。
 *
 * opaque 的命令會額外產生一筆標記事件(file_path 為 null),
 * 讓宿主知道「這裡有一段看不透的檔案操作」。
 * 那筆不進中性事件流,只出現在回傳的 opaque_commands 裡。
 *
 * @returns {{events:Array, opaque_commands:number}}
 */
export function expandBashEvent(raw, { commandField = 'command' } = {}) {
  const input = raw?.input ?? raw?.tool_input ?? raw?.params ?? {};
  const cmd = input[commandField];
  if (typeof cmd !== 'string') return Object.freeze({ events: Object.freeze([]), opaque_commands: 0 });

  const found = filesFromCommand(cmd);
  const base = { ...raw };
  delete base.input;
  delete base.tool_input;
  delete base.params;

  const events = [];
  for (const f of found.reads) {
    events.push({ ...base, name: 'Read', input: { file_path: f } });
  }
  for (const f of found.writes) {
    events.push({ ...base, name: 'Write', input: { file_path: f } });
  }
  return Object.freeze({
    events: Object.freeze(events),
    opaque_commands: found.opaque ? 1 : 0,
  });
}
