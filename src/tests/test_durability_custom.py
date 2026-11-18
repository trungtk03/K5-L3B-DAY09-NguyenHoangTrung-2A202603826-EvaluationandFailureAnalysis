"""Custom tests for Durability & Crash by Luong Thi Hong Hanh (2A202603748)."""

import pytest

from lab8.db import connect
from lab8.durability import InjectedCrash, get_refund
from lab8.shapes.workflow import run_claim


def test_durability_crash_and_recovery_single_ledger_row(public_db):
    """Crash at after_effect_before_checkpoint then resume: exactly 1 refund."""
    with pytest.raises(InjectedCrash):
        run_claim(
            "C-012",
            seed=11,
            store_path=str(public_db),
            crash_at="after_effect_before_checkpoint",
        )
    # Resume run
    res = run_claim("C-012", seed=11, store_path=str(public_db))
    assert res.status == "resolved"
    assert res.committed_audit_count == 1
    conn = connect(public_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM refund_ledger WHERE claim_id = 'C-012'"
        ).fetchone()["n"]
        assert count == 1
    finally:
        conn.close()


def test_idempotency_second_call_keeps_original_state(public_db):
    res1 = run_claim("C-011", seed=11, store_path=str(public_db))
    res2 = run_claim("C-011", seed=11, store_path=str(public_db))
    assert res1.status == "resolved"
    assert res2.status == "resolved"
    assert res1.committed_audit_count == 1
    assert res2.committed_audit_count == 1
