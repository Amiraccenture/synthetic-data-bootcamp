"""Card-disputes domain-specific checks for draft tasks.

Runs during verification on every generated draft. Returns human-readable error
strings; a non-empty list rejects the draft. These rules keep generated oracles
consistent with policy.md and the guards in tools.py.
"""

from __future__ import annotations

from aieng.syn_data.synbench.schemas.domain import DomainBundle
from aieng.syn_data.synbench.schemas.tasks import Task

VALID_REASONS = {"fraud", "not_received", "duplicate_charge", "incorrect_amount"}


def check_domain_rules(domain: DomainBundle, draft: Task) -> list[str]:
    """Domain-specific oracle invariants for draft tasks."""
    errors: list[str] = []
    transactions = domain.db.get("transactions", {})

    for action in draft.evaluation_criteria.actions:
        if action.name != "open_dispute":
            continue
        tid = action.arguments.get("transaction_id")
        reason = action.arguments.get("reason")
        txn = transactions.get(tid, {})
        if not txn:
            errors.append(f"open_dispute on unknown transaction: {tid}")
            continue
        if not txn.get("disputable"):
            errors.append(f"open_dispute on non-disputable transaction: {tid}")
        if txn.get("disputed"):
            errors.append(f"open_dispute on already-disputed transaction: {tid}")
        if reason not in VALID_REASONS:
            errors.append(f"open_dispute with invalid reason: {reason!r}")

    return errors
