/**
 * hooks/event-ledger.mjs 的測試。
 *
 * 兩個重點，其他都是次要的：
 *
 *   一，canonical JSON 要與 Python 端逐位元組相同。對不上的話正本會有
 *   兩種寫法，指紋跟著分岔，而「重播兩次逐位元組相同」那條出口條件
 *   會在某一天安靜地失效。
 *
 *   二，任何失敗都不能 throw。2026-09-08 那次事故是 hook 把自己的問題
 *   變成使用者的問題，擋掉九小時工作。
 */

import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtempSync, readFileSync, existsSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  canonicalJson, payloadHash, classify, shrink, appendEvent,
} from '../hooks/event-ledger.mjs';

const box = () => mkdtempSync(join(tmpdir(), 'el-'));

test('canonical JSON 的三條規則', async (t) => {
  await t.test('欄位排序', () => {
    assert.equal(canonicalJson({ z: 1, a: 2 }), '{"a":2,"z":1}');
  });

  await t.test('非 ASCII 不跳脫', () => {
    // 跳脫的話 hash 會跟著跳脫序列走，而 Python 那邊用的是
    // ensure_ascii=False。這一條錯了兩邊的指紋就永遠對不上。
    assert.equal(canonicalJson({ a: '中文' }), '{"a":"中文"}');
  });

  await t.test('沒有多餘空白，巢狀也一樣', () => {
    assert.equal(
      canonicalJson({ b: [3, 1], a: { y: null, x: true } }),
      '{"a":{"x":true,"y":null},"b":[3,1]}',
    );
  });

  await t.test('與 Python 端對過的那個樣本', () => {
    // 這一串是 2026-09-10 實際拿去跟 event_ledger.canonical_json()
    // 比對過的輸出，逐位元組相同。改動 canonicalJson 之後這條會先斷。
    const sample = { z: 1, a: '中文', nested: { y: [3, 1], x: null }, b: 2.5, t: true };
    assert.equal(
      canonicalJson(sample),
      '{"a":"中文","b":2.5,"nested":{"x":null,"y":[3,1]},"t":true,"z":1}',
    );
  });

  await t.test('同樣的內容不同的建構順序，hash 相同', () => {
    assert.equal(payloadHash({ x: 1, y: 2 }), payloadHash({ y: 2, x: 1 }));
  });
});

test('hook event 對到 v5.0 §6.2 的 canonical type', async (t) => {
  const cases = [
    [{ hook_event_name: 'PreToolUse', tool_name: 'Write' }, 'TOOL_CALL'],
    [{ hook_event_name: 'PostToolUse', tool_name: 'Write' }, 'FILE_WRITE'],
    [{ hook_event_name: 'PostToolUse', tool_name: 'Edit' }, 'FILE_WRITE'],
    [{ hook_event_name: 'PostToolUse', tool_name: 'Read' }, 'FILE_READ'],
    [{ hook_event_name: 'PostToolUse', tool_name: 'Bash' }, 'TOOL_RESULT'],
    [{ hook_event_name: 'Stop' }, 'MODEL_OUTPUT'],
  ];
  for (const [input, want] of cases) {
    await t.test(`${input.hook_event_name}/${input.tool_name ?? '-'} → ${want}`, () => {
      assert.equal(classify(input), want);
    });
  }

  await t.test('不認得的事件回 null，不亂猜一個 type', () => {
    // 猜一個進去的話，正本裡會出現 Python 端拒收的 type，
    // 而那筆事件會在重建索引的時候才炸，離發生的時間點很遠。
    assert.equal(classify({ hook_event_name: 'SomethingNew' }), null);
    assert.equal(classify({}), null);
    assert.equal(classify(null), null);
  });
});

test('大 payload 外存，小的原樣留著', async (t) => {
  await t.test('只換超過門檻的那一欄', () => {
    const dir = box();
    const out = shrink({ file_path: '/a.txt', content: 'x'.repeat(70 * 1024) }, dir);
    assert.equal(out.file_path, '/a.txt', 'file_path 很小，要原樣留著');
    assert.equal(out.content._stashed, true);
    assert.equal(typeof out.content._sha256, 'string');
    assert.ok(out.content._bytes > 64 * 1024);
  });

  await t.test('外存的內容真的寫到磁碟，不是只留一個宣稱', () => {
    const dir = box();
    const out = shrink({ content: '中'.repeat(40 * 1024) }, dir);
    const f = join(dir, 'raw_payloads', `${out.content._sha256}.json`);
    assert.ok(existsSync(f), '參照指向的檔案要真的存在');
    assert.ok(readFileSync(f, 'utf8').includes('中'));
  });
});

