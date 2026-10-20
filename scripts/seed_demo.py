"""Fill a database with the demo requests and decisions (src/nexora/demo.py).

    python scripts/seed_demo.py --database sqlite:///nexora.db
    MISTRAL_API_KEY=... python scripts/seed_demo.py --database sqlite:///tmp.db --record

Every request goes through the real pipeline and every decision through the
review service. The analyses come from the recorded answers of a real model
when they exist (data/demo/recorded_analyses.jsonl), otherwise from the
provider configured in the environment. With --record, the configured model
analyses every request and its answers are written to that file.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from nexora import demo
from nexora.api.app import create_app
from nexora.config import Settings
from nexora.llm import build_provider
from nexora.llm.replay import RECORDINGS, RecordingProvider, ReplayProvider


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, help="SQLAlchemy URL of the database")
    parser.add_argument(
        "--record",
        action="store_true",
        help="analyse with the configured model and record its answers",
    )
    args = parser.parse_args()

    settings = Settings(database_url=args.database)
    live = build_provider(settings)
    if args.record:
        if live.name == "scripted":
            print("--record needs a model: set MISTRAL_API_KEY or GEMINI_API_KEY.")
            return 1
        provider = RecordingProvider(live)
    else:
        provider = ReplayProvider.from_file(RECORDINGS, fallback=live)
    clock = {"now": datetime.now(UTC)}
    client = TestClient(create_app(settings, clock=lambda: clock["now"], provider=provider))
    count = demo.seed(client, clock)
    if not count:
        print("The database already holds requests: nothing added.")
    if args.record:
        provider.save(RECORDINGS)
        print(f"{len(provider.recorded)} answers recorded in {RECORDINGS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
