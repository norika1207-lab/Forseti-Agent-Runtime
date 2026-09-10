#!/usr/bin/env python3
"""一個頁面人打開看不看得懂。

存在的理由是 2026-09-10 的部署事故（bible Q-06）：三條 verifier 全過 ——
檔案在 VPS 上、HTTP 200、雜湊與本機逐位元組一致 —— 而瀏覽器打開是整頁亂碼。

三條驗的都是真的，沒有一條說謊。問題是沒有一條驗到「人打開看得懂」，
而那正是部署一個頁面的唯一理由。

**這支腳本要能放進 verifier**，所以它的回傳是 exit code：

    0  看得懂
    1  看不懂，理由印在 stdout
    2  拿不到內容（連不上、檔案不存在）

用法：

    check-page-readable.py <檔案路徑>
    check-page-readable.py <url>
    check-page-readable.py <url> --ssh sportverse        從 VPS 內抓
    check-page-readable.py <url> --expect "北極星"        指定字串要解得出來

`--ssh` 是必要的而不是方便：charenix.com 對本機 Mac 回 444（反爬主動關連線），
從本機抓到的 000 是假陰性。這一條寫在 CLAUDE.md 的交付規則第一條。

零依賴，標準庫而已（ADR-009）。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

# UTF-8 的中文被當成 latin-1 或 cp1252 解讀時會產生的典型序列。
# 這幾個不是隨便挑的：中文常用字的 UTF-8 位元組多落在
# 0xE4-0xE9 開頭，錯誤解讀之後就變成 ä å æ è é 加上第二第三位元組
# 的 Â  ‚ „ € 那一票。
#
# 2026-09-10 那次實際看到的開頭是「è®" AI çš„å·¥ä½œ」。
MOJIBAKE = re.compile(r"[ÃÂåäæèéç][-¿‘-„€™]")


def fetch(target: str, via_ssh: str | None) -> tuple[bytes, str]:
    """回傳 (內容, HTTP 宣告的 charset)。charset 拿不到就是空字串。"""
    if via_ssh:
        head = subprocess.run(
            ["ssh", via_ssh, "curl", "-sI", "--max-time", "20", target],
            capture_output=True, text=True, timeout=60)
        body = subprocess.run(
            ["ssh", via_ssh, "curl", "-s", "--max-time", "20", target],
            capture_output=True, timeout=60)
        m = re.search(r"content-type:.*?charset=([\w-]+)", head.stdout, re.I)
        return body.stdout, (m.group(1).lower() if m else "")

    p = Path(target).expanduser()
    if p.exists():
        return p.read_bytes(), ""

    if target.startswith(("http://", "https://")):
        with urlopen(target, timeout=20) as r:
            ct = r.headers.get("Content-Type", "")
            m = re.search(r"charset=([\w-]+)", ct, re.I)
            return r.read(), (m.group(1).lower() if m else "")

    raise FileNotFoundError(target)


def declared_in_html(raw: bytes) -> str:
    """HTML 自己宣告的 charset。

    只看前 2048 位元組 —— 那是瀏覽器的做法，meta charset 放在後面
    等於沒放，因為解析器早就開始用預設編碼了。
    """
    head = raw[:2048].decode("ascii", errors="replace")
    m = re.search(r'<meta[^>]+charset=["\']?([\w-]+)', head, re.I)
    return m.group(1).lower() if m else ""


def check(target: str, via_ssh: str | None = None,
          expect: list[str] | None = None) -> tuple[int, list[str]]:
    try:
        raw, http_charset = fetch(target, via_ssh)
    except Exception as e:  # noqa: BLE001 - 拿不到就是拿不到,理由要留著
        return 2, [f"拿不到內容：{e}"]

    if not raw:
        return 2, ["內容是空的"]

    notes = []
    html_charset = declared_in_html(raw)
    notes.append(f"HTTP 宣告　{http_charset or '（沒有）'}")
    notes.append(f"HTML 宣告　{html_charset or '（沒有）'}")

    if not http_charset and not html_charset:
        # 這正是 2026-09-10 那次的實際原因。兩邊都沒宣告的時候,
        # 瀏覽器的行為不確定 —— 而且 X-Content-Type-Options: nosniff
        # 還會讓它連猜都不能猜。
        notes.append("兩邊都沒有宣告編碼。瀏覽器只能猜，而它可能不准猜")
        return 1, notes

    enc = http_charset or html_charset
    try:
        text = raw.decode(enc, errors="strict")
    except (UnicodeDecodeError, LookupError) as e:
        notes.append(f"用宣告的 {enc} 解不開：{e}")
        return 1, notes

    hits = MOJIBAKE.findall(text)
    if len(hits) > 5:
        notes.append(f"解出來像亂碼：命中 {len(hits)} 個 mojibake 序列，"
                     f"例如 {''.join(hits[:6])!r}")
        return 1, notes

    non_ascii = sum(1 for c in text if ord(c) > 127)
    notes.append(f"非 ASCII 字元　{non_ascii:,} 個")

    for want in (expect or []):
        if want not in text:
            notes.append(f"找不到指定的字串：{want!r}")
            return 1, notes
        notes.append(f"找得到　{want!r}")

    return 0, notes


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    target = argv[1]
    via_ssh = None
    expect = []
    i = 2
    while i < len(argv):
        if argv[i] == "--ssh" and i + 1 < len(argv):
            via_ssh, i = argv[i + 1], i + 2
        elif argv[i] == "--expect" and i + 1 < len(argv):
            expect.append(argv[i + 1])
            i += 2
        else:
            i += 1

    code, notes = check(target, via_ssh, expect)
    print()
    print(f"  {target}")
    for n in notes:
        print(f"    {n}")
    print()
    print({0: "  看得懂。", 1: "  看不懂。", 2: "  拿不到。"}[code])
    print()
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
