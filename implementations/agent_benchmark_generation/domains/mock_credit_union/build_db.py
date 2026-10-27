"""Build ``db.json`` for the mock credit-union domain.

Run from anywhere:  python build_db.py

The customer table below is the single source of truth. Each customer is an
"archetype" chosen so every task type has several eligible customers and the
refusal cases sit on both sides of their rule (e.g. a transaction 58 days past
its statement is disputable, one at 62 days is not).

``case_index`` is generation-only: the sampler reads it, the tools never do, so
it cannot leak answers to the agent. Eligibility in it is computed by running
the real ToolKit guards on a copy of the database, so it cannot drift from what
the tools actually allow.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


HERE = Path(__file__).parent
TODAY = date(2026, 10, 27)

# (merchant, amount, stmt_days_ago, txn_offset_days, already_disputed)
# stmt_days_ago = days since the statement the charge first appeared on.
# Keep every balance under 1,000 so numbers have no thousands separators and
# substring matching on communicate_info stays robust.
CUSTOMERS: list[dict[str, Any]] = [
    dict(
        id="20417", name="Maya Patel", dob="1988-02-14", ssn="3921", acct="4821",
        limit=3000.0, balance=412.37, due_in=12, cards=[("7305", "active")],
        txns=[("GreenLeaf Grocers", 86.42, 12, 6), ("Metro Transit", 34.00, 20, 3),
              ("BrightBooks", 129.99, 41, 9)],
        fees=[],
    ),
    dict(
        id="31588", name="Daniel Okafor", dob="1979-09-03", ssn="5530", acct="6102",
        limit=2500.0, balance=238.90, due_in=5, cards=[("2284", "active")],
        txns=[("PixelPlay Games", 59.99, 18, 4), ("HomeNest Furniture", 310.00, 74, 10)],
        fees=[],
    ),
    dict(
        id="44026", name="Priya Raman", dob="1992-12-30", ssn="8174", acct="3359",
        limit=4000.0, balance=655.10, due_in=3, cards=[("9911", "active")],
        txns=[("Sunrise Pharmacy", 23.15, 9, 2), ("CloudNine Hosting", 14.99, 30, 5)],
        fees=[("late_payment", 29.00, 20, None)],
    ),
    dict(
        id="52371", name="Tomás Rivera", dob="1983-06-18", ssn="2046", acct="7740",
        limit=3500.0, balance=502.66, due_in=9, cards=[("1357", "active")],
        txns=[("Corner Auto Parts", 112.30, 15, 3)],
        # Late fee waived 148 days ago -> a new late fee is blocked (12-month rule).
        fees=[("late_payment", 29.00, 10, None), ("late_payment", 29.00, 150, 148)],
    ),
    dict(
        id="60845", name="Hannah Lindqvist", dob="1975-04-09", ssn="6618", acct="2913",
        limit=3000.0, balance=301.45, due_in=14, cards=[("5568", "active")],
        txns=[("Nordic Outfitters", 148.00, 25, 6)],
        # Returned-payment fee waived 118 days ago (same calendar year) -> blocked.
        fees=[("returned_payment", 35.00, 14, None), ("returned_payment", 35.00, 120, 118)],
    ),
    dict(
        id="67199", name="Marcus Bell", dob="1990-01-22", ssn="1493", acct="8826",
        limit=5000.0, balance=744.20, due_in=7, cards=[("6672", "active")],
        txns=[("Summit Hardware", 203.75, 33, 7)],
        # Earlier late-fee waiver was 428 days ago -> outside 12 months, so eligible.
        fees=[("late_payment", 29.00, 12, None), ("late_payment", 29.00, 430, 428)],
    ),
    dict(
        id="71530", name="Sofia Alvarez", dob="1986-11-27", ssn="7702", acct="1675",
        limit=5000.0, balance=889.00, due_in=10, cards=[("4410", "active"), ("9027", "active")],
        txns=[("Casa Verde Market", 64.10, 8, 2), ("TravelNow Airfare", 412.00, 22, 12, False, 1)],
        # Over-limit fees can never be waived by an agent (supervisor only).
        fees=[("over_limit", 29.00, 40, None)],
    ),
    dict(
        id="78264", name="Kenji Watanabe", dob="1981-08-15", ssn="4385", acct="5048",
        limit=2500.0, balance=177.52, due_in=6, cards=[("3046", "active")],
        txns=[("Harbor Sushi", 71.20, 16, 3), ("Digital Depot", 249.99, 88, 14)],
        fees=[("late_payment", 29.00, 18, None)],
    ),
    dict(
        id="83912", name="Grace Thompson", dob="1994-03-05", ssn="9051", acct="9387",
        limit=2000.0, balance=366.80, due_in=11, cards=[("8120", "active")],
        txns=[("StreamFlix", 15.99, 27, 5, True), ("Peak Fitness", 45.00, 27, 8)],
        fees=[],
    ),
    dict(
        id="90077", name="Omar Haddad", dob="1977-10-12", ssn="2860", acct="6631",
        limit=3000.0, balance=528.33, due_in=4, cards=[("4752", "active")],
        # 58 days is inside the window, 62 is outside: the boundary pair.
        txns=[("Delta Bistro", 98.40, 58, 9), ("Wellness Spa", 175.00, 62, 11)],
        fees=[],
    ),
    dict(
        id="95408", name="Beatrice Moreau", dob="1968-07-29", ssn="3317", acct="1204",
        limit=4000.0, balance=691.75, due_in=8, cards=[("2599", "active")],
        txns=[("Lumiere Boutique", 218.60, 19, 4)],
        fees=[("returned_payment", 35.00, 11, None)],
    ),
    dict(
        id="99650", name="Liam O'Connor", dob="1999-05-16", ssn="5894", acct="7519",
        limit=1500.0, balance=95.10, due_in=13, cards=[("6038", "active")],
        txns=[("Quick Fuel Stop", 42.00, 6, 1), ("Online Electronics", 389.00, 6, 2),
              ("Gadget Galaxy", 249.00, 6, 3)],
        fees=[],
    ),
]


def _load_toolkit() -> Any:
    spec = importlib.util.spec_from_file_location("cu_tools", HERE / "tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ToolKit


def build_base() -> dict[str, Any]:
    """Build every table except the generation-only ``case_index``."""
    db: dict[str, Any] = {
        "meta": {"today": TODAY.isoformat()},
        "customers": {}, "accounts": {}, "cards": {}, "transactions": {},
        "fees": {}, "disputes": {}, "escalations": {},
    }
    for c in CUSTOMERS:
        assert c["balance"] < 1000, f"{c['name']}: keep balances under 1,000"
        cid = f"cu_{c['id']}"
        acct_id = f"acct_{c['id']}"
        db["customers"][cid] = {
            "customer_id": cid, "name": c["name"],
            "date_of_birth": c["dob"], "ssn_last4": c["ssn"],
        }
        db["accounts"][acct_id] = {
            "account_id": acct_id, "customer_id": cid, "account_last4": c["acct"],
            "status": "current", "credit_limit": c["limit"],
            "current_balance": c["balance"],
            "available_credit": round(c["limit"] - c["balance"], 2),
            # Policy: 2.00% of the new balance or $25.00, whichever is greater.
            "minimum_payment": round(max(c["balance"] * 0.02, 25.0), 2),
            "payment_due_date": (TODAY + timedelta(days=c["due_in"])).isoformat(),
            "past_due_amount": 0.0,
        }
        card_ids = []
        for k, (last4, status) in enumerate(c["cards"], start=1):
            card_id = f"card_{c['id']}_{k}"
            card_ids.append(card_id)
            db["cards"][card_id] = {
                "card_id": card_id, "customer_id": cid,
                "last_four": last4, "status": status,
            }
        for k, spec in enumerate(c["txns"], start=1):
            merchant, amount, stmt_ago, offset = spec[:4]
            disputed = spec[4] if len(spec) > 4 else False
            card_idx = spec[5] if len(spec) > 5 else 0
            stmt_date = TODAY - timedelta(days=stmt_ago)
            tid = f"txn_{c['id']}_{k}"
            db["transactions"][tid] = {
                "transaction_id": tid, "customer_id": cid, "account_id": acct_id,
                "card_id": card_ids[card_idx], "merchant": merchant, "amount": amount,
                "date": (stmt_date - timedelta(days=offset)).isoformat(),
                "statement_date": stmt_date.isoformat(),
                "status": "posted", "disputed": disputed,
            }
            if disputed:
                did = f"disp_{tid}"
                db["disputes"][did] = {
                    "dispute_id": did, "transaction_id": tid, "customer_id": cid,
                    "reason": "duplicate_charge", "status": "open",
                }
        for k, (ftype, amount, fee_ago, waived_ago) in enumerate(c["fees"], start=1):
            fid = f"fee_{c['id']}_{k}"
            waived = waived_ago is not None
            db["fees"][fid] = {
                "fee_id": fid, "customer_id": cid, "account_id": acct_id,
                "type": ftype, "amount": amount,
                "date": (TODAY - timedelta(days=fee_ago)).isoformat(),
                "waived": waived,
                "waived_on": (TODAY - timedelta(days=waived_ago)).isoformat() if waived else None,
                "waiver_reason": "first_time_request" if waived else None,
            }
    return db


def _can(db: dict[str, Any], toolkit_cls: Any, method: str, **kwargs: Any) -> bool:
    """True if the real tool would accept this call (run on a throwaway copy)."""
    try:
        getattr(toolkit_cls(copy.deepcopy(db)), method)(**kwargs)
    except ValueError:
        return False
    return True


def add_case_index(db: dict[str, Any]) -> None:
    """Add the generation-only ``case_index`` table (never read by any tool)."""
    toolkit_cls = _load_toolkit()
    kit = toolkit_cls(db)
    db["case_index"] = {}
    for cid, cust in db["customers"].items():
        acct = next(a for a in db["accounts"].values() if a["customer_id"] == cid)
        txns = [t for t in db["transactions"].values() if t["customer_id"] == cid]
        fees = [f for f in db["fees"].values() if f["customer_id"] == cid]

        disputable, stale = [], []
        for t in txns:
            view = kit._txn_view(t)
            brief = {
                "transaction_id": t["transaction_id"], "merchant": t["merchant"],
                "amount": t["amount"], "days_since_statement": view["days_since_statement"],
            }
            if _can(db, toolkit_cls, "open_dispute", customer_id=cid,
                    transaction_id=t["transaction_id"], reason="incorrect_amount"):
                disputable.append(brief)
            elif not t["disputed"]:
                stale.append(brief)

        waivable, blocked = [], []
        for f in fees:
            if f["waived"] or f["type"] not in ("late_payment", "returned_payment"):
                continue
            brief = {"fee_id": f["fee_id"], "type": f["type"], "amount": f["amount"]}
            if _can(db, toolkit_cls, "waive_fee", customer_id=cid,
                    fee_id=f["fee_id"], reason="first_time_request"):
                waivable.append(brief)
            else:
                blocked.append(brief)

        active_cards = [
            {"card_id": c["card_id"], "last_four": c["last_four"]}
            for c in db["cards"].values()
            if c["customer_id"] == cid and c["status"] == "active"
        ]
        db["case_index"][cid] = {
            "customer_id": cid,
            "account_last4": acct["account_last4"],
            "date_of_birth": cust["date_of_birth"],
            "ssn_last4": cust["ssn_last4"],
            "current_balance": acct["current_balance"],
            "active_cards": active_cards,
            "disputable_transactions": disputable,
            "stale_transactions": stale,
            "waivable_fees": waivable,
            "blocked_fees": blocked,
            "has_disputable_txn": bool(disputable),
            "has_stale_txn": bool(stale),
            "has_waivable_fee": bool(waivable),
            "has_blocked_fee": bool(blocked),
            "has_active_card": bool(active_cards),
        }


def main() -> None:
    """Write db.json next to this script."""
    db = build_base()
    add_case_index(db)
    out = HERE / "db.json"
    out.write_text(json.dumps(db, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {out} ({len(db['customers'])} customers, {len(db['transactions'])} transactions, {len(db['fees'])} fees)")


if __name__ == "__main__":
    main()
