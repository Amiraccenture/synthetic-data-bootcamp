# template_domain

A **scaffold** for authoring your own SynBench domain. It loads and validates
out of the box using a generic `customers` + `records` world, so you can prove
the pipeline end to end, then replace the placeholders with your real domain.

## Files

| File | Who reads it | What to change |
|------|--------------|----------------|
| `policy.md` | generator, agent-under-test, planner/critic | Your real rules. Every rule should be checkable. |
| `db.json` | tools, scoring (via replay) | Your real world state. Tables are objects keyed by id. Keep it small but cover every status/edge case. |
| `tools.py` | agent, generator (as specs), env | Your real tool surface. READ tools don't mutate; WRITE tools mutate `self.db` deterministically. |
| `task_types.yaml` | sampler, verifier | Your task mix + per-type `allow_write`. |
| `user_simulator.yaml` | user-simulator LLM | Personas / goal phrasing. The 5 styles are reusable as-is. |
| `tasks.seed.json` | generator (few-shot) | 3–6 hand-verified example tasks. Quality > quantity. |
| `generation.yaml` | sampler, prompt builder | **No-code binding** to your db.json shape (collections, ids, joins, eligibility, hints). |
| `verify.py` | verifier | Domain invariants the oracle must respect. |

## How to use it

1. Copy this folder to `domains/<your_domain>/` (or edit in place).
2. Replace placeholders marked `TODO`. Start with `db.json` + `tools.py` — they
   define the whole world. Keep `policy.md`, `verify.py`, and the WRITE-tool
   guards in `tools.py` consistent with each other.
3. Point a notebook's `DOMAIN_PATH` at this folder.
4. Validate before generating:

   ```python
   from aieng.syn_data.synbench.domain.loader import validate_domain
   errors = validate_domain("implementations/agent_benchmark_generation/domains/template_domain")
   assert not errors, errors
   ```

5. Run notebook `2-generate_and_verify_tasks.ipynb` to generate + verify tasks,
   then `3-single_agent_evaluation.ipynb` to score an agent (`pass@1`).

## Scoring reminder

Agents are scored on **outcomes**, not exact tool sequences: final `db_hash`
match (DB reward) × required `communicate_info` substrings present
(COMMUNICATE reward). Author oracle `actions` and `communicate_info` carefully —
both must pass for reward 1.0.
