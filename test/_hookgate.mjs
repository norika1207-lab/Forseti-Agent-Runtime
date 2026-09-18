/**
 * hook 裡「擋人之前有沒有問過閘門」的唯一判準。
 *
 * ## 為什麼要抽出來
 *
 * 2026-09-18 審計時發現同一個判準有兩份:`hooks.e2e.test.mjs` 的
 * AT-HOOK-R3 與 `spec-v0.1.test.mjs` 第 9 條。兩份的視窗大小、
 * 認得的閘門種類都不一樣,於是同一個檔案在一邊是 FAIL、
 * 在另一邊是 VIOLATES,而修好一邊另一邊照樣紅。
 *
 * 兩份會分歧的判斷遲早會分歧,而分歧那天不會有錯誤訊息。
 *
 * ## 它守的事故
 *
 * 2026-09-08:三個 `process.exit(2)` 一個都沒有問過 `intervention.js`,
 * 擁有者的夜間工作被擋了九個小時。
 *
 * ## 閘門有兩種,兩種都算
 *
 * 一,`intervention.js` 的裁決(`gate()` / `g.allowed`)。
 *    預設路徑:硬前提不明的時候才准擋。
 *
 * 二,owner 明確覆寫。她在信任階層第一級(v2.0 §3.3),
 *    2026-09-16 原話「我現在要你開啟 Forseti 全自動介入你的工作,
 *    強制介入」。覆寫走 `.forseti/config.json` 不走改程式碼,
 *    而且有次數上限 —— 讓位要留下痕跡。
 *
 * 第二種的判準刻意要三件事同時在:`if (!enforce)` 這個提早出口、
 * 它後面的 `process.exit(0)`、以及次數上限 `cap`。只找 `enforce`
 * 這個字不夠 —— 把那個 if 整段拿掉之後那個字還在別的地方,
 * 判準會放行一個無條件擋人的 exit(2)。這一點是實測驗過的:
 * 拿掉那一段,這支回報違規;還原,不回報。
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/** 掃描的檔案。三個 hook 裡只有這兩個會 exit(2)。 */
export const HOOK_FILES = ['forseti-hook.mjs', 'forseti-stop-hook.mjs'];

/** 往上看幾行。要蓋得住 owner 覆寫那條路的提早出口到 exit(2) 的距離。 */
const WINDOW = 30;

function stripComments(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
    .replace(/^([^\n]*?)\/\/[^\n]*$/gm, (m, keep) => keep);
}

/**
 * 回傳沒問過閘門的 exit(2) 清單:`[{ file, line }]`。
 * 空陣列代表全部都問過。
 *
 * @param {string} hooksDir hooks 目錄的絕對路徑
 */
export function ungatedExits(hooksDir) {
  const bad = [];
  for (const f of HOOK_FILES) {
    const lines = stripComments(readFileSync(join(hooksDir, f), 'utf8')).split('\n');
    lines.forEach((line, i) => {
      if (!/process\.exit\(2\)/.test(line)) return;
      const before = lines.slice(Math.max(0, i - WINDOW), i).join('\n');
      const gated = /g\.allowed|gate\(/.test(before);
      const ownerOverride =
        /if\s*\(!enforce\)/.test(before)
        && /process\.exit\(0\)/.test(before)
        && /\bcap\b/.test(before);
      if (!gated && !ownerOverride) bad.push({ file: f, line: i + 1 });
    });
  }
  return bad;
}

/** 給 assert 用的一句話。沒有違規回空字串。 */
export function ungatedExitsWhy(hooksDir) {
  const bad = ungatedExits(hooksDir);
  if (!bad.length) return '';
  return bad.map((b) => `${b.file}:${b.line}`).join('、')
    + ' 有沒問過閘門的 exit(2)。這正是擋掉擁有者一整晚的那種寫法。';
}
