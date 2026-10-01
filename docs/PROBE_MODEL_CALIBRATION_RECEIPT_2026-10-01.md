# ProbeModel / calibration verifier receipt

## Delivery identity

- Worktree: `/Volumes/NewDrive/AI Project/Forseti.worktrees/worker-r3-calibration-audit`
- Baseline: `origin/commander-r2-ui-takeover` at `9632358a28044aeba7fe7c6520780e89082e516b`
- Implementation commit: `64469fe` (`feat(calibration): add strict fail-closed run contract`)
- Verification date: 2026-10-01, Asia/Taipei
- UI safety lock: respected; no Forseti.app launch, deploy, Accessibility, or UI operation

## Scoped implementation

The calibration slice adds `apps/forseti-cli/calibration_run_contract.py` and its dedicated test module. The contract is deterministic and fail-closed:

- only `VERIFIED` runs with exact corpus/model/context identities, evidence references, observed/owner labels, and a complete five-symptom mapping are classifiable;
- `PLANNED`, `RUN`, malformed, incomplete, and duplicate-`run_id` inputs remain `UNKNOWN` and never fabricate FP/FN;
- FP/FN classification is derived from observed versus owner labels;
- canonical ordering and a SHA-256 contract digest make equivalent input order deterministic.

No ProbeModel model call, Claude authentication check, UI action, recovery path, or deployment was performed.

## Verification evidence

Focused terminating suite:

```text
$ python3 -m pytest -q tests/test_calibration_run_contract.py tests/test_probemodel.py tests/test_probe.py
...............................................................          [100%]
63 passed in 0.35s
```

Static checks:

```text
$ git diff --check 9632358a28044aeba7fe7c6520780e89082e516b..HEAD
# exit 0; no output

$ python3 -m py_compile apps/forseti-cli/calibration_run_contract.py apps/forseti-cli/probemodel.py tests/test_calibration_run_contract.py tests/test_probemodel.py
# exit 0; no output
```

The complete repository Python suite terminated with one unrelated pre-existing failure:

```text
=================================== FAILURES ===================================
____________________________ test_登記簿裡那一筆還在而且指得回這個檔 _____________________________
E       AssertionError: pol-bdfd4735df 不在登記簿裡了
=========================== short test summary info ============================
FAILED tests/test_pollution_probe_vitals_window.py::test_登記簿裡那一筆還在而且指得回這個檔
1 failed, 2089 passed, 1 skipped in 515.59s (0:08:35)
```

The failure is outside this Work Order: both `apps/forseti-cli/pollution.py` and `tests/test_pollution_probe_vitals_window.py` are byte-identical to the baseline, and the final diff contains only the two calibration implementation/test files plus this receipt. The pollution registry path is not an allowed path, so it remains an explicit blocker for a green full-repository suite.

## Per-file diff

- `apps/forseti-cli/calibration_run_contract.py`: new strict normalization, classification, deterministic build, and canonical JSON contract.
- `tests/test_calibration_run_contract.py`: dedicated tests for FP classification, fail-closed states, malformed identities/labels, duplicate IDs, deterministic digest, and non-list input.
- `docs/PROBE_MODEL_CALIBRATION_RECEIPT_2026-10-01.md`: this evidence receipt.

## Acceptance state

The ProbeModel/calibration vertical slice is verified by the focused suite and static checks. Full-suite acceptance is blocked only by the pre-existing pollution registry mismatch above. Next verifiable delivery checkpoint: 2026-10-01 23:00 Asia/Taipei, with the commit SHA, scoped diff, and terminating outputs reported to the Commander.
