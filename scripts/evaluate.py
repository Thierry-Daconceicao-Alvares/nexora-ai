"""Evaluates NEXORA AI on the labelled set and writes the report.

    python scripts/evaluate.py --provider scripted --out eval/results/scripted
    MISTRAL_API_KEY=... python scripts/evaluate.py --provider mistral --pause 1 \
        --out eval/results/2026-10-20-mistral

See src/nexora/evaluation/ and data/evaluation/.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from nexora.config import Settings
from nexora.domain.rules_config import load_rules
from nexora.evaluation import report, runner
from nexora.llm import build_provider
from nexora.services.analysis import PROMPT_VERSION


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["scripted", "mistral", "gemini"], default="scripted")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, help="only the first N requests (a quick try)")
    parser.add_argument(
        "--pause",
        type=float,
        default=0.0,
        help="seconds between two model calls (free-plan rate limits)",
    )
    parser.add_argument("--no-chaos", action="store_true", help="skip the fault injection run")
    args = parser.parse_args()

    settings = Settings(llm_provider=args.provider)
    provider = build_provider(settings)
    records = runner.load()
    if args.limit:
        records = records[: args.limit]
    run = runner.evaluate(
        provider, records, pause_s=args.pause, chaos=not args.no_chaos, progress=print
    )
    figures = runner.metrics(run)
    commit = (
        subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        or "unknown"
    )
    meta = {
        "provider": provider.name,
        "model": run.rows
        and next((r.get("model") for r in run.rows if r.get("model")), provider.model)
        or provider.model,
        "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "commit": commit,
        "prompt_version": PROMPT_VERSION,
        "rule_set": load_rules(settings.rules_path).version,
        "pause_s": args.pause,
    }
    report.write(run, figures, args.out, meta)
    print()
    print((args.out / "report.md").read_text(encoding="utf-8").split("## By scenario")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
