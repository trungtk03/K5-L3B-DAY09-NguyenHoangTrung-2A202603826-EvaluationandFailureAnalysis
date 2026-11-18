"""Custom tests for Shape A (Workflow) by Nguyen Hoang Trung (2A202603826)."""

import pytest

from lab8.db import connect
from lab8.shapes.workflow import run_claim
from tests.conftest import BY_ID


def test_workflow_nonexistent_claim_fails_gracefully(public_db):
    result = run_claim("C-NONEXISTENT", seed=11, store_path=str(public_db))
    assert result.status == "failed"
    assert result.error_reason == "unknown_claim"
    assert result.proposal_amount == 0


def test_workflow_missing_order_needs_info(public_db):
    result = run_claim("C-004", seed=11, store_path=str(public_db))
    assert result.status == "needs_info"
    assert result.error_reason == "missing_order_id"
    assert result.proposal_amount == 0


def test_workflow_escalates_unowned_order(public_db):
    result = run_claim("C-005", seed=11, store_path=str(public_db))
    assert result.status == "escalated"
    assert result.proposal_amount == 0
