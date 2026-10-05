"""Runnable demo: ``python -m orchestrator.examples.run_demo`` (Agent 3).

Executes one worked example end-to-end in LLM_MODE=mock (fully offline) and
prints every pinned event as it fires, then a compact run summary (status,
steps, token/cost meter, report executive summary).

Usage::

    python -m orchestrator.examples.run_demo                # churn (default)
    python -m orchestrator.examples.run_demo --example ev
    python -m orchestrator.examples.run_demo --example support
    python -m orchestrator.examples.run_demo --list
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from orchestrator.examples.missions import EXAMPLES, get_example, list_examples

__all__ = ["main", "run_example"]


def _print_event(envelope: dict) -> None:
    """Pretty-print one pinned event envelope as it fires."""
    payload = json.dumps(envelope.get("payload", {}), ensure_ascii=False, default=str)
    if len(payload) > 180:
        payload = payload[:177] + "..."
    agent = envelope.get("agent") or "-"
    print(f"[{envelope['seq']:>2}] {envelope['type']:<17} {agent:<10} {payload}")


def run_example(key: str, on_event=None) -> dict:
    """Run one example synchronously and return the RunResult dict.

    Args:
        key: example key (churn | ev | support).
        on_event: event callback; ``None`` disables event printing (quiet mode).
    """
    # Mock mode is the demo default; an explicit env override still wins.
    os.environ.setdefault("LLM_MODE", "mock")

    from orchestrator.engine import execute_run

    example = get_example(key)
    print(f"=== AgentForge demo: {example.title} ===")
    print(f"MISSION: {example.mission}")
    print(f"TEMPLATE: {example.template_id or '-'}  DATASET: {example.dataset_path or '-'}")
    print("EXPECTED PLAN (heuristic):")
    print(example.expected_plan_json())
    print("--- live events ---")

    result = asyncio.run(
        execute_run(
            mission=example.mission,
            template_id=example.template_id,
            dataset_path=example.dataset_path,
            dataset_columns=list(example.dataset_columns),
            on_event=on_event,
        )
    )
    return result.to_dict()


def _print_summary(result: dict) -> None:
    """Print the compact end-of-run summary."""
    print("--- run summary ---")
    print(f"run_id: {result['run_id']}")
    print(f"status: {result['status']}")
    for step in result["steps"]:
        marker = {"completed": "+", "failed": "x", "skipped": "-", "pending": "?"}.get(
            step["status"], "?"
        )
        print(f"  [{marker}] {step['subtask_id']:<8} {step['agent']:<10} {step['title'][:60]}")
    totals = result["token_usage"].get("totals", {})
    print(
        f"tokens: in={totals.get('input_tokens', 0)} out={totals.get('output_tokens', 0)} "
        f"est_cost=${totals.get('cost_usd', 0.0):.6f}"
    )
    if result["errors"]:
        print("errors:")
        for error in result["errors"]:
            print(f"  - {error[:160]}")
    report = result.get("report")
    if report:
        print("report executive summary:")
        print(f"  {report.get('executive_summary', '')[:400]}")
    else:
        print("report: not built (orchestrator.report unavailable or failed)")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.examples.run_demo",
        description="Run one AgentForge worked example offline (LLM_MODE=mock).",
    )
    parser.add_argument(
        "--example",
        choices=sorted(EXAMPLES),
        default="churn",
        help="which worked example to run (default: churn)",
    )
    parser.add_argument("--list", action="store_true", help="list examples and exit")
    parser.add_argument(
        "--quiet", action="store_true", help="suppress per-event output"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.list:
        for key in list_examples():
            example = get_example(key)
            print(f"{key:<10} {example.title}")
        return 0

    result = run_example(args.example, on_event=None if args.quiet else _print_event)
    _print_summary(result)
    return 0 if result["status"] in ("succeeded", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
