"""Arrange receipt retirement between duplicate rollback and response resolution."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.resolution_worker import PAYLOADS
from experiments.run_overlap_comparison import BarrierFailure, wait_for_pause
from src.publication_store import recover_value
from src.resolution_store import MODES, ResolutionPublicationStore

PATTERNS = {
    "same_ascii": ("b", "b"), "same_empty": ("empty", "empty"),
    "same_unicode": ("unicode", "unicode"), "same_revoke": ("revoke", "revoke"),
    "changed_bytes": ("b", "c"), "update_to_revoke": ("empty", "revoke"),
    "revoke_to_update": ("revoke", "empty"), "changed_unicode_bytes": ("nfc", "nfd"),
}
SOURCES = (
    "src/resolution_store.py", "experiments/resolution_worker.py", "experiments/run_resolution_comparison.py",
    "experiments/verify_resolution_results.py", "tests/test_resolution_store.py", "docs/RESOLUTION_PROTOCOL.md",
    "src/publication_store.py", "src/retry_store.py", "src/retirement_store.py", "src/overlap_store.py",
    "experiments/run_overlap_comparison.py",
)
STEP_TIMEOUT = 15
ORACLE_FIELDS = (
    "extra_gap_effect", "one_shared_effect", "new_effects", "safe_gap_resolution", "unavailable_gap",
    "original_gap_resolution", "identical_gap_replay", "changed_gap_conflict", "later_state_preserved",
    "control_original_resolution", "receipt_pk_aborts", "rollback_verified", "busy_retirements",
    "completed_retirement_retry", "final_epoch_3", "final_epoch_2", "coherent_final", "invalid_old_commit",
    "recreated_old_receipt", "retired_old_receipts_absent", "consistent_observations", "verified_barriers",
    "child_completions",
)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"schema_version", "cases"} or data["schema_version"] != "resolution-eval-v1":
        raise ValueError("unsupported resolution manifest")
    cases = data["cases"]
    expected = {("retire_gap", p) for p in PATTERNS}
    expected |= {("retire_gap_later", p) for p in ("same_ascii", "same_revoke", "changed_bytes", "update_to_revoke")}
    expected |= {("resolution_first", p) for p in ("same_ascii", "changed_bytes")}
    expected |= {("retained", p) for p in ("same_empty", "changed_unicode_bytes")}
    if (not isinstance(cases, list) or len(cases) != 16
            or any(not isinstance(c, dict) or set(c) != {"case_id", "schedule", "pattern"}
                   or not all(isinstance(v, str) and v for v in c.values()) for c in cases)
            or len({c["case_id"] for c in cases}) != 16
            or {(c["schedule"], c["pattern"]) for c in cases} != expected):
        raise ValueError("sixteen unique declared histories required")
    return cases


def inputs(case: dict) -> dict:
    result = {}
    for caller, alias in zip(("first", "second", "later"), (*PATTERNS[case["pattern"]], "later")):
        value = PAYLOADS[alias]
        result[caller] = {"caller": caller, "epoch": 3 if caller == "later" else 2,
                          "request_id": "later" if caller == "later" else "shared-request", "intent": alias,
                          "content_utf8": None if value is None else value.decode()}
    return result


def reply(status, req, revision=None, approved=None):
    return {"status": status, "epoch": req["epoch"], "request_id": req["request_id"],
            "revision": revision, "approved_sha256": approved}


def capture(store) -> dict:
    observed = store.inspect()
    state = observed.pop("state")
    output = recover_value(state)
    value = output.pop("content")
    observed["receipts"] = [{**{k: v for k, v in r.items() if k != "payload"},
                             "payload_utf8": None if r["payload"] is None else r["payload"].decode()}
                            for r in observed["receipts"]]
    return {**observed, "state": {"revision": state.revision, "approved_sha256": state.approved_sha256,
                                 "content_utf8": state.content.decode(), "content_sha256": sha(state.content)},
            "delivery": {**output, "delivered_utf8": None if value is None else value.decode()},
            "sqlite_settings": store.settings()}


def audit_capture(case, observed):
    declared = inputs(case)
    commits, active = observed["commits"], observed["active_epoch"]
    if active not in (2, 3):
        raise ValueError("unexpected active epoch")
    payload, approved = "approved=version-b\n", None
    effects = [
        {"revision": 2, "epoch": 1, "request_id": "seed-a", "operation": "update", "approved_sha256": sha(payload.encode())},
        {"revision": 3, "epoch": 1, "request_id": "seed-b", "operation": "revoke", "approved_sha256": None},
    ]
    receipts = {}
    previous_active = 2
    for revision, commit in enumerate(commits, 4):
        if commit["caller"] not in declared:
            raise ValueError("undeclared committing caller")
        req = declared[commit["caller"]]
        current = commit["active_epoch"]
        if current not in (2, 3) or not previous_active <= current <= active:
            raise ValueError("commit-time epoch contradicts monotonic namespace")
        previous_active = current
        value = req["content_utf8"]
        if value is not None:
            payload = value
        approved = None if value is None else sha(value.encode())
        effect = {"revision": revision, "epoch": req["epoch"], "request_id": req["request_id"],
                  "operation": "revoke" if value is None else "update", "approved_sha256": approved}
        if commit != {**effect, "caller": req["caller"], "active_epoch": current}:
            raise ValueError("observer does not bind actual request bytes and effect")
        effects.append(effect)
        if req["epoch"] >= active or current == active:
            receipts[(req["epoch"], req["request_id"])] = {**effect, "payload_utf8": value}
    state = {"revision": 3 + len(commits), "approved_sha256": approved, "content_utf8": payload,
             "content_sha256": sha(payload.encode())}
    delivery = {"status": "blocked" if approved is None else "delivered",
                "reason": "approval_revoked" if approved is None else "verified_recovery",
                "revision": state["revision"], "delivered_utf8": None if approved is None else payload}
    expected = {"state": state, "active_epoch": active, "effects": effects,
                "receipts": [v for k, v in sorted(receipts.items())], "commits": commits, "delivery": delivery,
                "sqlite_settings": {"journal_mode": "delete", "synchronous": 2, "integrity_check": "ok"}}
    if observed != expected:
        raise ValueError("capture differs from durable caller/epoch history")
    return commits


def check_process(record, result_kind):
    events = [json.loads(line) for line in record["stdout"].splitlines()]
    if (record["returncode"] != 0 or record["stderr"] or record["events"] != events
            or any(e["seq"] != n for n, e in enumerate(events))
            or [e["response"] for e in events if e["kind"] == result_kind] != [record["response"]]):
        raise ValueError("incomplete child process result or trace")
    return events


def audit_retirement(record):
    answer = record["response"]
    busy = answer["status"] == "busy"
    expected = {"target_epoch": 3, "busy_timeout_ms": 0, "sqlite_errorcode": 5 if busy else None,
                "sqlite_errorname": "SQLITE_BUSY" if busy else None, "status": "busy" if busy else "retired",
                "active_epoch": None if busy else 3}
    events = [{"seq": 0, "kind": "retirement_started", "target_epoch": 3},
              {"seq": 1, "kind": "retirement_result", "response": expected}, {"seq": 2, "kind": "completed"}]
    command = record["command"]
    if (answer != expected or check_process(record, "retirement_result") != events
            or len(command) != 10 or Path(command[1]).name != "resolution_worker.py"
            or command[2] != "--root" or not command[3]
            or command[4:] != ["--mode", record["mode"], "--role", "retire", "--target", "3"]):
        raise ValueError("retirement result/code/command differs")
    return busy


def audit_caller(row, record):
    req = inputs(row)[record["caller"]]
    command, caller = record["command"], record["caller"]
    if (record["request"] != req or record["mode"] != row["mode"] or len(command) != 18
            or Path(command[1]).name != "resolution_worker.py" or command[2] != "--root" or not command[3]
            or command[4:] != ["--mode", row["mode"], "--role", "caller", "--caller", caller,
                               "--epoch", str(req["epoch"]), "--key", req["request_id"], "--intent", req["intent"],
                               "--pauses", "both" if caller == "first" else "none"]):
        raise ValueError("caller identity, bytes or invocation changed")
    answer = record["response"]
    if (set(answer) != {"status", "epoch", "request_id", "revision", "approved_sha256"}
            or answer["epoch"] != req["epoch"] or answer["request_id"] != req["request_id"]
            or answer["status"] not in {"committed", "replayed", "conflict", "outcome_unavailable", "storage_error", "busy", "future_epoch"}):
        raise ValueError("invalid caller result schema")
    events = []
    def event(kind, **fields):
        events.append({"seq": len(events), "kind": kind, **fields})
    def checkpoint(stage, paused=False):
        event("checkpoint", stage=stage)
        if paused:
            event("paused", stage=stage, caller="first")
            event("resumed", stage=stage, caller="first")
    def view(scope, active, revision, seen, decision, origin="read"):
        event("lookup", scope=scope, origin=origin, observed_epoch=active, current_revision=revision,
              receipt_seen=seen, receipt_revision=4 if seen else None, decision=decision)
    value = req["content_utf8"]
    event("caller_started", caller=caller, epoch=req["epoch"], request_id=req["request_id"],
          operation="revoke" if value is None else "update", payload_sha256=None if value is None else sha(value.encode()))
    view("initial", req["epoch"], 4 if caller == "later" else 3, False, "missing")
    checkpoint("after_precheck", caller == "first")
    event("write_view", revision=4 if caller == "second" else 5, requested_epoch=req["epoch"], active_epoch=req["epoch"])
    if caller == "first":
        event("duplicate_receipt", at="receipt_insert", sqlite_errorcode=1555,
              sqlite_errorname="SQLITE_CONSTRAINT_PRIMARYKEY", transaction_rolled_back=True)
        guarded = row["mode"] == "guarded_resolution"
        event("resolution_guard", held=guarded)
        checkpoint("before_resolution", True)
        observation = row["resolution_capture"]
        active, revision = observation["active_epoch"], observation["state"]["revision"]
        seen = any(r["epoch"] == 2 and r["request_id"] == "shared-request" for r in observation["receipts"])
        same = req["content_utf8"] == inputs(row)["second"]["content_utf8"]
        decision = ("replayed" if same else "conflict") if seen else "outcome_unavailable" if active > 2 else "missing"
        view("resolution", active, revision, seen, decision, "transaction" if guarded else "read")
        if row["mode"] == "retry_missing" and not seen:
            event("unsafe_retry", requested_epoch=2, observed_epoch=active)
            event("write_view", revision=revision + 1, requested_epoch=2, active_epoch=active)
            checkpoint("before_commit")
            checkpoint("after_commit")
        elif guarded:
            event("resolution_released")
    else:
        checkpoint("before_commit")
        checkpoint("after_commit")
    event("caller_result", response=answer)
    event("completed")
    if check_process(record, "caller_result") != events:
        raise ValueError("caller trace contradicts its lookup/rollback/guard path")


def assess(row):
    reqs = inputs(row)
    gap = row["schedule"] in {"retire_gap", "retire_gap_later"}
    later = row["schedule"] == "retire_gap_later"
    callers, retirements = row["callers"], row["retirements"]
    invocations = [r["command"] for r in (*callers, *retirements)]
    if any(len(c) < 4 for c in invocations) or len({(c[0], c[1], c[3]) for c in invocations}) != 1:
        raise ValueError("child invocations changed interpreter, worker or fixture")
    if [r["caller"] for r in callers] != ["first", "second"] + (["later"] if later else []):
        raise ValueError("missing or repeated logical caller")
    busy = bool(retirements and retirements[0]["response"]["status"] == "busy")
    phases = (["during_resolution"] + (["after_resolution"] if busy else [])) if gap else ["after_resolution"] if row["schedule"] == "resolution_first" else []
    if [r["phase"] for r in retirements] != phases or (busy and row["mode"] != "guarded_resolution"):
        raise ValueError("retirement order or scope changed")
    for r in retirements:
        if r["mode"] != row["mode"]:
            raise ValueError("retirement changed mode")
        audit_retirement(r)
        audit_capture(row, r["capture"])
    if retirements and retirements[-1]["response"]["status"] != "retired":
        raise ValueError("retirement never completed")
    for record in callers:
        audit_caller(row, record)
    initial = audit_capture(row, row["initial"])
    winner = audit_capture(row, row["winner_capture"])
    resolution = audit_capture(row, row["resolution_capture"])
    first_done = audit_capture(row, row["after_first"])
    final = audit_capture(row, row["final"])
    if initial or row["initial"]["active_epoch"] != 2 or [c["caller"] for c in winner] != ["second"]:
        raise ValueError("fixture or actual winner changed")
    if winner[0]["active_epoch"] != 2 or row["winner_capture"]["active_epoch"] != 2:
        raise ValueError("original commitment was not at epoch 2")
    prefix = winner
    for attempt in retirements:
        if attempt["phase"] == "during_resolution":
            if attempt["capture"]["commits"] != winner or attempt["capture"]["active_epoch"] != (2 if busy else 3):
                raise ValueError("first retirement observation changed the winner")
    if later:
        after_later = audit_capture(row, row["later_capture"])
        if [c["caller"] for c in after_later] != ["second", "later"] or row["later_capture"]["active_epoch"] != 3:
            raise ValueError("independent later work in wrong position")
        later_result = callers[-1]["response"]
        c = after_later[-1]
        if later_result != reply("committed", reqs["later"], c["revision"], c["approved_sha256"]):
            raise ValueError("later acknowledgment does not match its effect")
        if not busy:
            prefix = after_later
    elif row["later_capture"] is not None:
        raise ValueError("undeclared later work")
    if resolution != prefix or row["resolution_capture"]["active_epoch"] != (3 if gap and not busy else 2):
        raise ValueError("resolution snapshot contradicts retirement ordering")
    if first_done[:len(prefix)] != prefix or any(c["caller"] != "first" for c in first_done[len(prefix):]):
        raise ValueError("first completion rewrote a causal prefix")
    for attempt in retirements:
        if attempt["phase"] == "after_resolution" and attempt["capture"]["commits"] != first_done:
            raise ValueError("retirement changed a committed effect prefix")
    expected_final = after_later if later and busy else first_done
    if final != expected_final or row["final"]["active_epoch"] != (2 if row["schedule"] == "retained" else 3):
        raise ValueError("final snapshot has an unscheduled writer or epoch")
    if later and busy and after_later[:-1] != first_done:
        raise ValueError("later work rewrote completed resolution history")
    journal = []
    def note(kind, **fields):
        journal.append({"seq": len(journal), "kind": kind, **fields})
    def caller(c, start=False):
        note("caller_started" if start else "caller_completed", caller=c,
             **({} if start else {"status": next(r["response"]["status"] for r in callers if r["caller"] == c)}))
    def retire(index):
        item = retirements[index]
        note("retirement_requested", attempt=index + 1, phase=item["phase"])
        note("retirement_completed", attempt=index + 1, status=item["response"]["status"], sqlite_errorcode=item["response"]["sqlite_errorcode"])
        note("retirement_observed", attempt=index + 1)
    def independent():
        caller("later", True)
        caller("later")
        note("later_observed")
    note("seeded")
    caller("first", True)
    note("first_paused", stage="after_precheck")
    caller("second", True)
    caller("second")
    note("winner_observed")
    note("first_resumed", stage="after_precheck")
    note("first_paused", stage="before_resolution")
    if gap:
        retire(0)
        if later and not busy:
            independent()
    note("resolution_observed")
    note("first_resumed", stage="before_resolution")
    caller("first")
    note("first_observed")
    if busy or row["schedule"] == "resolution_first":
        retire(1 if busy else 0)
        if later:
            independent()
    note("final_observed")
    if row["timeline"] != journal:
        raise ValueError("controller journal differs from actor order")
    actual = callers[0]["response"]
    same = reqs["first"]["content_utf8"] == reqs["second"]["content_utf8"]
    original = reply("replayed", reqs["first"], winner[0]["revision"], winner[0]["approved_sha256"]) if same else reply("conflict", reqs["first"])
    winner_ok = callers[1]["response"] == reply("committed", reqs["second"], winner[0]["revision"], winner[0]["approved_sha256"])
    shared_count = sum(c["request_id"] == "shared-request" for c in final)
    one = shared_count == 1
    receipt_available = any(r["epoch"] == 2 and r["request_id"] == "shared-request" for r in row["resolution_capture"]["receipts"])
    original_ok = winner_ok and one and receipt_available and actual == original
    missing_closed = row["resolution_capture"]["active_epoch"] > 2 and not receipt_available
    unavailable = actual == reply("outcome_unavailable", reqs["first"])
    safe = original_ok or (winner_ok and one and unavailable and missing_closed)
    return {"extra_gap_effect": gap and shared_count > 1, "one_shared_effect": one, "new_effects": len(final),
            "safe_gap_resolution": gap and safe, "unavailable_gap": gap and unavailable and missing_closed and one,
            "original_gap_resolution": gap and original_ok, "identical_gap_replay": gap and same and original_ok,
            "changed_gap_conflict": gap and not same and original_ok,
            "later_state_preserved": later and row["final"]["state"] == row["later_capture"]["state"] and row["final"]["delivery"] == row["later_capture"]["delivery"],
            "control_original_resolution": not gap and original_ok, "receipt_pk_aborts": 1, "rollback_verified": True,
            "busy_retirements": int(busy), "completed_retirement_retry": busy,
            "final_epoch_3": row["final"]["active_epoch"] == 3, "final_epoch_2": row["final"]["active_epoch"] == 2,
            "coherent_final": row["final"]["state"]["approved_sha256"] in (None, row["final"]["state"]["content_sha256"]),
            "invalid_old_commit": any(c["epoch"] < c["active_epoch"] for c in final),
            "recreated_old_receipt": any(r["epoch"] < row["final"]["active_epoch"] for r in row["final"]["receipts"]),
            "retired_old_receipts_absent": row["final"]["active_epoch"] == 3 and not any(r["epoch"] < 3 for r in row["final"]["receipts"]),
            "consistent_observations": True, "verified_barriers": 2,
            "child_completions": len(callers) + len(retirements)}


def criteria(arms):
    a = [arms[m] for m in MODES]
    def counts(field):
        return [v[field] for v in a]
    return {
        "one_effect_and_total_effects": counts("extra_gap_effect") == [12, 0, 0] and counts("one_shared_effect") == [4, 16, 16] and counts("new_effects") == [32, 20, 20],
        "safe_outcomes_and_unavailability": counts("safe_gap_resolution") == [0, 12, 12] and counts("unavailable_gap") == [0, 12, 0],
        "original_outcomes": counts("original_gap_resolution") == [0, 0, 12] and counts("identical_gap_replay") == [0, 0, 6] and counts("changed_gap_conflict") == [0, 0, 6],
        "later_policy_preserved": counts("later_state_preserved") == [0, 4, 4],
        "original_controls": counts("control_original_resolution") == [4, 4, 4],
        "collision_and_rollback": counts("receipt_pk_aborts") == counts("rollback_verified") == [16, 16, 16],
        "retirement_contention_and_retries": counts("busy_retirements") == counts("completed_retirement_retry") == [0, 0, 12],
        "current_epoch_and_coherence": counts("final_epoch_3") == [14, 14, 14] and counts("final_epoch_2") == [2, 2, 2] and counts("coherent_final") == counts("consistent_observations") == [16, 16, 16],
        "closed_epoch_evidence": counts("invalid_old_commit") == counts("recreated_old_receipt") == [12, 0, 0] and counts("retired_old_receipts_absent") == [2, 14, 14],
        "complete_process_and_barrier_coverage": counts("verified_barriers") == [32, 32, 32] and counts("child_completions") == [50, 50, 62] and counts("infrastructure_errors") == [0, 0, 0],
    }


def summarize(records, cases):
    expected = {(c["case_id"], m) for c in cases for m in MODES}
    if len(records) != 48 or {(r["case_id"], r["mode"]) for r in records} != expected:
        raise ValueError("exactly one record per case and mode required")
    declarations = {c["case_id"]: c for c in cases}
    arms = {}
    for mode in MODES:
        rows = [r for r in records if r["mode"] == mode]
        good = []
        for row in rows:
            if any(row[k] != v for k, v in declarations[row["case_id"]].items()):
                raise ValueError("raw declaration differs from manifest")
            if row["status"] == "complete":
                actual = assess(row)
                if row["oracle"] != actual:
                    raise ValueError("stored oracle differs from observations")
                good.append(actual)
            elif row["status"] != "infrastructure_error" or row["oracle"] is not None:
                raise ValueError("invalid raw status")
        arms[mode] = {"cases": len(rows), "gap_cases": 12, "identical_gap_cases": 6, "changed_gap_cases": 6,
                      "later_cases": 4, "control_cases": 4, "retired_cases": 14,
                      "infrastructure_errors": len(rows) - len(good),
                      **{name: sum(v[name] for v in good) for name in ORACLE_FIELDS}}
    return {"arms": arms, "criteria": criteria(arms)}


def run_case(case, mode):
    if mode not in MODES:
        raise ValueError("unknown resolution mode")
    row = {**case, "mode": mode, "status": "pending", "error_phase": "setup", "error_type": None,
           "error_detail": None, "callers": [], "retirements": [], "timeline": [], "oracle": None,
           "initial": None, "winner_capture": None, "resolution_capture": None, "after_first": None,
           "later_capture": None, "final": None}
    process, consumed, drained, held = None, b"", False, None
    def note(kind, **fields):
        row["timeline"].append({"seq": len(row["timeline"]), "kind": kind, **fields})
    with tempfile.TemporaryDirectory(prefix="codeguardian-resolution-") as directory:
        root = Path(directory)
        store = ResolutionPublicationStore(root, mode)
        declared = inputs(case)
        def caller_record(caller):
            req = declared[caller]
            command = [sys.executable, str(ROOT / "experiments/resolution_worker.py"), "--root", str(root),
                       "--mode", mode, "--role", "caller", "--caller", caller, "--epoch", str(req["epoch"]),
                       "--key", req["request_id"], "--intent", req["intent"], "--pauses", "both" if caller == "first" else "none"]
            record = {"caller": caller, "mode": mode, "request": req.copy(), "command": command,
                      "returncode": None, "stdout": "", "stderr": "", "events": [], "response": None}
            row["callers"].append(record)
            note("caller_started", caller=caller)
            return record
        def finish(record, code, stdout, stderr, result_kind):
            record.update(returncode=code, stdout=stdout.decode() if isinstance(stdout, bytes) else stdout,
                          stderr=stderr.decode() if isinstance(stderr, bytes) else stderr)
            record["events"] = [json.loads(line) for line in record["stdout"].splitlines()]
            results = [e["response"] for e in record["events"] if e.get("kind") == result_kind]
            if code != 0 or record["stderr"] or len(results) != 1:
                raise ValueError("child failed to return a complete modeled result")
            record["response"] = results[0]
        def execute(record, result_kind):
            try:
                child = subprocess.run(record["command"], capture_output=True, text=True, timeout=STEP_TIMEOUT)
            except subprocess.TimeoutExpired as error:
                record["stdout"] = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
                record["stderr"] = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
                raise
            finish(record, child.returncode, child.stdout, child.stderr, result_kind)
        def invoke(caller):
            record = caller_record(caller)
            row["error_phase"] = "caller_" + caller
            execute(record, "caller_result")
            note("caller_completed", caller=caller, status=record["response"]["status"])
        def retire(phase):
            number = len(row["retirements"]) + 1
            record = {"mode": mode, "phase": phase,
                      "command": [sys.executable, str(ROOT / "experiments/resolution_worker.py"), "--root", str(root),
                                  "--mode", mode, "--role", "retire", "--target", "3"],
                      "returncode": None, "stdout": "", "stderr": "", "events": [], "response": None, "capture": None}
            row["retirements"].append(record)
            note("retirement_requested", attempt=number, phase=phase)
            row["error_phase"] = "retirement"
            execute(record, "retirement_result")
            audit_retirement(record)
            result = record["response"]
            note("retirement_completed", attempt=number, status=result["status"], sqlite_errorcode=result["sqlite_errorcode"])
            record["capture"] = capture(store)
            note("retirement_observed", attempt=number)
            return result["status"] == "busy"
        def independent():
            invoke("later")
            row["later_capture"] = capture(store)
            note("later_observed")
        def resume(stage):
            if process.stdin is None:
                raise ValueError("caller stdin required")
            process.stdin.write((json.dumps({"command": "resume", "stage": stage, "caller": "first"}) + "\n").encode())
            process.stdin.flush()
            note("first_resumed", stage=stage)
        try:
            store.initialize(b"approved=version-a\n")
            store.publish_request(1, "seed-a", b"approved=version-b\n")
            store.publish_request(1, "seed-b", None)
            store.retire(2)
            row["initial"] = capture(store)
            note("seeded")
            held = caller_record("first")
            process = subprocess.Popen(held["command"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            row["error_phase"] = "first_barrier"
            consumed = wait_for_pause(process, "after_precheck", STEP_TIMEOUT)
            note("first_paused", stage="after_precheck")
            invoke("second")
            row["winner_capture"] = capture(store)
            note("winner_observed")
            resume("after_precheck")
            row["error_phase"] = "resolution_barrier"
            consumed += wait_for_pause(process, "before_resolution", STEP_TIMEOUT)
            note("first_paused", stage="before_resolution")
            gap = case["schedule"] in {"retire_gap", "retire_gap_later"}
            later = case["schedule"] == "retire_gap_later"
            busy = retire("during_resolution") if gap else False
            if later and not busy:
                independent()
            row["resolution_capture"] = capture(store)
            note("resolution_observed")
            resume("before_resolution")
            row["error_phase"] = "first_completion"
            tail, stderr = process.communicate(timeout=STEP_TIMEOUT)
            drained = True
            finish(held, process.returncode, consumed + tail, stderr, "caller_result")
            note("caller_completed", caller="first", status=held["response"]["status"])
            row["after_first"] = capture(store)
            note("first_observed")
            if busy or case["schedule"] == "resolution_first":
                if retire("after_resolution"):
                    raise ValueError("scheduled retirement retry did not complete")
                if later:
                    independent()
            row["final"] = capture(store)
            note("final_observed")
            row["error_phase"] = "oracle"
            row["oracle"] = assess(row)
            row.update(status="complete", error_phase=None)
        except (OSError, ValueError, RuntimeError, UnicodeError, sqlite3.Error, subprocess.SubprocessError) as error:
            if isinstance(error, BarrierFailure):
                consumed += error.output
            elif isinstance(error, subprocess.TimeoutExpired) and row["error_phase"] in {"first_barrier", "resolution_barrier"}:
                consumed += error.stdout or b""
            row.update(status="infrastructure_error", error_type=type(error).__name__, error_detail=str(error))
        finally:
            if process is not None and not drained:
                if process.poll() is None:
                    process.kill()
                tail, stderr = process.communicate(timeout=STEP_TIMEOUT)
                held.update(returncode=process.returncode, stdout=(consumed + tail).decode(errors="replace"), stderr=stderr.decode(errors="replace"))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments/results")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11+ numeric SQLite metadata required")
    started = datetime.now(timezone.utc)
    cases = load_cases(args.dataset)
    records = [run_case(c, m) for c in cases for m in MODES]
    result = summarize(records, cases)
    run = started.strftime("%Y-%m-%dT%H-%M-%S-%fZ-resolution-v1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = args.output_dir / (run + ".jsonl")
    metadata = {"started_at_utc": started.isoformat(), "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "python_version": platform.python_version(), "sqlite_version": sqlite3.sqlite_version, "platform": platform.platform(),
                "base_commit": args.base_commit, "freeze_commit": args.freeze_commit, "command": [sys.executable, *sys.argv],
                "dataset": str(args.dataset), "dataset_sha256": sha(args.dataset.read_bytes()),
                "source_sha256": {p: sha((ROOT / p).read_bytes()) for p in SOURCES}, "results_file": raw.name, "summary": result,
                "interpretation_limit": "Fixed two-caller rollback/resolution ordering with logical retirement; unavailable historical outcomes and guarded retirement deferral remain separate; no general concurrency, latency, authentication, network, crash or external-effect claim."}
    with raw.open("x", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (args.output_dir / (run + "-summary.json")).open("x", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    print("Saved " + run)
    return int(any(a["infrastructure_errors"] for a in result["arms"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
