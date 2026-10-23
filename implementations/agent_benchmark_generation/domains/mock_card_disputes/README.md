# mock_card_disputes

A SynBench domain for benchmarking a **banking card-disputes agent** — one that
helps customers review card transactions, open disputes (chargebacks), and block
lost or stolen cards.

## World (`db.json`)

| Table | Keyed by | Key fields |
|-------|----------|------------|
| `customers` | `customer_id` | `name`, `email`, `dob` |
| `cards` | `card_id` | `customer_id`, `last_four`, `status` (active/blocked) |
| `transactions` | `transaction_id` | `card_id`, `customer_id`, `merchant`, `amount`, `status` (posted/pending), `age_days`, `disputed`, `disputable` |
| `disputes` | `dispute_id` | `transaction_id`, `customer_id`, `reason`, `status` |

`disputable` precomputes the dispute rule (posted **and** within the 60-day
window **and** not already disputed) as one field, so the sampler and `verify.py`
can gate on it directly. The seed data deliberately includes ineligible
transactions: `txn_1002` (too old), `txn_1003` (pending), `txn_2002` (already
disputed) — these drive the `refuse_dispute` tasks.

## Tools (`tools.py`)

- **READ:** `find_customer_id`, `list_cards`, `get_card`, `list_transactions`,
  `get_transaction`, `get_dispute`
- **WRITE:** `open_dispute` (deterministic `dispute_id = disp_<transaction_id>`),
  `block_card` (idempotent)

## Task types

| Type | Write? | What the agent must do |
|------|--------|------------------------|
| `inquiry` | no | Look up and report a transaction / card / dispute |
| `open_dispute` | yes | Open a dispute on an **eligible** posted transaction |
| `block_card` | yes | Block a card after verifying ownership |
| `refuse_dispute` | no | **Refuse** to dispute an ineligible transaction, explaining why |

## Scoring notes

Agents are scored on **outcomes**: final `db_hash` match (DB reward) × required
`communicate_info` substrings present (COMMUNICATE reward).

- `open_dispute` stores `reason` in DB state, so the agent must choose the same
  reason as the oracle (`fraud`, `not_received`, `duplicate_charge`,
  `incorrect_amount`). The task scenario makes the reason explicit, mirroring how
  `mock_retail`'s `update_shipping` requires the exact address argument.
- `refuse_dispute` tasks have no WRITE action — a correct refusal leaves the DB
  unchanged (DB reward) and says "cannot be disputed" (COMMUNICATE reward).

## Run it

```bash
# validate (no LLM calls)
uv run python implementations/agent_benchmark_generation/run_benchmark.py \
    --domain mock_card_disputes --validate-only

# generate 5 tasks, then score the single agent
uv run python implementations/agent_benchmark_generation/run_benchmark.py \
    --domain mock_card_disputes --generate 5
```
