#!/usr/bin/env python3
"""
把一份 artifact 自白書存進案例庫。

    python3 tools/save-case.py <本地HTML> <artifact-url> <標題> <輸出檔名>

為什麼要存:這些是 Forseti 每一個偵測器的來源。四個形狀、十個訊號、
飄移的定義,全部從這些文件萃取。而在 2026-09-08 之前,repo 裡一份都沒有,
只剩形狀的名字跟我當時的轉述。擁有者問「這麼重要的東西你忘了沒有存」,
答案是對。

規格書第 34 條:模型自白是有用的研究材料,但不能當唯一 ground truth,
校準標籤要區分可觀測事實、人的判定、模型自述。這裡存的全部是第三類,
檔頭會標明,不准當成前兩類用。
"""
import sys, re, html, hashlib, datetime, os

src, url, title, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
raw = open(src, encoding='utf-8', errors='replace').read()
digest = hashlib.sha256(raw.encode('utf-8', 'replace')).hexdigest()

s = re.sub(r'<script[\s\S]*?</script>', ' ', raw)
s = re.sub(r'<style[\s\S]*?</style>', ' ', s)
s = re.sub(r'<br\s*/?>', '\n', s)
s = re.sub(r'</(p|div|li|h[1-6]|tr|section|article|td|th)>', '\n', s)
s = re.sub(r'<[^>]+>', ' ', s)
t = html.unescape(s)
t = re.sub(r'[ \t]+', ' ', t)
t = re.sub(r'\n[ \t]+', '\n', t)
t = re.sub(r'\n\s*\n\s*\n+', '\n\n', t).strip()

head = f"""---
來源: {url}
標題: {title}
撈取時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
原始 HTML SHA256: {digest}
證據等級: MODEL_SELF_REPORT
---

> 這是模型自述，不是可觀測事實，也不是人的判定。
>
> 規格書 §9 寫著 historical self-confessions are useful research material
> but MUST NOT be treated as sole ground truth，校準標籤必須區分
> observable event facts、human adjudication、model self-report 三類。
> 這份屬於第三類。拿它當校準資料時，證據等級不可以升級。
>
> 純文字由原始 HTML 轉出，只移除了 script、style 與標記，沒有改寫、
> 沒有摘要、沒有補充。原始檔的 SHA256 記在上面，可以比對。

"""
os.makedirs(os.path.dirname(out), exist_ok=True)
open(out, 'w', encoding='utf-8').write(head + t + '\n')
print(f'  {out}  {len(t)} 字  sha256 {digest[:16]}')
