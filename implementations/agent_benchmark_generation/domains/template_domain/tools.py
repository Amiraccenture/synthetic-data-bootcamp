"""Template domain toolkit.

TODO: Rename tools and rewrite ToolKit methods to mirror YOUR agent's real
tool surface. Two hard rules make outcome-based scoring work:

  1. WRITE tools must mutate ``self.db`` *deterministically* — the same action
     on the same starting state must always produce the same ending state
     (``db_hash`` compares final state, so any nondeterminism breaks scoring).
  2. READ tools must not mutate state. Mark each tool READ or WRITE correctly:
     the verifier uses ``tool_type`` to enforce ``task_types.yaml`` allow_write.

Raise ValueError for recoverable problems (not found, bad status). The tool
loop returns the error text to the model so it can recover — it is not fatal.
"""

from __future__ import annotations

import copy
from typing import Any

from aieng.syn_data.synbench.schemas.tools import ToolSpec, ToolType


def get_tool_specs() -> list[ToolSpec]:
    """Declare the tools this domain exposes to the agent."""
    return [
        ToolSpec(
            name="find_customer_id",
            description=(
                "Look up a customer's customer_id by their full name. "
                "Ask the customer for their name first, then call this before "
                "list_records or any record mutation."
            ),
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="get_record",
            description="Get record details by record_id",
            parameters={
                "type": "object",
                "properties": {"record_id": {"type": "string"}},
                "required": ["record_id"],
            },
            tool_type=ToolType.READ,
        ),
        ToolSpec(
            name="list_records",
            description="List records for a customer_id",
            parameters={
                "type": "object",
                "properties": {"customer_id": {"type": "string"}},
                "required": ["customer_id"],
            },
            tool_type=ToolType.READ,
        ),
        # TODO: replace with your real WRITE actions.
        ToolSpec(
            name="update_record",
            description="Update the detail field on a record",
            parameters={
                "type": "object",
                "properties": {
                    "record_id": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["record_id", "detail"],
            },
            tool_type=ToolType.WRITE,
        ),
        ToolSpec(
            name="close_record",
            description="Close an open record",
            parameters={
                "type": "object",
                "properties": {"record_id": {"type": "string"}},
                "required": ["record_id"],
            },
            tool_type=ToolType.WRITE,
        ),
    ]


class ToolKit:
    """Implementations of the template tools over a mutable database.

    There must be one method per tool name declared in ``get_tool_specs()``.
    """

    def __init__(self, db: dict[str, Any]):
        self.db = db

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

    def get_record(self, record_id: str) -> dict[str, Any]:
        """Return the record with ``record_id``."""
        record = self.db["records"].get(record_id)
        if record is None:
            raise ValueError(f"Record not found: {record_id}")
        return copy.deepcopy(record)

    def list_records(self, customer_id: str) -> list[dict[str, Any]]:
        """Return every record belonging to ``customer_id``."""
        return [
            copy.deepcopy(r)
            for r in self.db["records"].values()
            if r["customer_id"] == customer_id
        ]

    def update_record(self, record_id: str, detail: str) -> dict[str, Any]:
        """Set a new detail value on ``record_id``."""
        record = self.db["records"].get(record_id)
        if record is None:
            raise ValueError(f"Record not found: {record_id}")
        record["detail"] = detail
        return {"record_id": record_id, "detail": detail}

    def close_record(self, record_id: str) -> dict[str, Any]:
        """Close ``record_id``, which must still be open."""
        record = self.db["records"].get(record_id)
        if record is None:
            raise ValueError(f"Record not found: {record_id}")
        # TODO: this guard mirrors policy rule 5 and verify.py — keep them in sync.
        if record["status"] != "open":
            raise ValueError(f"Cannot close record with status: {record['status']}")
        record["status"] = "closed"
        return {"record_id": record_id, "status": "closed"}
