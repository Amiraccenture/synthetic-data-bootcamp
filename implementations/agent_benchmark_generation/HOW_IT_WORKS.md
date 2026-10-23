# Agent Benchmarking with SynBench — How It Works

> A team explainer for how we test AI agents with a synthetic benchmark.

## What this is

We built a **synthetic benchmark** that tests AI agents the way a QA team would —
except the test cases are generated automatically, each with a known-correct
answer. Our example domain is a **bank card-disputes agent**
(`domains/mock_card_disputes`). The framework is SynBench, modeled on
[τ-bench](https://taubench.com/).

The core idea: **don't grade the agent on which tools it called in what order —
grade it on outcomes.** Did it leave the database in the right final state, and
did it tell the customer the right thing?

## The pipeline (5 stages)

```
1. DOMAIN    a mock world: policy + database + tools + task types
2. GENERATE  an LLM writes test scenarios + the correct solution ("oracle")
3. VERIFY    rules auto-check each scenario is valid; bad ones are dropped
4. RUN       the agent-under-test handles each task in a simulated conversation
5. SCORE     final DB state matches oracle?  +  did it say required phrases?
```

## The domain we built

A mock bank world (`db.json`): **customers → cards → transactions → disputes**.
The agent gets 8 tools — 6 read-only lookups and 2 that change state
(`open_dispute`, `block_card`).

Four kinds of test tasks:

| Task | What the agent must do |
|---|---|
| **inquiry** | Look up and report a charge (read-only) |
| **open_dispute** | File a dispute on an *eligible* charge |
| **block_card** | Block a lost/stolen card |
| **refuse_dispute** | *Decline* to dispute an ineligible charge and explain why |

The `refuse_dispute` case is the most valuable — it catches agents that cave to
pushy customers.

## What the agent actually does (one example)

A customer says *"There's an $899 charge I don't recognize."* The agent — which
only sees the policy and the tools, **not** the answer — has to:

1. ask for the name → `find_customer_id`
2. find the charge → `list_transactions` / `get_transaction`, confirm merchant & amount
3. file it → `open_dispute(txn, "fraud")`
4. confirm to the customer that a **dispute** was opened

## How scoring works

SynBench replays the oracle and the agent on *fresh* copies of the DB and
compares:

- **DB reward** — agent's final database state == oracle's? (dispute created /
  card blocked / *nothing changed* for a refusal)
- **Communicate reward** — did the agent say the required phrase? ("dispute",
  "blocked", "cannot be disputed")
- **reward = DB × Communicate** → both must pass. Aggregate metric is **pass@1**
  (fraction of tasks fully correct).

Reads don't affect the score — only outcomes do. An agent can take a different
valid path and still pass.

## Why this is useful

- **Scales** — generate hundreds of varied, persona-driven tasks instead of
  hand-writing them.
- **Objective** — pass/fail is deterministic, no human grading.
- **Comparative** — run different models/prompts against the *same* tasks and
  compare pass@1.
- **Targets failure modes** — we design task types (like refusals) around where
  agents break.

## How to run it

```bash
# one-time setup
uv sync --dev --group synbench
cp implementations/agent_benchmark_generation/.env.example .env   # set models + API key

# validate the domain (no API calls)
uv run python implementations/agent_benchmark_generation/run_benchmark.py \
    --domain mock_card_disputes --validate-only

# generate tasks + score the agent
uv run python implementations/agent_benchmark_generation/run_benchmark.py \
    --domain mock_card_disputes --generate 5
```

To benchmark a different agent, change `AGENT_MODEL` in `.env` (or the
`policy.md`) and re-run against the same tasks.

## One caveat to know

Write actions require the agent to match the oracle's arguments (e.g. the dispute
`reason`), so argument choices matter for scoring — something we're reviewing
with mentors.

## Where things live

- `domains/mock_card_disputes/` — the domain we built (world, tools, policy, tasks)
- `domains/template_domain/` — a blank scaffold to spin up a new domain
- `run_benchmark.py` — CLI to generate + verify + score from the terminal
- Notebooks `1`–`5` — the same flow, step by step, for learning
