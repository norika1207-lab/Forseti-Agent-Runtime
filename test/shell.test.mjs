// shell 命令的檔案操作解析。
// 這個模組的每一條規則都來自真實資料:接上 130 份真實記錄之前，
// 採集率是 19.6%，因為 shell 這條路完全看不見。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { filesFromCommand as f, expandBashEvent } from '../src/shell.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

// ---- 重定向 ----
t('覆寫重定向算寫入', () => assert.deepEqual([...f('echo hi > out.txt').writes], ['out.txt']));
t('附加重定向算寫入', () => assert.deepEqual([...f('echo hi >> notes.md').writes], ['notes.md']));
t('輸入重定向算讀取', () => assert.deepEqual([...f('node app.js < input.json').reads], ['input.json']));
t('一條命令多個目標都抓得到', () => {
  const r = f('cat a.md b.md > merged.md');
  assert.deepEqual([...r.reads], ['a.md', 'b.md']);
  assert.deepEqual([...r.writes], ['merged.md']);
});

// ---- heredoc:餵 cat 跟餵直譯器是兩件事 ----
t('heredoc 餵給 cat:寫入抓得到,不算不透明', () => {
  const r = f("cat > src/x.js <<'EOF'");
  assert.deepEqual([...r.writes], ['src/x.js']);
  assert.equal(r.opaque, false, 'heredoc 只是 stdin,寫入目標已經明確');
});

t('heredoc 餵給直譯器:標成不透明,因為檔名在程式碼裡不在命令列', () => {
  const r = f("python3 - <<'PY'");
  assert.equal(r.opaque, true);
  assert.ok(r.opaque_reasons.includes('HEREDOC_TO_INTERPRETER'));
});

t('這正是這份程式碼自己被寫出來的方式,所以必須看得見這個盲點', () => {
  // 實際用過的形狀:python 在 heredoc 裡 open(p,'w'),命令列上沒有那個檔名
  const r = f("python3 - <<'PY'\nopen('src/admission.js','w').write(s)\nPY");
  assert.equal(r.opaque, true);
});

// ---- 檔案命令 ----
t('cp 第一個是來源,最後一個是目的地', () => {
  const r = f('cp a.js b.js');
  assert.deepEqual([...r.reads], ['a.js']);
  assert.deepEqual([...r.writes], ['b.js']);
});

t('mv 同理', () => {
  const r = f('mv old.js new.js');
  assert.deepEqual([...r.writes], ['new.js']);
});

t('rm 算寫入,那是破壞性的', () =>
  assert.deepEqual([...f('rm -rf build/x.js').writes], ['build/x.js']));

t('tee 的參數是寫入目標', () =>
  assert.deepEqual([...f('tee out.log').writes], ['out.log']));

t('cat 是讀取', () => assert.deepEqual([...f('cat README.md').reads], ['README.md']));

t('sed -i 是寫入,而且表達式不是檔案', () => {
  const r = f('sed -i s/x/y/ config.json');
  assert.deepEqual([...r.writes], ['config.json'], 's/x/y/ 含斜線但不是路徑');
  assert.deepEqual([...r.reads], []);
});

t('sed -n 只是讀', () => {
  const r = f('sed -n 1,20p src/a.js');
  assert.deepEqual([...r.reads], ['src/a.js']);
  assert.deepEqual([...r.writes], []);
});

// ---- 真實資料抓到的誤判 ----
t('裝置不是檔案:/dev/null 不算,否則會製造假撞車', () => {
  const r = f('node app.js 2> /dev/null');
  assert.deepEqual([...r.writes], []);
});

t('/proc 與 /sys 同理', () => {
  assert.deepEqual([...f('cat /proc/cpuinfo').reads], []);
  assert.deepEqual([...f('cat /sys/class/net/eth0/address').reads], []);
});

t('萬用字元不猜,展開結果這裡看不到', () =>
  assert.deepEqual([...f('rm build/*.js').writes], []));

// ---- 不透明 ----
t('變數展開:看不出實際路徑', () => {
  const r = f('cp "$SRC" "$DST"');
  assert.equal(r.opaque, true);
  assert.ok(r.opaque_reasons.includes('VARIABLE_EXPANSION'));
});

t('命令替換:看不出實際路徑', () =>
  assert.ok(f('cat $(ls -t | head -1)').opaque_reasons.includes('COMMAND_SUBSTITUTION')));

t('執行程式:它可能動了任何東西', () => {
  assert.ok(f('npm test').opaque_reasons.includes('RUNS_A_PROGRAM'));
  assert.ok(f('./deploy.sh').opaque_reasons.includes('RUNS_A_SCRIPT'));
});

t('xargs 與 find -exec 都不猜', () => {
  assert.ok(f('find . -name "*.tmp" | xargs rm').opaque);
  assert.ok(f('find . -name "*.tmp" -exec rm {} ;').opaque);
});

t('不透明時明確的重定向照收,但整條仍標不透明', () => {
  const r = f('./build.sh > build.log');
  assert.deepEqual([...r.writes], ['build.log']);
  assert.equal(r.opaque, true, '重定向抓到了,但腳本裡還動了什麼不知道');
});

t('永遠是下界,這個旗標不可關閉', () => {
  assert.equal(f('cat a.js').is_lower_bound, true);
  assert.equal(f('').is_lower_bound, true);
});

t('回傳凍結', () => {
  const r = f('cat a.js');
  assert.throws(() => { r.reads.push('x'); }, TypeError);
});

t('空命令與非字串不炸', () => {
  assert.deepEqual([...f('').reads], []);
  assert.deepEqual([...f(null).writes], []);
});

// ---- 展開成事件 ----
t('一筆 Bash 呼叫展成多筆檔案事件', () => {
  const out = expandBashEvent({
    attributed_agent: 'w1', at: 1000,
    name: 'Bash', input: { command: 'cp a.js b.js' },
  });
  assert.equal(out.events.length, 2);
  assert.deepEqual(out.events.map((e) => e.name).sort(), ['Read', 'Write']);
  assert.equal(out.events[0].attributed_agent, 'w1', '身分歸屬要跟著過去');
  assert.equal(out.events[0].at, 1000);
});

t('不透明的命令會被計數,不是靜默略過', () => {
  assert.equal(expandBashEvent({ name: 'Bash', input: { command: 'npm test' } }).opaque_commands, 1);
  assert.equal(expandBashEvent({ name: 'Bash', input: { command: 'cat a.js' } }).opaque_commands, 0);
});

t('沒有命令字串時回空,不猜', () =>
  assert.equal(expandBashEvent({ name: 'Bash', input: {} }).events.length, 0));

// ---- 邊界 ----
t('零依賴：shell.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/shell.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('19.6% 那個真實數字寫在原始碼裡,不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/shell.js', import.meta.url), 'utf8');
  assert.ok(/19\.6%/.test(src), '這個模組存在的理由是一個實測數字');
  assert.ok(/圖靈完備/.test(src), '為什麼永遠只能是下界,必須寫明');
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
