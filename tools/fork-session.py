#!/usr/bin/env python3
"""從對話中間某一輪 fork 出一個新 session。CLI 入口。

核心搬到 `apps/forseti-cli/forkline.py` 了 —— Widget 也要用，
而判斷邏輯只能有一份。這裡只剩命令列介面。

用法：

    python3 tools/fork-session.py <session-uuid> --at-line <行號>
    python3 tools/fork-session.py <session-uuid> --at-line 8818 --dry-run
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

from forkline import fork, resolve  # noqa: E402

def main(argv: list[str]) -> int:
    if len(argv) < 2 or "--at-line" not in argv:
        print(__doc__.strip().split("用法：")[-1])
        return 2
    src = resolve(argv[1])
    at = int(argv[argv.index("--at-line") + 1])
    dry = "--dry-run" in argv

    info = fork(src, at, dry_run=dry)
    print()
    print(f"  來源　{Path(info['source']).name}")
    print(f"  切點　第 {info['at_line']} 行（{info['target_type']}）")
    print()
    print(f"  留下　{info['kept']:,} 筆對話 + {info['headers']} 筆 header")
    print(f"  丟掉　{info['dropped']:,} 筆（切點之後的）")
    print()
    if dry:
        print("  --dry-run，沒有寫任何檔案")
    else:
        print(f"  新 session　{info['new_session_id']}")
        print(f"  寫到　{info['dest']}")
        print()
        print(f"    claude --resume {info['new_session_id']}")
    print()
    print("  原檔一個位元組都沒有動。")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
