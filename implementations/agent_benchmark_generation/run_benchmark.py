"""Run the SynBench pipeline from the terminal: generate -> verify -> score.

This is a thin CLI wrapper around the same library calls the notebooks make
(2-generate_and_verify_tasks.ipynb and 3/4-*_evaluation.ipynb), so you can run
a whole benchmark without opening Jupyter.

Prerequisites (from the repo root):
    uv sync --dev --group synbench
    cp implementations/agent_benchmark_generation/.env.example .env   # set models
    # ensure OPENAI_API_KEY is in your environment (see repo README)

Examples:
    # generate 5 tasks for the template domain, then score the single agent
    uv run python implementations/agent_benchmark_generation/run_benchmark.py \
        --domain template_domain --generate 5

    # re-score a saved benchmark with the multi-agent pipeline (no generation)
    uv run python implementations/agent_benchmark_generation/run_benchmark.py \
        --domain template_domain --agent pipeline

    # validate a domain bundle only, no LLM calls
    uv run python implementations/agent_benchmark_generation/run_benchmark.py \
        --domain template_domain --validate-only
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aieng.syn_data.synbench.agents.pipeline import AgentPipeline
from aieng.syn_data.synbench.agents.single import SingleToolAgent
from aieng.syn_data.synbench.domain.loader import load_domain, validate_domain
from aieng.syn_data.synbench.evaluation.metrics import MetricsCollector
from aieng.syn_data.synbench.generation.generator import GenerationRun
from aieng.syn_data.synbench.llm.client import get_client
from aieng.syn_data.synbench.path_utils import find_repo_root
from aieng.syn_data.synbench.schemas.domain import DomainBundle
from aieng.syn_data.synbench.schemas.tasks import Task


def load_saved_tasks(tasks_path: Path) -> list[Task]:
    """Load a previously written ``tasks.json`` into a list of ``Task``."""
    with open(tasks_path) as f:
        raw = json.load(f)
    return [Task.model_validate(t) for t in raw.get("tasks", raw)]


def generate_and_verify(domain: DomainBundle, n: int, out_dir: Path, seed: int) -> list[Task]:
    """Generate ``n`` drafts, verify them, save the passing ones, and return them."""
    run = GenerationRun(domain, seed=seed)
    print(f"Generating {n} draft task(s) with the generator model...")
    drafts = run.run(n=n)
    verified, rejected = run.verify_drafts(drafts)
    print(f"  {len(verified)} passed verification, {len(rejected)} rejected")
    for task, errors in rejected:
        print(f"    - rejected {task.id} ({task.task_type}): {errors}")
    if not verified:
        return []
    path = run.write_tasks(verified, out_dir)
    print(f"  wrote {len(verified)} task(s) -> {path}")
    return verified


def score_agent(domain: DomainBundle, tasks: list[Task], agent_kind: str) -> dict:
    """Run every task through the chosen agent and return aggregate metrics."""
    client = get_client()  # agent-under-test uses AGENT_MODEL from .env
    if agent_kind == "pipeline":
        agent = AgentPipeline(domain, max_turns=12, max_dialogue_turns=3, agent_client=client)
    else:
        agent = SingleToolAgent(domain, max_turns=12, max_dialogue_turns=3, client=client)

    print(f"\nScoring {len(tasks)} task(s) with the '{agent_kind}' agent...")
    metrics = MetricsCollector()
    for task in tasks:
        score = agent.run_and_score_task(task)
        metrics.add(task.id, score)
        flag = "PASS" if score.reward >= 1.0 else "fail"
        missing = f" missing={score.missing_communicate}" if score.missing_communicate else ""
        print(
            f"  [{flag}] {task.id} ({task.task_type}) "
            f"reward={score.reward:.1f} db={score.db_reward:.1f} "
            f"comm={score.communicate_reward:.1f}{missing}"
        )
    return metrics.summary()


def main() -> None:
    """Parse arguments and run the requested slice of the pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--domain",
        default="template_domain",
        help="Domain folder name under domains/ (default: template_domain)",
    )
    parser.add_argument(
        "--generate",
        type=int,
        default=0,
        metavar="N",
        help="Generate and verify N tasks before scoring. 0 (default) reuses a saved tasks.json.",
    )
    parser.add_argument(
        "--agent",
        choices=["single", "pipeline"],
        default="single",
        help="Which agent to evaluate (default: single).",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Sampling seed for generation (default: 42)."
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate the domain bundle; make no LLM calls.",
    )
    args = parser.parse_args()

    root = find_repo_root()
    base = root / "implementations/agent_benchmark_generation"
    domain_path = base / "domains" / args.domain
    out_dir = root / "data/benchmarks" / args.domain
    tasks_path = out_dir / "tasks.json"

    errors = validate_domain(domain_path)
    if errors:
        print(f"Domain '{args.domain}' failed validation:")
        for e in errors:
            print(f"  - {e}")
        raise SystemExit(1)
    print(f"Domain '{args.domain}' validated OK.")
    if args.validate_only:
        return

    domain = load_domain(domain_path)

    if args.generate > 0:
        tasks = generate_and_verify(domain, args.generate, out_dir, args.seed)
    else:
        if not tasks_path.exists():
            raise SystemExit(
                f"No saved tasks at {tasks_path}. Run with --generate N first."
            )
        tasks = load_saved_tasks(tasks_path)
        print(f"Loaded {len(tasks)} saved task(s) from {tasks_path}")

    if not tasks:
        print("No tasks to score. Exiting.")
        return

    summary = score_agent(domain, tasks, args.agent)
    print("\n=== Benchmark summary ===")
    print(f"  tasks:                 {summary['n_tasks']}")
    print(f"  pass@1:                {summary['pass_at_1']:.2%}")
    print(f"  mean DB reward:        {summary['mean_db_reward']:.2f}")
    print(f"  mean communicate:      {summary['mean_communicate_reward']:.2f}")
    print(f"  mean dialogue turns:   {summary['mean_dialogue_turns']:.1f}")

    results_path = out_dir / f"results_{args.agent}.json"
    with open(results_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nFull results written to {results_path}")


if __name__ == "__main__":
    main()