test('任何失敗都不 throw，這條比功能重要', async (t) => {
  await t.test('目錄寫不進去也只是回 null', () => {
    // /proc 在 macOS 不存在、在 Linux 唯讀，兩邊都寫不進去。
    const id = appendEvent('/proc/forseti-should-not-exist',
      { hook_event_name: 'PostToolUse', tool_name: 'Write' }, {});
    assert.equal(id, null);
  });

  await t.test('input 是垃圾也不 throw', () => {
    const dir = box();
    for (const bad of [null, undefined, 42, 'string', [], { }]) {
      assert.doesNotThrow(() => appendEvent(dir, bad, {}));
    }
  });

  await t.test('循環參照不 throw', () => {
    const dir = box();
    const loop = { hook_event_name: 'PostToolUse', tool_name: 'Write', tool_input: {} };
    loop.tool_input.self = loop;
    assert.doesNotThrow(() => appendEvent(dir, loop, {}));
  });
});

test('寫出去的一行，結構要對得上 Python 端', () => {
  const dir = box();
  const id = appendEvent(dir, {
    hook_event_name: 'PostToolUse',
    tool_name: 'Write',
    tool_input: { file_path: '/tmp/中文.txt', content: '內容' },
    session_id: 's-1',
    cwd: '/repo',
  }, { projectId: 'Forseti' });

  assert.ok(id, '要回傳 raw event id');
  const line = readFileSync(join(dir, 'event_ledger.jsonl'), 'utf8').trim();
  const rec = JSON.parse(line);

  assert.equal(rec.raw.provider, 'claude-code', 'provider 是 Event Ledger 的分野');
  assert.equal(rec.raw.provider_event_type, 'PostToolUse');
  assert.equal(rec.norm.type, 'FILE_WRITE');
  assert.equal(rec.norm.raw_event_id, rec.raw.id, '回頭路不能斷');
  assert.equal(rec.norm.subject, '/tmp/中文.txt');
  assert.equal(rec.norm.provenance, 'OBSERVED');

  // 寫進去的那一行本身就要是 canonical 的。不是的話 Python 那邊
  // replay 出來的位元組會跟正本不同，而那正是出口條件在測的東西。
  assert.equal(line, canonicalJson(rec));
});

test('append 是 append，不覆蓋', () => {
  const dir = box();
  for (let i = 0; i < 3; i += 1) {
    appendEvent(dir, {
      hook_event_name: 'PostToolUse', tool_name: 'Write',
      tool_input: { file_path: `/f${i}` }, session_id: 's',
    }, {});
  }
  const lines = readFileSync(join(dir, 'event_ledger.jsonl'), 'utf8')
    .trim().split('\n');
  assert.equal(lines.length, 3);
  assert.equal(readdirSync(dir).includes('event_ledger.jsonl'), true);
});

test('Evidence Receipt 跟它所屬的事件在同一筆', async (t) => {
  await t.test('evidence 進 metadata，大小進 result', () => {
    const dir = box();
    appendEvent(dir, {
      hook_event_name: 'PostToolUse', tool_name: 'Write',
      tool_input: { file_path: '/x.txt' }, session_id: 's',
    }, {
      evidence: {
        observedAt: 1, resourceLocator: '/x.txt', existence: true,
        byteSize: 42, contentHash: 'deadbeef', captureMethod: 'PostToolUse:Write',
        exitCode: null,
      },
    });
    const rec = JSON.parse(readFileSync(join(dir, 'event_ledger.jsonl'), 'utf8').trim());
    assert.equal(rec.norm.metadata.evidence.byteSize, 42);
    assert.equal(rec.norm.metadata.evidence.contentHash, 'deadbeef');
    assert.equal(rec.norm.result, '42 bytes');
  });

  await t.test('existence 是三態，unknown 不會變成 false', () => {
    // 這個區別是 src/evidence.js 拒絕接受其他值的原因：
    // 「量不到」跟「不存在」是兩件事。混在一起的話，一個因為權限讀不到的
    // 檔案會被當成「AI 說做了但沒做」，而那是冤枉它。
    const dir = box();
    appendEvent(dir, {
      hook_event_name: 'PostToolUse', tool_name: 'Write',
      tool_input: { file_path: '/nope' }, session_id: 's',
    }, {
      evidence: {
        observedAt: 1, resourceLocator: '/nope', existence: 'unknown',
        byteSize: null, contentHash: null, captureMethod: 'PostToolUse:Write',
        exitCode: null,
      },
    });
    const rec = JSON.parse(readFileSync(join(dir, 'event_ledger.jsonl'), 'utf8').trim());
    assert.equal(rec.norm.metadata.evidence.existence, 'unknown');
    assert.notEqual(rec.norm.metadata.evidence.existence, false);
    assert.equal(rec.norm.result, 'UNKNOWN');
  });

  await t.test('沒有 evidence 的事件，metadata 是空物件不是塞 null', () => {
    // 塞一個 evidence: null 進去的話，下游要分辨「沒量」與「量到空的」
    // 就得看兩層。空物件讓「這一筆沒有證據」只有一種形狀。
    const dir = box();
    appendEvent(dir, { hook_event_name: 'PreToolUse', tool_name: 'Write' }, {});
    const rec = JSON.parse(readFileSync(join(dir, 'event_ledger.jsonl'), 'utf8').trim());
    assert.deepEqual(rec.norm.metadata, {});
    assert.equal(rec.norm.result, '');
  });
});
