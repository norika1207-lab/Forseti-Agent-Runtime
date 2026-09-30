#!/usr/bin/env python3
"""Deterministic, fail-closed model/context calibration contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


VERSION = "forseti.calibration-run@1"
UNKNOWN = "UNKNOWN"
STATES = {"PLANNED", "RUN", "VERIFIED"}
LABELS = {"POSITIVE", "NEGATIVE"}
SYMPTOMS = {
    "GOAL_DRIFT", "EVIDENCE_INFLATION", "EXECUTION_GAP",
    "CONTEXT_LOSS", "RECOVERY_FAILURE",
}


def _text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _refs(value: Any) -> list[str] | None:
    if not isinstance(value, (list, tuple)):
        return None
    refs = [_text(item) for item in value]
    if not refs or any(item is None for item in refs):
        return None
    return sorted(set(refs))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _unknown(run_id: str | None, why: str) -> dict[str, Any]:
    return {"run_id": run_id, "state": UNKNOWN, "classification": UNKNOWN,
            "fp": None, "fn": None, "symptoms": [], "why": why}


def normalize_run(raw: Any, symptom_mapping: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return _unknown(None, "run must be an object")
    run_id = _text(raw.get("run_id"))
    state = _text(raw.get("state"))
    required = {
        "run_id": run_id,
        "corpus_id": _text(raw.get("corpus_id")),
        "model_id": _text(raw.get("model_id")),
        "context_id": _text(raw.get("context_id")),
    }
    if state not in STATES or any(value is None for value in required.values()):
        return _unknown(run_id, "state or exact corpus/model/context identity missing")

    evidence = _refs(raw.get("evidence_refs"))
    observed = _text(raw.get("observed_label"))
    owner = _text(raw.get("owner_label"))
    if state != "VERIFIED":
        return {**required, "state": state, "classification": UNKNOWN,
                "fp": None, "fn": None, "symptoms": [],
                "evidence_refs": evidence or [],
                "why": "only VERIFIED runs with owner labels are classifiable"}
    if evidence is None or observed not in LABELS or owner not in LABELS:
        return {**required, "state": UNKNOWN, "classification": UNKNOWN,
                "fp": None, "fn": None, "symptoms": [],
                "evidence_refs": evidence or [],
                "why": "verified run lacks evidence or exact observed/owner label"}

    mapping = symptom_mapping if isinstance(symptom_mapping, Mapping) else {}
    requested = raw.get("symptom_codes")
    if not isinstance(requested, (list, tuple)):
        symptoms = []
        mapping_complete = False
    else:
        symptoms = sorted({_text(item) for item in requested
                           if _text(item) in SYMPTOMS})
        mapping_complete = bool(requested) and len(symptoms) == len(requested)
        mapping_complete = mapping_complete and all(
            mapping.get(code) is True for code in symptoms)
    classification = "TP" if observed == owner == "POSITIVE" else (
        "TN" if observed == owner == "NEGATIVE" else
        "FP" if observed == "POSITIVE" else "FN")
    if not mapping_complete:
        return {**required, "state": UNKNOWN, "classification": UNKNOWN,
                "fp": None, "fn": None, "symptoms": symptoms,
                "evidence_refs": evidence,
                "why": "owner-approved five-symptom mapping incomplete"}
    return {**required, "state": "VERIFIED", "classification": classification,
            "fp": classification == "FP", "fn": classification == "FN",
            "symptoms": symptoms, "evidence_refs": evidence,
            "why": "owner label and evidence permit classification"}


def build(runs: Any, *, symptom_mapping: Mapping[str, Any] | None = None) -> dict[str, Any]:
    rows = list(runs) if isinstance(runs, (list, tuple)) else []
    normalized = [normalize_run(row, symptom_mapping) for row in rows]
    normalized.sort(key=lambda row: (
        row.get("run_id") or "", _canonical(row)))
    duplicate_ids = sorted({row["run_id"] for row in normalized
                            if row.get("run_id") and
                            sum(other.get("run_id") == row["run_id"]
                                for other in normalized) > 1})
    if duplicate_ids:
        for row in normalized:
            if row.get("run_id") in duplicate_ids:
                row.update(state=UNKNOWN, classification=UNKNOWN,
                           fp=None, fn=None, why="duplicate run_id")
    body = {"version": VERSION, "runs": normalized,
            "summary": {
                "total": len(normalized),
                "verified": sum(row["state"] == "VERIFIED" for row in normalized),
                "unknown": sum(row["state"] == UNKNOWN for row in normalized),
                "fp": sum(row["fp"] is True for row in normalized),
                "fn": sum(row["fn"] is True for row in normalized),
            }}
    body["contract_digest"] = hashlib.sha256(
        _canonical(body).encode("utf-8")).hexdigest()
    return body


def canonical_json(contract: Mapping[str, Any]) -> str:
    return _canonical(contract)
