"""Shape B — one ReAct agent. Student work.

Signature (do not change):

    run_claim(claim_id, *, seed, store_path, crash_at=None) -> RunResult
"""

from __future__ import annotations

import sqlite3
from typing import Any

from lab8.db import connect
from lab8.durability import InjectedCrash, issue_refund
from lab8.mock_llm import complete
from lab8.runtime import run_react
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish
from lab8.tools import get_claim_view, tool_cost
from lab8.trace import Trace


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _run(conn, claim_id, seed=seed, crash_at=crash_at)
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, claim_id: str, *, seed: int, crash_at: str | None) -> RunResult:
    budget = Budget()
    run_id = make_run_id("single", claim_id, seed)
    trace = Trace(run_id)

    claim_view = get_claim_view(conn, claim_id)
    budget.add_tool(tool_cost())

    if not claim_view.get("found"):
        trace.add("error", {"reason": "unknown_claim"})
        return finish(
            conn,
            shape="single",
            claim_id=claim_id,
            seed=seed,
            status="failed",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason="unknown_claim",
        )

    # ReAct decide function
    def decide(seen: dict[str, Any]) -> dict[str, Any]:
        complete(budget, seed=seed, purpose="decide", prompt=str(seen.get("last_tool", "start")))
        claim = seen.get("claim") or {}
        if not claim.get("order_id"):
            return {"final": {"status": "needs_info", "error_reason": "missing_order_id"}}

        last_tool = seen.get("last_tool")
        if last_tool is None:
            return {
                "tool": "lookup_order",
                "args": {"order_id": claim.get("order_id"), "principal_id": claim.get("principal_id")},
            }

        if last_tool == "lookup_order":
            order_view = seen.get("last_result") or {}
            if not order_view.get("visible"):
                return {"final": {"status": "escalated", "error_reason": order_view.get("reason")}}
            return {"tool": "compute_compensation", "args": {"order": order_view["order"]}}

        if last_tool == "compute_compensation":
            quote_payload = seen.get("last_result") or {}
            amount = int(quote_payload.get("amount_vnd", 0))
            if amount <= 0:
                return {
                    "final": {
                        "status": "denied",
                        "proposal_amount": 0,
                        "error_reason": quote_payload.get("reason"),
                        "quote_payload": quote_payload,
                    }
                }
            return {
                "final": {
                    "status": "resolved",
                    "proposal_amount": amount,
                    "quote_payload": quote_payload,
                }
            }

        return {"final": {"status": "failed", "error_reason": "unexpected_step"}}

    react_outcome = run_react(
        conn,
        budget,
        observation={"claim": claim_view},
        decide=decide,
        max_steps=8,
        worker=True,
    )

    if react_outcome.get("stopped") == "step_cap":
        trace.add("error", {"reason": "step_cap"})
        return finish(
            conn,
            shape="single",
            claim_id=claim_id,
            seed=seed,
            status="failed",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason="step_cap",
        )

    final = react_outcome.get("final") or {}
    status = final.get("status", "failed")

    if status == "needs_info":
        complete(budget, seed=seed, purpose="draft", prompt="needs_info")
        trace.add("decision", {"status": "needs_info"})
        return finish(
            conn,
            shape="single",
            claim_id=claim_id,
            seed=seed,
            status="needs_info",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=final.get("error_reason"),
        )

    if status == "escalated":
        complete(budget, seed=seed, purpose="draft", prompt="escalated")
        trace.add("decision", {"status": "escalated"})
        return finish(
            conn,
            shape="single",
            claim_id=claim_id,
            seed=seed,
            status="escalated",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=final.get("error_reason"),
        )

    if status == "denied":
        quote_payload = final.get("quote_payload") or {}
        trace.add("quote", quote_payload)
        trace.add("decision", {"status": "denied", "reason": final.get("error_reason")})
        return finish(
            conn,
            shape="single",
            claim_id=claim_id,
            seed=seed,
            status="denied",
            proposal_amount=0,
            budget=budget,
            trace=trace,
            error_reason=final.get("error_reason"),
        )

    # status is resolved candidate (quote > 0)
    proposal = int(final.get("proposal_amount", 0))
    quote_payload = final.get("quote_payload") or {}
    trace.add("quote", quote_payload)
    complete(budget, seed=seed, purpose="draft", prompt=f"proposal={proposal}")

    try:
        outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise

    if not outcome["ok"]:
        res_status = "failed" if outcome["conflict"] else "denied"
        trace.add("decision", {"status": res_status, "reason": outcome["reason"]})
        return finish(
            conn,
            shape="single",
            claim_id=claim_id,
            seed=seed,
            status=res_status,
            proposal_amount=proposal,
            budget=budget,
            trace=trace,
            error_reason=outcome["reason"],
        )

    trace.add("decision", {"status": "resolved"})
    return finish(
        conn,
        shape="single",
        claim_id=claim_id,
        seed=seed,
        status="resolved",
        proposal_amount=proposal,
        budget=budget,
        trace=trace,
        error_reason=None,
    )
