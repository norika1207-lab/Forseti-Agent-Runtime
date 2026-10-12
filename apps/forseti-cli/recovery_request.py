#!/usr/bin/env python3
"""Read a bounded pre-compaction original-text window on explicit user request."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from provider_recovery import recover_provider_interval


def recover_request(*, home: Path, source_path: str, provider: str,
                    ordinal: int, round_number: int, expected_line: int) -> dict:
    unknown = lambda reason: {"status": "UNKNOWN", "reason": reason,
                              "packet": None, "auto_inject": False}
    roots = {"codex": home / ".codex/sessions",
             "claude": home / ".claude/projects"}
    if (provider not in roots or type(ordinal) is not int or ordinal < 1
            or type(round_number) is not int or round_number < 1
            or type(expected_line) is not int or expected_line < 1):
        return unknown("invalid_request")
    path = Path(source_path)
    root = roots[provider]
    try:
        if (not path.is_absolute() or path.suffix != ".jsonl"
                or path.is_symlink() or not path.is_file()
                or not path.resolve(strict=True).is_relative_to(root.resolve(strict=True))):
            return unknown("invalid_source")
    except OSError:
        return unknown("invalid_source")

    # Keep the on-screen packet bounded. If the nearest three rounds exceed the
    # packet budget, narrow explicitly; never present a truncated range as whole.
    last = None
    for start in range(max(1, round_number - 2), round_number + 1):
        result = recover_provider_interval(
            source_path=str(path), provider=provider, start_round=start,
            compaction_ordinal=ordinal, goal="未提供；請參照原始對話",
            task="檢視壓縮前原文")
        if result["status"] == "READY":
            if result["compaction_source_ref"] != f"{path.resolve()}:{expected_line}":
                return unknown("compaction_anchor_changed")
            if result.get("recovered_end_round") != round_number:
                return unknown("compaction_round_changed")
            result["recovered_start_round"] = start
            result["requested_end_round"] = round_number
            result["window_limited"] = start > max(1, round_number - 2)
            return result
        last = result
        if result["reason"] not in {"capacity_overflow", "cross_compaction_boundary",
                                    "missing_source_round"}:
            break
    return last or unknown("missing_source_round")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--ordinal", required=True, type=int)
    parser.add_argument("--round", required=True, type=int)
    parser.add_argument("--line", required=True, type=int)
    args = parser.parse_args()
    result = recover_request(home=Path.home(), source_path=args.source,
                             provider=args.provider, ordinal=args.ordinal,
                             round_number=args.round, expected_line=args.line)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
