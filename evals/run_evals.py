#!/usr/bin/env python3
"""Offline evaluation runner for the SQL AI Agent.

Usage:
    uv run python evals/run_evals.py [--api-url URL] [--output FILE] [--ids q001,q002]

Metrics computed:
    - EX rate: % of answerable questions where agent produces executable SQL
    - UNANSWERABLE accuracy: % of non-answerable questions correctly rejected
    - Latency p50 / p95 (ms)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import median, quantiles
from typing import Any

import httpx
import yaml

EVALS_DIR = Path(__file__).parent
RESULTS_DIR = EVALS_DIR / "results"
QUESTIONS_FILE = EVALS_DIR / "questions.yaml"


def load_questions(ids: list[str] | None = None) -> list[dict[str, Any]]:
    with open(QUESTIONS_FILE) as f:
        questions: list[dict[str, Any]] = yaml.safe_load(f)
    if ids:
        questions = [q for q in questions if q["id"] in ids]
    return questions


def run_question(
    client: httpx.Client, api_url: str, question: dict[str, Any]
) -> dict[str, Any]:
    start = time.monotonic()
    answerable = question.get("answerable", True)
    try:
        resp = client.post(
            f"{api_url}/v1/query",
            json={"question": question["question"]},
            timeout=120.0,
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        if resp.status_code == 200:
            data = resp.json()
            agent_unanswerable = bool(data.get("unanswerable"))
            if agent_unanswerable:
                status = "unanswerable_correct" if not answerable else "unanswerable_wrong"
            else:
                status = "success" if answerable else "unanswerable_wrong"
            return {
                "id": question["id"],
                "question": question["question"],
                "difficulty": question["difficulty"],
                "category": question["category"],
                "answerable": answerable,
                "status": status,
                "sql": data.get("sql", ""),
                "columns": data.get("columns", []),
                "row_count": data.get("row_count", 0),
                "attempts": data.get("attempts", 1),
                "latency_ms": data.get("latency_ms", elapsed_ms),
                "api_latency_ms": elapsed_ms,
                "error": data.get("reason") if agent_unanswerable else None,
            }
        else:
            detail = resp.json().get("detail", resp.text) if resp.content else resp.text
            detail_str = str(detail)
            is_unanswerable_code = resp.status_code in (200, 400, 422) and (
                "unanswerable" in detail_str.lower()
                or "ne peut pas" in detail_str.lower()
            )
            if not answerable and is_unanswerable_code:
                status = "unanswerable_correct"
            elif answerable:
                status = "error"
            else:
                status = "unanswerable_wrong"
            return {
                "id": question["id"],
                "question": question["question"],
                "difficulty": question["difficulty"],
                "category": question["category"],
                "answerable": answerable,
                "status": status,
                "sql": "",
                "columns": [],
                "row_count": 0,
                "attempts": 1,
                "latency_ms": elapsed_ms,
                "api_latency_ms": elapsed_ms,
                "error": detail_str[:200],
            }
    except httpx.TimeoutException:
        elapsed_ms = (time.monotonic() - start) * 1000
        return {
            "id": question["id"],
            "question": question["question"],
            "difficulty": question["difficulty"],
            "category": question["category"],
            "answerable": answerable,
            "status": "timeout",
            "sql": "",
            "columns": [],
            "row_count": 0,
            "attempts": 0,
            "latency_ms": elapsed_ms,
            "api_latency_ms": elapsed_ms,
            "error": "Request timed out",
        }
    except Exception as exc:
        return {
            "id": question["id"],
            "question": question["question"],
            "difficulty": question["difficulty"],
            "category": question["category"],
            "answerable": answerable,
            "status": "exception",
            "sql": "",
            "columns": [],
            "row_count": 0,
            "attempts": 0,
            "latency_ms": 0.0,
            "api_latency_ms": 0.0,
            "error": str(exc)[:200],
        }


def compute_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in results if r.get("answerable", True)]
    unanswerable = [r for r in results if not r.get("answerable", True)]

    ex_rate = (
        sum(1 for r in answerable if r["status"] == "success") / len(answerable)
        if answerable
        else 0.0
    )
    unanswerable_accuracy = (
        sum(1 for r in unanswerable if r["status"] == "unanswerable_correct")
        / len(unanswerable)
        if unanswerable
        else 1.0
    )

    successful = [r for r in results if r["status"] == "success"]
    latencies = [r["latency_ms"] for r in successful]
    latency_p50 = median(latencies) if latencies else 0.0
    latency_p95 = (
        quantiles(latencies, n=20)[18]
        if len(latencies) >= 2
        else (latencies[0] if latencies else 0.0)
    )

    by_difficulty: dict[str, dict[str, Any]] = {}
    for diff in ("easy", "medium", "hard"):
        subset = [r for r in answerable if r.get("difficulty") == diff]
        by_difficulty[diff] = {
            "total": len(subset),
            "success": sum(1 for r in subset if r["status"] == "success"),
            "ex_rate": (
                sum(1 for r in subset if r["status"] == "success") / len(subset)
                if subset
                else 0.0
            ),
        }

    errors = [
        r for r in results if r["status"] not in ("success", "unanswerable_correct")
    ]
    return {
        "total_questions": len(results),
        "answerable_questions": len(answerable),
        "unanswerable_questions": len(unanswerable),
        "ex_rate": round(ex_rate, 4),
        "unanswerable_accuracy": round(unanswerable_accuracy, 4),
        "latency_p50_ms": round(latency_p50, 1),
        "latency_p95_ms": round(latency_p95, 1),
        "by_difficulty": by_difficulty,
        "errors": errors,
    }


def print_summary(metrics: dict[str, Any]) -> None:
    print("\n" + "=" * 60)
    print("EVAL RESULTS SUMMARY")
    print("=" * 60)
    print(f"Total questions       : {metrics['total_questions']}")
    print(f"Answerable            : {metrics['answerable_questions']}")
    print(f"Unanswerable          : {metrics['unanswerable_questions']}")
    print(f"\nEX rate               : {metrics['ex_rate']:.1%}")
    print(f"UNANSWERABLE accuracy : {metrics['unanswerable_accuracy']:.1%}")
    print(f"\nLatency p50           : {metrics['latency_p50_ms']:.0f} ms")
    print(f"Latency p95           : {metrics['latency_p95_ms']:.0f} ms")
    print("\nBy difficulty:")
    for diff, stats in metrics["by_difficulty"].items():
        if stats["total"] > 0:
            print(
                f"  {diff:8s}: {stats['success']}/{stats['total']} "
                f"({stats['ex_rate']:.1%})"
            )
    if metrics["errors"]:
        print(f"\nErrors ({len(metrics['errors'])}):")
        for err in metrics["errors"]:
            print(f"  [{err['id']}] {err['status']}: {str(err.get('error') or '')[:80]}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run offline evals against the SQL AI Agent API"
    )
    parser.add_argument(
        "--api-url", default="http://localhost:8000", help="Base API URL"
    )
    parser.add_argument(
        "--output",
        help="JSON output file (default: evals/results/TIMESTAMP.json)",
    )
    parser.add_argument(
        "--ids", help="Comma-separated question IDs to run (default: all)"
    )
    args = parser.parse_args()

    ids = args.ids.split(",") if args.ids else None
    questions = load_questions(ids)
    if not questions:
        print("No questions found.", file=sys.stderr)
        sys.exit(1)

    print(f"Running {len(questions)} questions against {args.api_url} ...")

    results: list[dict[str, Any]] = []
    with httpx.Client() as client:
        for i, q in enumerate(questions, 1):
            print(
                f"  [{i:2d}/{len(questions)}] {q['id']}: {q['question'][:55]}...",
                end=" ",
                flush=True,
            )
            result = run_question(client, args.api_url, q)
            results.append(result)
            icon = (
                "✓"
                if result["status"] == "success"
                else ("~" if result["status"] == "unanswerable_correct" else "✗")
            )
            print(f"{icon} ({result['latency_ms']:.0f}ms)")

    metrics = compute_metrics(results)
    print_summary(metrics)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = (
        Path(args.output) if args.output else RESULTS_DIR / f"eval_{timestamp}.json"
    )
    with open(output_path, "w") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "api_url": args.api_url,
                "metrics": metrics,
                "results": results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
