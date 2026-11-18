"""Bonus B3 tests: Swarm with code-level grounded verifier."""

import json
from pathlib import Path
import pytest

from bonus.swarm_verified import run_claim
from lab8.db import connect
from lab8.durability import get_refund


def test_swarm_verified_overrides_seed_55_weakness(public_db):
    """C-002 seed 55: Ticket claims delay 5 days, DB says 2 days.

    Swarm reference fails (pays 20000). Swarm_verified must detect discrepancy,
    log verifier_override event, quote 0, and deny compensation.
    """
    res = run_claim("C-002", seed=55, store_path=str(public_db))
    assert res.status == "denied"
    assert res.proposal_amount == 0

    trace_file = Path(res.trace_path)
    assert trace_file.exists()
    trace_data = json.loads(trace_file.read_text(encoding="utf-8"))
    events = [e["kind"] for e in trace_data["events"]]
    assert "verifier_override" in events


def test_swarm_verified_normal_claim_resolves_cleanly(public_db):
    """C-001 seed 11: Valid late delivery. Should resolve with full entitlement."""
    res = run_claim("C-001", seed=11, store_path=str(public_db))
    assert res.status == "resolved"
    assert res.proposal_amount == 35000
    assert res.committed_audit_count == 1
    conn = connect(public_db)
    try:
        ref = get_refund(conn, "C-001")
        assert ref is not None
        assert int(ref["amount_vnd"]) == 35000
    finally:
        conn.close()
