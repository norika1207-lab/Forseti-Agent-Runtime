// 一次跑完全部模組的測試。任何一支非零退出就整體失敗。
import { execFileSync } from 'node:child_process';
// capture 排最前面:它是其他五個的資料入口,它壞了後面全部的答案都不算數。
// integration 排最後:前面每支只證明零件自己對,那支證明它們接得起來。
const suites = ['capture', 'cost', 'capsule', 'admission', 'coverage', 'handoff', 'persist', 'integration'];
let bad = 0;
for (const s of suites) {
  console.log(`\n──── ${s} ────`);
  try {
    process.stdout.write(execFileSync(process.execPath, [new URL(`./${s}.test.mjs`, import.meta.url).pathname], { encoding: 'utf8' }));
  } catch (e) {
    process.stdout.write(e.stdout ?? '');
    bad++;
  }
}
console.log(bad ? `\n${bad} 個模組有失敗` : '\n全部模組通過');
process.exit(bad ? 1 : 0);
