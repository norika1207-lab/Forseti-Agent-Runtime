// 一次跑完全部模組的測試。任何一支非零退出就整體失敗。
import { execFileSync } from 'node:child_process';
const suites = ['cost', 'capsule', 'admission', 'coverage'];
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
