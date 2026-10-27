"""Mock credit-union credit-card servicing toolkit.

Tools for a card-servicing agent: verify identity, read account data, and make
four kinds of changes (open a dispute, waive a fee, replace a card, escalate).

Design rules that keep outcome-based (db_hash) scoring sound:

  - Verification is stateless. ``verify_identity`` returns a ``customer_id``;
    every customer-scoped tool requires it and checks ownership. An agent that
    never verifies has no ``customer_id`` and cannot read or change anything,
    and an environment copy mid-conversation cannot lose "verified" state.
  - WRITE tools are deterministic: ids are derived from their inputs (no uuid),
    and "today" comes from ``db["meta"]["today"]`` rather than the wall clock.
  - Two WRITE tools never write the same field, so the final state does not
    depend on the order the agent calls them in.
  - Policy limits (60-day dispute window, fee-waiver windows) are enforced here
    as well as described in policy.md, so an agent that ignores the policy gets
    a tool error and no state change instead of a corrupted database.
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

from aieng.syn_data.synbench.schemas.tools import ToolSpec, ToolType


DISPUTE_WINDOW_DAYS = 60
LATE_FEE_WAIVER_WINDOW_DAYS = 365  # one late-fee waiver per 12 months
WAIVABLE_FEE_TYPES = {"late_payment", "returned_payment"}

DISPUTE_REASONS = [
    "unrecognized_charge",
    "incorrect_amount",
    "duplicate_charge",
    "not_received",
]
WAIVER_REASONS = ["first_time_request", "payment_error", "technical_issue"]
REPLACE_REASONS = ["lost", "stolen", "compromised"]
ESCALATION_REASONS = [
    "suspected_fraud",
    "legal_threat",
    "supervisor_request",
    "out_of_policy_request",
]


def get_tool_specs() -> list[ToolSpec]:
    """Declare the tools this domain exposes to the agent."""
    customer_id = {"type": "string", "description": "customer_id from verify_identity"}
    return [
        ToolSpec(
            name="verify_identity",
            description=(
                "Verify a caller's identity. Requires their full name, the last 4 "
                "digits of their account number, and EITHER their date of birth "
                "(YYYY-MM-DD) OR the last 4 digits of their SSN. On success returns "
                "the customer_id needed by every other account tool. Fails with a "
                "generic error if the details do not match."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "full_name": {"type": "string"},
                    "account_last4": {"type": "string"},
                    "date_of_birth": {"type": "string", "description": "YYYY-MM-DD"},
                    "ssn_last4": {"type": "string"},
                },
                "required": ["full_name", "account_last4"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="get_account",
            description=(
                "Get the credit card account: current balance, credit limit, "
                "available credit, minimum payment, payment due date, and flags."
            ),
            parameters={
                "type": "object",
                "properties": {"customer_id": customer_id},
                "required": ["customer_id"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="list_cards",
            description="List the customer's cards (card_id, last four digits, status).",
            parameters={
                "type": "object",
                "properties": {"customer_id": customer_id},
                "required": ["customer_id"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="list_transactions",
            description=(
                "List the customer's transactions, including statement_date and "
                "days_since_statement for each."
            ),
            parameters={
                "type": "object",
                "properties": {"customer_id": customer_id},
                "required": ["customer_id"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="get_transaction",
            description=(
                "Get one transaction, including statement_date, "
                "days_since_statement, and whether it is already disputed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "customer_id": customer_id,
                    "transaction_id": {"type": "string"},
                },
                "required": ["customer_id", "transaction_id"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="list_fees",
            description=(
                "List the customer's fees, including type, amount, date, and "
                "whether and when each was waived (needed to check waiver history)."
            ),
            parameters={
                "type": "object",
                "properties": {"customer_id": customer_id},
                "required": ["customer_id"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="open_dispute",
            description=(
                "Open a dispute on a transaction. Only allowed within 60 days of "
                "the statement date on which the transaction first appeared, and "
                "only if it is not already disputed. 'reason' must be one of: "
                f"{', '.join(DISPUTE_REASONS)}."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "customer_id": customer_id,
                    "transaction_id": {"type": "string"},
                    "reason": {"type": "string", "enum": DISPUTE_REASONS},
                },
                "required": ["customer_id", "transaction_id", "reason"],
            },
            tool_type=ToolType.WRITE,
        ),
        ToolSpec(
            name="waive_fee",
            description=(
                "Waive one late payment or returned payment fee and credit it back "
                "to the balance. Other fee types need supervisor authorization and "
                "are rejected. 'reason' documents why and must be one of: "
                f"{', '.join(WAIVER_REASONS)}."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "customer_id": customer_id,
                    "fee_id": {"type": "string"},
                    "reason": {"type": "string", "enum": WAIVER_REASONS},
                },
                "required": ["customer_id", "fee_id", "reason"],
            },
            tool_type=ToolType.WRITE,
        ),
        ToolSpec(
            name="replace_card",
            description=(
                "Replace a card that is lost, stolen, or compromised: the old card "
                "stops working, a replacement is issued, and the account is "
                f"flagged. 'reason' must be one of: {', '.join(REPLACE_REASONS)}."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "customer_id": customer_id,
                    "card_id": {"type": "string"},
                    "reason": {"type": "string", "enum": REPLACE_REASONS},
                },
                "required": ["customer_id", "card_id", "reason"],
            },
            tool_type=ToolType.WRITE,
        ),
        ToolSpec(
            name="escalate_to_human",
            description=(
                "Hand the case to a human agent. Use for suspected fraud and for "
                "anything policy says must be escalated. 'customer_id' is optional "
                "because some escalations happen before identity is verified. "
                f"'reason' must be one of: {', '.join(ESCALATION_REASONS)}. "
                "Escalating as suspected_fraud also flags the account."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "enum": ESCALATION_REASONS},
                    "customer_id": customer_id,
                },
                "required": ["reason"],
            },
            tool_type=ToolType.WRITE,
        ),
    ]


class ToolKit:
    """Implementations of the credit-union tools over a mutable database."""

    def __init__(self, db: dict[str, Any]):
        self.db = db

    # --- helpers --------------------------------------------------------------
    def _today(self) -> date:
        return date.fromisoformat(self.db["meta"]["today"])

    def _account(self, customer_id: str) -> dict[str, Any]:
        for acct in self.db["accounts"].values():
            if acct["customer_id"] == customer_id:
                return acct
        raise ValueError(
            "Customer not found. Verify the caller's identity with verify_identity first."
        )

    def _owned(self, table: str, record_id: str, customer_id: str) -> dict[str, Any]:
        self._account(customer_id)
        record = self.db[table].get(record_id)
        if record is None or record.get("customer_id") != customer_id:
            # Same message for "missing" and "someone else's": never confirm
            # that another customer's record exists.
            raise ValueError(f"{record_id} not found for this customer")
        return record

    def _txn_view(self, txn: dict[str, Any]) -> dict[str, Any]:
        view = copy.deepcopy(txn)
        view["days_since_statement"] = (
            self._today() - date.fromisoformat(txn["statement_date"])
        ).days
        return view

    # --- READ -----------------------------------------------------------------
    def verify_identity(
        self,
        full_name: str,
        account_last4: str,
        date_of_birth: str | None = None,
        ssn_last4: str | None = None,
    ) -> dict[str, Any]:
        """Check name + account last 4 + (date of birth or SSN last 4)."""
        if not date_of_birth and not ssn_last4:
            raise ValueError(
                "Verification needs full name, account last 4, and either date "
                "of birth or SSN last 4."
            )
        needle = full_name.strip().lower()
        for cust in self.db["customers"].values():
            if str(cust["name"]).strip().lower() != needle:
                continue
            acct = next(
                (
                    a
                    for a in self.db["accounts"].values()
                    if a["customer_id"] == cust["customer_id"]
                ),
                None,
            )
            if acct is None or acct["account_last4"] != str(account_last4).strip():
                continue
            checks = []
            if date_of_birth:
                checks.append(cust["date_of_birth"] == date_of_birth.strip())
            if ssn_last4:
                checks.append(cust["ssn_last4"] == str(ssn_last4).strip())
            if all(checks):
                return {
                    "verified": True,
                    "customer_id": cust["customer_id"],
                    "account_id": acct["account_id"],
                    "name": cust["name"],
                }
        raise ValueError("Verification failed. The details provided do not match our records.")

    def get_account(self, customer_id: str) -> dict[str, Any]:
        """Return the customer's credit card account."""
        return copy.deepcopy(self._account(customer_id))

    def list_cards(self, customer_id: str) -> list[dict[str, Any]]:
        """Return every card on the customer's account."""
        self._account(customer_id)
        return [
            copy.deepcopy(c)
            for c in self.db["cards"].values()
            if c["customer_id"] == customer_id
        ]

    def list_transactions(self, customer_id: str) -> list[dict[str, Any]]:
        """Return every transaction on the customer's account."""
        self._account(customer_id)
        return [
            self._txn_view(t)
            for t in self.db["transactions"].values()
            if t["customer_id"] == customer_id
        ]

    def get_transaction(self, customer_id: str, transaction_id: str) -> dict[str, Any]:
        """Return one of the customer's transactions."""
        return self._txn_view(self._owned("transactions", transaction_id, customer_id))

    def list_fees(self, customer_id: str) -> list[dict[str, Any]]:
        """Return every fee on the customer's account."""
        self._account(customer_id)
        return [
            copy.deepcopy(f)
            for f in self.db["fees"].values()
            if f["customer_id"] == customer_id
        ]

    # --- WRITE ----------------------------------------------------------------
    def open_dispute(
        self, customer_id: str, transaction_id: str, reason: str
    ) -> dict[str, Any]:
        """Open a dispute if the transaction is inside the 60-day window."""
        if reason not in DISPUTE_REASONS:
            raise ValueError(f"Invalid reason: {reason}. Must be one of {DISPUTE_REASONS}.")
        txn = self._owned("transactions", transaction_id, customer_id)
        if txn.get("disputed"):
            raise ValueError(f"Transaction already disputed: {transaction_id}")
        days = self._txn_view(txn)["days_since_statement"]
        if days > DISPUTE_WINDOW_DAYS:
            raise ValueError(
                f"Transaction {transaction_id} is {days} days past its statement "
                f"date; disputes must be opened within {DISPUTE_WINDOW_DAYS} days."
            )
        dispute_id = f"disp_{transaction_id}"
        txn["disputed"] = True
        self.db.setdefault("disputes", {})[dispute_id] = {
            "dispute_id": dispute_id,
            "transaction_id": transaction_id,
            "customer_id": customer_id,
            "reason": reason,
            "status": "open",
        }
        return {"dispute_id": dispute_id, "status": "open"}

    def waive_fee(self, customer_id: str, fee_id: str, reason: str) -> dict[str, Any]:
        """Waive a late/returned payment fee if the waiver history allows it."""
        if reason not in WAIVER_REASONS:
            raise ValueError(f"Invalid reason: {reason}. Must be one of {WAIVER_REASONS}.")
        fee = self._owned("fees", fee_id, customer_id)
        if fee["waived"]:
            raise ValueError(f"Fee already waived: {fee_id}")
        if fee["type"] not in WAIVABLE_FEE_TYPES:
            raise ValueError(
                f"{fee['type']} fees cannot be waived by an agent; supervisor "
                "authorization is required."
            )
        today = self._today()
        prior = [
            date.fromisoformat(f["waived_on"])
            for f in self.db["fees"].values()
            if f["customer_id"] == customer_id
            and f["fee_id"] != fee_id
            and f["type"] == fee["type"]
            and f["waived"]
        ]
        if fee["type"] == "late_payment" and any(
            (today - d).days <= LATE_FEE_WAIVER_WINDOW_DAYS for d in prior
        ):
            raise ValueError("A late payment fee was already waived within the past 12 months.")
        if fee["type"] == "returned_payment" and any(d.year == today.year for d in prior):
            raise ValueError("A returned payment fee was already waived this calendar year.")

        fee["waived"] = True
        fee["waived_on"] = today.isoformat()
        fee["waiver_reason"] = reason
        acct = self._account(customer_id)
        acct["current_balance"] = round(acct["current_balance"] - fee["amount"], 2)
        acct["available_credit"] = round(acct["available_credit"] + fee["amount"], 2)
        return {"fee_id": fee_id, "status": "waived"}

    def replace_card(self, customer_id: str, card_id: str, reason: str) -> dict[str, Any]:
        """Retire an active card, issue a replacement, and flag the account."""
        if reason not in REPLACE_REASONS:
            raise ValueError(f"Invalid reason: {reason}. Must be one of {REPLACE_REASONS}.")
        card = self._owned("cards", card_id, customer_id)
        if card["status"] != "active":
            raise ValueError(f"Card {card_id} is not active (status: {card['status']}).")
        new_id = f"{card_id}_repl"
        card["status"] = "replaced"
        card["replacement_reason"] = reason
        self.db["cards"][new_id] = {
            "card_id": new_id,
            "customer_id": customer_id,
            "last_four": "pending",
            "status": "issued",
        }
        self._account(customer_id)["card_replacement_reason"] = reason
        return {"old_card_id": card_id, "replacement_card_id": new_id, "status": "issued"}

    def escalate_to_human(
        self, reason: str, customer_id: str | None = None
    ) -> dict[str, Any]:
        """Open an escalation; suspected fraud also flags the account."""
        if reason not in ESCALATION_REASONS:
            raise ValueError(f"Invalid reason: {reason}. Must be one of {ESCALATION_REASONS}.")
        acct = self._account(customer_id) if customer_id else None
        escalation_id = f"esc_{customer_id or 'unknown'}_{reason}"
        self.db.setdefault("escalations", {})[escalation_id] = {
            "escalation_id": escalation_id,
            "customer_id": customer_id,
            "reason": reason,
            "status": "open",
        }
        if acct is not None and reason == "suspected_fraud":
            acct["fraud_flag"] = True
        return {"escalation_id": escalation_id, "status": "open"}
