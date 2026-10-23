"""Mock card-disputes domain toolkit.

A banking agent that helps customers inspect card transactions, open disputes
(chargebacks), and block cards. WRITE tools mutate ``self.db`` deterministically
so τ-bench-style outcome scoring (db_hash) is stable:

  - ``open_dispute`` derives a fixed dispute_id from the transaction id (no
    random uuid), so replaying the same action always yields the same state.
  - ``block_card`` is idempotent: blocking an already-blocked card succeeds
    without changing state, so it never needs a special "already blocked" path.

The ``disputable`` flag on each transaction precomputes the business rule
(posted, within the 60-day window, not already disputed) so both the sampler
(generation.yaml eligibility) and verify.py can gate on a single field.
"""

from __future__ import annotations

import copy
from typing import Any

from aieng.syn_data.synbench.schemas.tools import ToolSpec, ToolType

# Valid dispute reasons. The generator and agent must choose from this set so
# the stored reason (part of DB state) is comparable across oracle and agent.
DISPUTE_REASONS = ["fraud", "not_received", "duplicate_charge", "incorrect_amount"]


def get_tool_specs() -> list[ToolSpec]:
    """Declare the tools this domain exposes to the agent."""
    return [
        ToolSpec(
            name="find_customer_id",
            description=(
                "Look up a customer's customer_id by their full name. Verify the "
                "customer's identity by asking for their full name first, then call "
                "this before any card or transaction tool."
            ),
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="list_cards",
            description="List the cards belonging to a customer_id.",
            parameters={
                "type": "object",
                "properties": {"customer_id": {"type": "string"}},
                "required": ["customer_id"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="get_card",
            description="Get a card's details by card_id.",
            parameters={
                "type": "object",
                "properties": {"card_id": {"type": "string"}},
                "required": ["card_id"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="list_transactions",
            description="List transactions on a card_id.",
            parameters={
                "type": "object",
                "properties": {"card_id": {"type": "string"}},
                "required": ["card_id"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="get_transaction",
            description="Get a transaction's details by transaction_id.",
            parameters={
                "type": "object",
                "properties": {"transaction_id": {"type": "string"}},
                "required": ["transaction_id"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="get_dispute",
            description="Get a dispute's details by dispute_id.",
            parameters={
                "type": "object",
                "properties": {"dispute_id": {"type": "string"}},
                "required": ["dispute_id"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="open_dispute",
            description=(
                "Open a dispute (chargeback) on a transaction. Only posted "
                "transactions within the 60-day window that are not already "
                "disputed are eligible. 'reason' must be one of: "
                f"{', '.join(DISPUTE_REASONS)}."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string"},
                    "reason": {"type": "string", "enum": DISPUTE_REASONS},
                },
                "required": ["transaction_id", "reason"],
            },
            tool_type=ToolType.WRITE,
        ),
        ToolSpec(
            name="block_card",
            description=(
                "Block a card so it can no longer be used (e.g. lost or stolen). "
                "Confirm with the customer before blocking."
            ),
            parameters={
                "type": "object",
                "properties": {"card_id": {"type": "string"}},
                "required": ["card_id"],
            },
            tool_type=ToolType.WRITE,
        ),
    ]


class ToolKit:
    """Implementations of the card-disputes tools over a mutable database."""

    def __init__(self, db: dict[str, Any]):
        self.db = db

    # --- READ -----------------------------------------------------------------
    def find_customer_id(self, name: str) -> dict[str, Any]:
        """Look up a customer by full name."""
        needle = name.strip().lower()
        for cust in self.db["customers"].values():
            if str(cust.get("name", "")).strip().lower() == needle:
                return {
                    "customer_id": cust["customer_id"],
                    "name": cust["name"],
                    "email": cust.get("email"),
                }
        raise ValueError(f"Customer not found for name: {name}")

    def list_cards(self, customer_id: str) -> list[dict[str, Any]]:
        """Return every card belonging to ``customer_id``."""
        return [
            copy.deepcopy(c)
            for c in self.db["cards"].values()
            if c["customer_id"] == customer_id
        ]

    def get_card(self, card_id: str) -> dict[str, Any]:
        """Return the card with ``card_id``."""
        card = self.db["cards"].get(card_id)
        if card is None:
            raise ValueError(f"Card not found: {card_id}")
        return copy.deepcopy(card)

    def list_transactions(self, card_id: str) -> list[dict[str, Any]]:
        """Return every transaction on ``card_id``."""
        return [
            copy.deepcopy(t)
            for t in self.db["transactions"].values()
            if t["card_id"] == card_id
        ]

    def get_transaction(self, transaction_id: str) -> dict[str, Any]:
        """Return the transaction with ``transaction_id``."""
        txn = self.db["transactions"].get(transaction_id)
        if txn is None:
            raise ValueError(f"Transaction not found: {transaction_id}")
        return copy.deepcopy(txn)

    def get_dispute(self, dispute_id: str) -> dict[str, Any]:
        """Return the dispute with ``dispute_id``."""
        dispute = self.db["disputes"].get(dispute_id)
        if dispute is None:
            raise ValueError(f"Dispute not found: {dispute_id}")
        return copy.deepcopy(dispute)

    # --- WRITE ----------------------------------------------------------------
    def open_dispute(self, transaction_id: str, reason: str) -> dict[str, Any]:
        """Open a dispute on ``transaction_id`` if it is eligible."""
        if reason not in DISPUTE_REASONS:
            raise ValueError(
                f"Invalid reason: {reason}. Must be one of {DISPUTE_REASONS}."
            )
        txn = self.db["transactions"].get(transaction_id)
        if txn is None:
            raise ValueError(f"Transaction not found: {transaction_id}")
        if txn.get("disputed"):
            raise ValueError(f"Transaction already disputed: {transaction_id}")
        if not txn.get("disputable"):
            raise ValueError(
                f"Transaction {transaction_id} cannot be disputed "
                "(not posted, outside the 60-day window, or already disputed)."
            )

        dispute_id = f"disp_{transaction_id}"
        txn["disputed"] = True
        self.db["disputes"][dispute_id] = {
            "dispute_id": dispute_id,
            "transaction_id": transaction_id,
            "customer_id": txn["customer_id"],
            "reason": reason,
            "status": "open",
        }
        return {"dispute_id": dispute_id, "transaction_id": transaction_id, "status": "open"}

    def block_card(self, card_id: str) -> dict[str, Any]:
        """Block ``card_id``. Idempotent: blocking a blocked card is a no-op."""
        card = self.db["cards"].get(card_id)
        if card is None:
            raise ValueError(f"Card not found: {card_id}")
        card["status"] = "blocked"
        return {"card_id": card_id, "status": "blocked"}
