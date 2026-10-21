"""Template domain-specific checks for draft tasks.

``check_domain_rules`` runs during verification (notebook 2) on every generated
draft task. Return a list of human-readable error strings; a non-empty list
rejects the draft. Use it to encode business invariants the oracle must respect
that generic task-type/write checks can't catch on their own.

Keep these rules in sync with policy.md and the guards in tools.py.
"""

from __future__ import annotations

from aieng.syn_data.synbench.schemas.domain import DomainBundle
from aieng.syn_data.synbench.schemas.tasks import Task


def check_domain_rules(domain: DomainBundle, draft: Task) -> list[str]:
    """Domain-specific oracle invariants for draft tasks."""
    errors: list[str] = []
    task_type = draft.task_type

    # Example: a 'close' oracle may only close records that are currently open.
    # TODO: replace with your own invariants (ownership, amount limits, etc.).
    if task_type == "close":
        close_actions = [
            a for a in draft.evaluation_criteria.actions if a.name == "close_record"
        ]
        for a in close_actions:
            rid = a.arguments.get("record_id")
            record = domain.db.get("records", {}).get(rid, {})
            if record.get("status") != "open":
                errors.append(f"close_record on non-open record: {rid}")

    return errors
