"""Credit-union domain checks for draft tasks.

The tools already enforce the policy limits (dispute window, waiver history,
card status), and verification replays the oracle strictly, so a draft that
breaks one of those fails replay. These checks cover what replay cannot see:

  - the oracle verifies the caller's identity, with details matching the DB,
    before any customer-scoped call, and later calls use that customer_id
  - each task type's required write actions are all present
  - at most one fee is waived per interaction (policy section 5)
"""

from __future__ import annotations

from aieng.syn_data.synbench.schemas.domain import DomainBundle
from aieng.syn_data.synbench.schemas.tasks import Task


CUSTOMER_SCOPED = {
    "get_account", "list_cards", "list_transactions", "get_transaction",
    "list_fees", "open_dispute", "waive_fee", "replace_card",
}

# Writes the policy requires for each write-type task.
REQUIRED_WRITES = {
    "transaction_dispute": {"open_dispute"},
    "fee_waiver": {"waive_fee"},
    "lost_card_report": {"replace_card"},
    # Policy section 7: flag the account (escalate) AND issue a replacement card.
    "fraud_escalation": {"escalate_to_human", "replace_card"},
}


def _matching_customer(domain: DomainBundle, args: dict) -> str | None:
    """Return the customer_id that verify_identity(args) would resolve to."""
    name = str(args.get("full_name", "")).strip().lower()
    last4 = str(args.get("account_last4", "")).strip()
    dob = args.get("date_of_birth")
    ssn = args.get("ssn_last4")
    if not dob and not ssn:
        return None
    accounts = domain.db.get("accounts", {}).values()
    for cust in domain.db.get("customers", {}).values():
        if str(cust["name"]).strip().lower() != name:
            continue
        acct = next((a for a in accounts if a["customer_id"] == cust["customer_id"]), None)
        if acct is None or acct["account_last4"] != last4:
            continue
        if dob and cust["date_of_birth"] != str(dob).strip():
            continue
        if ssn and cust["ssn_last4"] != str(ssn).strip():
            continue
        return cust["customer_id"]
    return None


def check_domain_rules(domain: DomainBundle, draft: Task) -> list[str]:
    """Domain-specific oracle invariants for draft tasks."""
    errors: list[str] = []
    actions = draft.evaluation_criteria.actions
    names = [a.name for a in actions]

    missing = REQUIRED_WRITES.get(draft.task_type, set()) - set(names)
    if missing:
        errors.append(f"{draft.task_type} oracle is missing required action(s): {sorted(missing)}")

    if names.count("waive_fee") > 1:
        errors.append("oracle waives more than one fee in a single interaction")

    verified_id: str | None = None
    for action in actions:
        if action.name == "verify_identity":
            verified_id = _matching_customer(domain, action.arguments)
            if verified_id is None:
                errors.append("verify_identity arguments do not match any customer in the DB")
        elif action.name in CUSTOMER_SCOPED or (
            action.name == "escalate_to_human" and action.arguments.get("customer_id")
        ):
            if verified_id is None:
                errors.append(f"{action.name} called before a successful verify_identity")
            elif action.arguments.get("customer_id") != verified_id:
                errors.append(
                    f"{action.name} uses customer_id {action.arguments.get('customer_id')!r}, "
                    f"not the verified {verified_id!r}"
                )
    return errors
