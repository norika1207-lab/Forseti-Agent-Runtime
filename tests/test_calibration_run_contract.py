from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import calibration_run_contract as C  # noqa: E402


MAPPING = {code: True for code in C.SYMPTOMS}


def run(**overrides):
    value = {
        "run_id": "r1", "state": "VERIFIED", "corpus_id": "corpus-a",
        "model_id": "model-a", "context_id": "ctx-a",
        "observed_label": "POSITIVE", "owner_label": "NEGATIVE",
        "symptom_codes": ["EVIDENCE_INFLATION"],
        "evidence_refs": ["receipt:1"],
    }
    value.update(overrides)
    return value


def test_verified_owner_labeled_run_can_be_fp():
    result = C.build([run()], symptom_mapping=MAPPING)
    assert result["runs"][0]["classification"] == "FP"
    assert result["summary"] == {
        "total": 1, "verified": 1, "unknown": 0, "fp": 1, "fn": 0}


def test_planned_or_run_state_never_invents_fp_fn():
    for state in ("PLANNED", "RUN"):
        row = C.build([run(state=state)], symptom_mapping=MAPPING)["runs"][0]
        assert row["classification"] == C.UNKNOWN
        assert row["fp"] is None and row["fn"] is None


def test_missing_identity_evidence_owner_label_or_mapping_is_unknown():
    cases = [
        run(model_id=None), run(evidence_refs=[]), run(owner_label=None),
        run(symptom_codes=["OWNER_UNDEFINED"]),
    ]
    for case in cases:
        row = C.build([case], symptom_mapping=MAPPING)["runs"][0]
        assert row["state"] == C.UNKNOWN
        assert row["classification"] == C.UNKNOWN


def test_bool_and_numeric_identity_aliases_fail_closed():
    for key in ("run_id", "corpus_id", "model_id", "context_id"):
        for value in (True, 1):
            row = C.build([run(**{key: value})], symptom_mapping=MAPPING)["runs"][0]
            assert row["state"] == C.UNKNOWN


def test_unhashable_state_and_labels_fail_closed_without_exception():
    for key in ("state", "observed_label", "owner_label"):
        for value in ([], {}):
            row = C.build([run(**{key: value})], symptom_mapping=MAPPING)["runs"][0]
            assert row["state"] == C.UNKNOWN
            assert row["classification"] == C.UNKNOWN
            assert row["fp"] is None and row["fn"] is None


def test_duplicate_run_id_is_unknown():
    result = C.build([run(model_id="a"), run(model_id="b")],
                     symptom_mapping=MAPPING)
    assert result["summary"]["unknown"] == 2
    assert all(row["why"] == "duplicate run_id" for row in result["runs"])


def test_contract_is_deterministic_under_input_and_mapping_order():
    rows = [run(run_id="b"), run(run_id="a", observed_label="NEGATIVE",
                                  owner_label="POSITIVE")]
    left = C.build(rows, symptom_mapping=MAPPING)
    right = C.build(list(reversed(rows)),
                    symptom_mapping=dict(reversed(list(MAPPING.items()))))
    assert C.canonical_json(left) == C.canonical_json(right)
    assert json.loads(C.canonical_json(left))["contract_digest"]


def test_non_list_runs_are_empty_not_fabricated():
    result = C.build({"run_id": "r1"}, symptom_mapping=MAPPING)
    assert result["summary"]["total"] == 0
    assert result["runs"] == []
