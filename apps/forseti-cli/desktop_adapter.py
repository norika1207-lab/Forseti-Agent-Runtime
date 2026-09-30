#!/usr/bin/env python3
"""Event-driven desktop host adapter for durable Forseti continuation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import ledger
from recovery_contract import continuation_key


class DesktopAdapter:
    def __init__(self, *, db: Path, cwd: Path, step_id: str, target: str):
        self.ledger = ledger.Ledger(db=db, cwd=cwd)
        self.step_id = step_id
        self.target = target

    def close(self) -> None:
        self.ledger.close()

    def _event(self, kind: str, payload: dict, key: str) -> None:
        task_id = self.ledger._task_of_step(self.step_id)
        self.ledger._event(kind, kind, actor="desktop-adapter", task_id=task_id,
                           step_id=self.step_id, payload=payload, idem_key=key)

    def _authorized_packet(self) -> dict:
        row = self.ledger.con.execute(
            "SELECT task_id,next_action FROM steps WHERE step_id=?", (self.step_id,)
        ).fetchone()
        if not row:
            return {"action": "FAIL_CLOSED", "reason": "UNKNOWN_STEP"}
        task_id, text = row
        text = (text or "").strip()
        if not text:
            return {"action": "FAIL_CLOSED", "reason": "NO_AUTHORIZED_NEXT_ACTION"}
        return {"task_id": task_id, "step_id": self.step_id,
                "original_input": text,
                "event_key": continuation_key(task_id, self.step_id, text)}

    def observe(self, event: dict) -> dict:
        if event.get("accessibility") is not True:
            return {"action": "FAIL_CLOSED", "reason": "NO_ACCESSIBILITY"}
        if event.get("target") != self.target:
            return {"action": "FAIL_CLOSED", "reason": "TARGET_MISMATCH"}
        state = str(event.get("state", "")).upper()
        if state not in {"ACTIVE", "IDLE"}:
            return {"action": "FAIL_CLOSED", "reason": "UNKNOWN_AX_STATE"}
        observation_id = str(event.get("observation_id", ""))
        if not observation_id:
            return {"action": "FAIL_CLOSED", "reason": "MISSING_OBSERVATION_ID"}

        self._event("AX_STATE", {"target": self.target, "state": state,
                                  "observation_id": observation_id},
                    f"ax:{self.step_id}:{observation_id}")
        prior_row = self.ledger.con.execute(
            "SELECT payload FROM events WHERE step_id=? AND kind='AX_STATE' "
            "ORDER BY event_id DESC LIMIT 1 OFFSET 1", (self.step_id,)).fetchone()
        prior = None
        if prior_row and prior_row[0]:
            try:
                prior = json.loads(prior_row[0]).get("state")
            except (TypeError, ValueError):
                prior = None
        if state == "ACTIVE":
            return {"action": "OBSERVED_ACTIVE", "target": self.target}
        if prior != "ACTIVE":
            return {"action": "FAIL_CLOSED", "reason": "IDLE_WITHOUT_ACTIVE"}

        packet = self._authorized_packet()
        if packet.get("action"):
            return packet
        decision = self.ledger.continue_if_stalled(
            self.step_id, authorized_input=packet["original_input"],
            command_running=False, activity_observed=False, stall_suspect=True)
        decision["target"] = self.target
        return decision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--step", required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    adapter = DesktopAdapter(db=args.db, cwd=args.cwd,
                             step_id=args.step, target=args.target)
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                result = adapter.observe(json.loads(line))
            except (TypeError, ValueError, KeyError) as exc:
                result = {"action": "FAIL_CLOSED", "reason": f"INVALID_EVENT:{exc}"}
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
