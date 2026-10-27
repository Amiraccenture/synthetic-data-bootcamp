# mock_credit_union

A SynBench domain for a **credit card servicing agent** at a credit union. The
agent verifies identity, then handles balance questions, disputes, fee waivers,
lost cards, and suspected fraud under the policy in [policy.md](policy.md).

This is **v1: 7 of the 19 task types** in [task_types.full.yaml](task_types.full.yaml).

## Files

| File | Notes |
|------|-------|
| `policy.md` | The agent's rules (source of truth for the domain). |
| `task_types.yaml` | The 7 active task types. The sampler draws only from this file. |
| `task_types.full.yaml` | The original 19-type list, kept for promoting types later. Not loaded. |
| `tools.py` | 6 READ + 4 WRITE tools. Enforces the policy limits as well as describing them. |
| `build_db.py` → `db.json` | 12 customer archetypes. **Edit `build_db.py`, then re-run it; don't edit `db.json` by hand.** |
| `generation.yaml` | Binds the sampler to `case_index`; eligibility filters and communicate hints. |
| `verify.py` | Oracle checks that replay can't see (identity first, required writes). |
| `tasks.seed.json` | 7 hand-verified seeds, one per type. |
| `user_simulator.yaml` | 5 personality styles. |

## Task types in v1

| Type | Write? | What a correct agent does |
|------|--------|---------------------------|
| `balance_inquiry` | no | Verify, read the account, state the balance |
| `transaction_dispute` | yes | Verify, `open_dispute`, state the 30- and 90-day timelines |
| `refuse_dispute` | no | Verify, look up a charge past 60 days, refuse and cite the window |
| `fee_waiver` | yes | Verify, check fee history, `waive_fee` once |
| `refuse_fee_waiver` | no | Verify, check history, refuse citing the 12-month / calendar-year rule |
| `lost_card_report` | yes | Verify, confirm which card, `replace_card`, state $0 liability |
| `fraud_escalation` | yes | Verify, `escalate_to_human` as suspected fraud, `replace_card`, say a human agent will follow up |

## How identity verification works

`verify_identity(full_name, account_last4, date_of_birth | ssn_last4)` returns a
`customer_id`. Every other account tool requires that `customer_id` and checks
ownership, so an agent that skips verification can't read or change anything.
It is stateless on purpose: the pipeline may copy the environment mid-conversation.

## Things to know

- **Generator only sees the first 1,500 characters of `policy.md`.** The dispute
  and fee rules fall after that, so they reach the generator through
  `generation.yaml` (eligibility filters, pre-computed lists, communicate hints)
  and the task-type descriptions instead.
- **`case_index` is generation-only.** No tool reads it, so it can't leak answers
  to the agent. `build_db.py` computes it by running the real tool guards.
- **The policy's "60 days" is ambiguous.** It says "transaction date is within 60
  days of the statement date", which a charge always satisfies. This domain reads
  it as: the dispute must be opened within 60 days of the statement date the
  charge first appeared on (`days_since_statement`). Confirm that's the intent.
- **"Unrecognized charge" vs fraud.** A single disputed charge is a dispute;
  card-details-stolen with several unknown charges is `fraud_escalation`. The
  seeds draw that line, but real customers blur it.
- **Required phrases are substrings**, so wording matters: `"$0"`, `"30 days"`,
  `"human agent"`. They come from facts the policy requires the agent to state,
  but a correct agent that words them differently scores 0.

## Not covered yet

- **Privacy and "must not say" rules** (never reveal another customer's data, no
  legal threats, tone). Scoring checks final DB state and required phrases only,
  and tools only return data for a verified customer, so these can't be tested
  without adding a forbidden-phrase check to the framework.
- **Conversation-state rules**, such as escalating after 3 failed verification
  attempts (needs more dialogue turns than the default run uses).
- The other 12 task types: authorized users, payment holiday, VAU, credit limit
  increase, stop payment, account closure, unauthorized-use dispute, and others.

## Run it

```bash
uv run python implementations/agent_benchmark_generation/run_benchmark.py \
    --domain mock_credit_union --validate-only

uv run python implementations/agent_benchmark_generation/run_benchmark.py \
    --domain mock_credit_union --generate 5
```
