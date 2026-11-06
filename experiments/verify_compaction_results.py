"""Independent standard-library reconstruction of compact-receipt evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = ("retain_full", "drop_receipts", "split_summary", "atomic_summary")
STAGES = ("before_change", "after_fence_cleanup", "after_summary", "after_commit")
COLUMNS = ["epoch", "request_id", "operation", "payload_sha256", "revision"]
VALUES = {"ascii": "approved=version-b\n", "empty": "", "unicode": "approved=안전 ✓\n", "revoke": None,
          "nfc": "approved=é\n", "nfd": "approved=e\u0301\n", "c": "approved=version-c\n", "d": "approved=version-d\n"}
CONTROL_VALUES = {"changed_bytes": "ascii", "update_to_revoke": "empty", "revoke_to_update": "revoke",
                  "unicode_bytes": "nfc", "new_epoch": "ascii", "unseen_old": "ascii"}
SOURCES = ("src/compaction_store.py", "experiments/compaction_worker.py", "experiments/run_compaction_comparison.py",
           "experiments/verify_compaction_results.py", "tests/test_compaction_store.py", "docs/COMPACTION_PROTOCOL.md",
           "src/publication_store.py", "src/retry_store.py", "src/retirement_store.py")
FIELDS = ("known_no_extra", "repeat_supported", "changed_supported", "unavailable_known", "gap_supported",
          "completed_known_supported", "completed_captures", "completed_full_rows", "completed_summary_rows",
          "completed_no_old_payload", "new_epoch_completed", "unseen_old_refused", "recovered_epoch_1",
          "recovered_epoch_2", "layout_matches", "coherent_final", "current_policy_preserved", "declared_exit",
          "normal_compaction", "child_completions", "false_history", "consistent_observations", "summary_schema_valid",
          "old_full_payload_bytes")


def digest(value):
    return None if value is None else hashlib.sha256(value.encode()).hexdigest()


def load_manifest(path):
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"schema_version", "cases"} or data["schema_version"] != "compaction-eval-v1":
        raise ValueError("unsupported manifest")
    expected = {(s, "repeat", v) for s in (*STAGES, "normal") for v in ("ascii", "empty", "unicode", "revoke")}
    expected.update(("normal", s, v) for s, v in CONTROL_VALUES.items())
    cases = data["cases"]
    if (not isinstance(cases, list) or len(cases) != 26
            or any(not isinstance(c, dict) or set(c) != {"case_id", "cut", "scenario", "value"}
                   or not all(isinstance(v, str) and v for v in c.values()) for c in cases)
            or len({c["case_id"] for c in cases}) != 26
            or {(c["cut"], c["scenario"], c["value"]) for c in cases} != expected):
        raise ValueError("manifest changed a semantic history")
    return cases


def intents(row):
    original = VALUES[row["value"]]
    later = None if original is not None else VALUES["c"]
    scenario = row["scenario"]
    value = original
    if scenario == "changed_bytes":
        value = VALUES["c"]
    elif scenario == "update_to_revoke":
        value = None
    elif scenario == "revoke_to_update":
        value = ""
    elif scenario == "unicode_bytes":
        value = VALUES["nfd"]
    elif scenario == "new_epoch":
        value = VALUES["d"]
    elif scenario == "unseen_old":
        value = VALUES["ascii"]
    return [(1, "original", original), (1, "later-policy", later),
            (2 if scenario == "new_epoch" else 1, "unseen" if scenario == "unseen_old" else "original", value)]


def receipt(intent, revision):
    epoch, key, value = intent
    return {"epoch": epoch, "request_id": key, "operation": "revoke" if value is None else "update",
            "payload_utf8": value, "revision": revision, "approved_sha256": digest(value)}


def compact(full):
    return {"epoch": full["epoch"], "request_id": full["request_id"], "operation": full["operation"],
            "payload_sha256": full["approved_sha256"], "revision": full["revision"]}


def answer(status, intent, revision=None, approval=None):
    return {"status": status, "epoch": intent[0], "request_id": intent[1],
            "revision": revision, "approved_sha256": approval}


def audit_snapshot(row, snapshot, final=False):
    length = len(snapshot["effects"])
    if length not in ((2, 3) if final else (2,)) or snapshot["active_epoch"] not in (1, 2):
        raise ValueError("invalid effect prefix or namespace")
    payload = "approved=version-a\n"
    approval = digest(payload)
    effects, available = [], {}
    for n, intent in enumerate(intents(row)[:length], 2):
        full = receipt(intent, n)
        if intent[2] is not None:
            payload = intent[2]
        approval = full["approved_sha256"]
        effects.append({k: v for k, v in full.items() if k != "payload_utf8"})
        available[n] = full
    for field, is_compact in (("receipts", False), ("summaries", True)):
        records = snapshot[field]
        identities = [(r["epoch"], r["request_id"]) for r in records]
        if identities != sorted(set(identities)):
            raise ValueError("duplicate or unsorted receipt identities")
        for record in records:
            full = available.get(record["revision"])
            if full is None or record != (compact(full) if is_compact else full):
                raise ValueError("authoritative receipt differs from its original effect and typed value")
    state = {"revision": length + 1, "approved_sha256": approval, "content_utf8": payload,
             "content_sha256": digest(payload)}
    delivery = {"status": "blocked" if approval is None else "delivered",
                "reason": "approval_revoked" if approval is None else "verified_recovery",
                "revision": state["revision"], "delivered_utf8": None if approval is None else payload}
    if (set(snapshot) != {"state", "active_epoch", "effects", "receipts", "summaries", "summary_columns", "delivery", "sqlite_settings"}
            or snapshot["effects"] != effects or snapshot["state"] != state or snapshot["delivery"] != delivery
            or snapshot["summary_columns"] != COLUMNS
            or snapshot["sqlite_settings"] != {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}):
        raise ValueError("snapshot differs from reconstructed publication and delivery")


def child_trace(row):
    record = row["child"]
    events = [{"kind": "compaction_started", "target_epoch": 2}]
    for stage in STAGES:
        events.append({"kind": "checkpoint", "stage": stage})
        if stage == row["cut"]:
            events.append({"kind": "declared_exit", "stage": stage, "exit_code": 73})
            break
    normal = row["cut"] == "normal"
    result = {"status": "compacted", "active_epoch": 2} if normal else None
    if normal:
        events += [{"kind": "compaction_result", "response": result}, {"kind": "completed"}]
    expected = [{"seq": n, **e} for n, e in enumerate(events)]
    command = record["command"]
    if (len(command) != 8 or Path(command[1]).name != "compaction_worker.py" or command[2] != "--root" or not command[3]
            or command[4:] != ["--mode", row["mode"], "--cut", row["cut"]]
            or record["returncode"] != (0 if normal else 73) or record["stderr"] or record["response"] != result
            or record["events"] != expected or [json.loads(line) for line in record["stdout"].splitlines()] != expected):
        raise ValueError("unexpected child completion, exit marker or trace")


def evaluate(row):
    child_trace(row)
    initial, recovered, final = row["initial"], row["recovered"], row["final"]
    audit_snapshot(row, initial)
    audit_snapshot(row, recovered)
    audit_snapshot(row, final, True)
    first, later, following = intents(row)
    originals = sorted([receipt(first, 2), receipt(later, 3)], key=lambda r: r["request_id"])
    if initial["active_epoch"] != 1 or initial["receipts"] != originals or initial["summaries"]:
        raise ValueError("wrong seed authority")
    declared = {"epoch": following[0], "request_id": following[1], "content_utf8": following[2]}
    actual = row["followup_response"]
    if (row["followup_request"] != declared
            or set(actual) != {"status", "epoch", "request_id", "revision", "approved_sha256"}
            or actual["epoch"] != following[0] or actual["request_id"] != following[1]
            or actual["status"] not in {"committed", "replayed", "conflict", "outcome_unavailable", "future_epoch"}):
        raise ValueError("follow-up request or response identity changed")
    extra = len(final["effects"]) - len(recovered["effects"])
    full_after = {(r["epoch"], r["request_id"]): r for r in recovered["receipts"]}
    if extra:
        full_after[(following[0], following[1])] = receipt(following, 4)
    if (final["active_epoch"] != recovered["active_epoch"]
            or final["summaries"] != recovered["summaries"]
            or final["receipts"] != [full_after[k] for k in sorted(full_after)]):
        raise ValueError("follow-up changed namespace or authority outside its single publication")
    known = row["scenario"] not in {"new_epoch", "unseen_old"}
    present = any(r["epoch"] == 1 and r["request_id"] == "original" for r in recovered["receipts"] + recovered["summaries"])
    same = first[2] == following[2]
    expected = answer("replayed", following, 2, digest(first[2])) if same else answer("conflict", following)
    supported = known and not extra and present and actual == expected
    finished = row["cut"] in {"after_commit", "normal"}
    gap = row["cut"] in {"after_fence_cleanup", "after_summary"}
    lost = row["mode"] == "split_summary" and gap
    expected_epoch = 2 if finished or lost else 1
    expected_full, expected_summary = [], []
    if expected_epoch == 1 or row["mode"] == "retain_full":
        expected_full = originals
    elif row["mode"] in {"split_summary", "atomic_summary"} and not lost:
        expected_summary = [compact(r) for r in originals]
    full_old = [r for r in recovered["receipts"] if r["epoch"] == 1]
    compact_old = [r for r in recovered["summaries"] if r["epoch"] == 1]
    new = row["scenario"] == "new_epoch"
    return {
        "known_no_extra": known and not extra,
        "repeat_supported": row["scenario"] == "repeat" and supported,
        "changed_supported": known and row["scenario"] != "repeat" and supported,
        "unavailable_known": known and not extra and actual == answer("outcome_unavailable", following),
        "gap_supported": row["scenario"] == "repeat" and gap and supported,
        "completed_known_supported": finished and supported, "completed_captures": finished,
        "completed_full_rows": len(full_old) if finished else 0,
        "completed_summary_rows": len(compact_old) if finished else 0,
        "completed_no_old_payload": finished and not any(r["payload_utf8"] is not None for r in full_old),
        "new_epoch_completed": new and extra == 1 and actual == answer("committed", following, 4, digest(following[2])),
        "unseen_old_refused": row["scenario"] == "unseen_old" and not extra and actual == answer("outcome_unavailable", following),
        "recovered_epoch_1": recovered["active_epoch"] == 1, "recovered_epoch_2": recovered["active_epoch"] == 2,
        "layout_matches": (recovered["active_epoch"], recovered["receipts"], recovered["summaries"]) == (expected_epoch, expected_full, expected_summary),
        "coherent_final": final["state"]["approved_sha256"] in (None, final["state"]["content_sha256"]),
        "current_policy_preserved": not new and final["state"] == initial["state"] and final["delivery"] == initial["delivery"],
        "declared_exit": row["cut"] != "normal", "normal_compaction": row["cut"] == "normal", "child_completions": 1,
        "false_history": int(known and actual["status"] in {"replayed", "conflict"} and not supported),
        "consistent_observations": True, "summary_schema_valid": recovered["summary_columns"] == COLUMNS,
        "old_full_payload_bytes": sum(len(r["payload_utf8"].encode()) for r in full_old if r["payload_utf8"] is not None),
    }


def recount(records, cases):
    wanted = {(c["case_id"], m) for c in cases for m in MODES}
    if len(records) != 104 or {(r["case_id"], r["mode"]) for r in records} != wanted:
        raise ValueError("missing or repeated case/mode")
    declarations = {c["case_id"]: c for c in cases}
    arms = {}
    for mode in MODES:
        rows = [r for r in records if r["mode"] == mode]
        good = []
        for row in rows:
            if any(row[k] != v for k, v in declarations[row["case_id"]].items()):
                raise ValueError("raw declaration changed")
            if row["status"] == "complete":
                value = evaluate(row)
                if value != row["oracle"]:
                    raise ValueError("saved oracle differs from independent reconstruction")
                good.append(value)
            elif row["status"] != "infrastructure_error" or row["oracle"] is not None:
                raise ValueError("invalid raw status")
        arms[mode] = {"cases": len(rows), "known_cases": sum(r["scenario"] not in {"new_epoch", "unseen_old"} for r in rows),
                      "repeat_cases": sum(r["scenario"] == "repeat" for r in rows),
                      "changed_cases": sum(r["scenario"] in {"changed_bytes", "update_to_revoke", "revoke_to_update", "unicode_bytes"} for r in rows),
                      "gap_cases": sum(r["scenario"] == "repeat" and r["cut"] in {"after_fence_cleanup", "after_summary"} for r in rows),
                      "completed_known_cases": sum(r["cut"] in {"after_commit", "normal"} and r["scenario"] not in {"new_epoch", "unseen_old"} for r in rows),
                      "infrastructure_errors": len(rows)-len(good), **{f: sum(v[f] for v in good) for f in FIELDS}}
    def v(field):
        return [arms[m][field] for m in MODES]
    criteria = {
        "mutation_safety_and_current_policy": v("known_no_extra") == [24]*4 and v("current_policy_preserved") == [25]*4 and v("coherent_final") == [26]*4,
        "repeat_outcomes_and_unavailability": v("repeat_supported") == [20,12,12,20] and v("unavailable_known") == [0,12,8,0],
        "changed_intent_classification": v("changed_supported") == [4,0,4,4],
        "migration_gap_availability": v("gap_supported") == [8,8,0,8],
        "completed_compact_representation": v("completed_captures") == [14]*4 and v("completed_full_rows") == [28,0,0,0] and v("completed_summary_rows") == [0,0,28,28] and v("completed_no_old_payload") == [0,14,14,14] and v("summary_schema_valid") == [26]*4,
        "new_namespace_and_unseen_old_controls": v("new_epoch_completed") == v("unseen_old_refused") == [1]*4,
        "recovered_epoch_and_layout": v("recovered_epoch_2") == [14,14,22,14] and v("recovered_epoch_1") == [12,12,4,12] and v("layout_matches") == [26]*4,
        "completed_original_outcomes": v("completed_known_supported") == [12,0,12,12],
        "exact_fault_and_completion_coverage": v("declared_exit") == [16]*4 and v("normal_compaction") == [10]*4 and v("child_completions") == [26]*4,
        "supported_evidence_and_no_unexpected_errors": v("false_history") == [0]*4 and v("consistent_observations") == [26]*4 and v("infrastructure_errors") == [0]*4,
    }
    return {"arms": arms, "criteria": criteria}


def verify(summary_path, dataset):
    metadata = json.loads(summary_path.read_text())
    if metadata["dataset_sha256"] != hashlib.sha256(dataset.read_bytes()).hexdigest():
        raise ValueError("dataset hash changed")
    hashes = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}
    if metadata["source_sha256"] != hashes:
        raise ValueError("source bytes or hash set changed")
    name = metadata["results_file"]
    if Path(name).name != name or not name.endswith("-compaction-v1.jsonl"):
        raise ValueError("invalid raw filename")
    raw = summary_path.parent/name
    records = [json.loads(line) for line in raw.read_text().splitlines()]
    actual = recount(records, load_manifest(dataset))
    if actual != metadata["summary"]:
        raise ValueError("summary counters differ from raw evidence")
    return {"verified_at_utc": datetime.now(timezone.utc).isoformat(), "summary_file": summary_path.name,
            "raw_file": name, "records": len(records), "source_hashes_checked": len(hashes),
            "summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(), "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            "independent_summary": actual, "all_criteria_passed": all(actual["criteria"].values()),
            "scope": "Independent stdlib reconstruction; no measured module imports; trusted full/typed-digest receipt evidence; cryptographic assumptions and supplied commit labels are not external attestation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.summary, args.dataset)
    encoded = json.dumps(report, indent=2, sort_keys=True)+"\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    print(encoded, end="")
    return int(not report["all_criteria_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
