// 一次跑完全部模組的測試。任何一支非零退出就整體失敗。
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
// capture 排最前面:它是其他五個的資料入口,它壞了後面全部的答案都不算數。
// integration 排倒數第二:前面每支只證明零件自己對,那支證明它們接得起來。
// spec-v0.1 真正排最後:前面每一支測的都是我自己定的驗收,
// 那支測的是擁有者寫的規格書。用自己的尺量自己,量出來永遠會及格。
// hooks.e2e 是唯一一支開真程序、看 exit code 的:
// 前面全部加起來都不能證明裝上去之後它會開口。Stop hook 就是
// 單元測試全過、實際裝上去一次都不會擋的活例子。
// v2 那五支排在 v1 模組之後、integration 之前:它們是 §26 的 P0..P6,
// 是後面 P7+ 的地基,地基自己先過了,上面的整合測試才有意義。
const suites = ['conformance', 'signals', 'yield', 'windows', 'rescue', 'followthrough', 'scope', 'baseline', 'overhead', 'rhetoric', 'intervention', 'artifact', 'capture', 'shell', 'adapter-claude-code', 'imports', 'cost', 'capsule', 'admission', 'coverage', 'handoff', 'persist', 'drift', 'provenance', 'heartbeat', 'thermometer', 'evidence', 'verifier', 'claims', 'goalanchor', 'progress', 'runtime', 'integration', 'acceptance', 'hooks.e2e', 'install', 'spec-v0.1'];
let bad = 0;
for (const s of suites) {
  console.log(`\n──── ${s} ────`);
  try {
    process.stdout.write(execFileSync(process.execPath, [fileURLToPath(new URL(`./${s}.test.mjs`, import.meta.url))], { encoding: 'utf8' }));
  } catch (e) {
    process.stdout.write(e.stdout ?? '');
    bad++;
  }
}
console.log(bad ? `\n${bad} 個模組有失敗` : '\n全部模組通過');
process.exit(bad ? 1 : 0);
