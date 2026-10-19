
"""Run the SEC Watcher against EDGAR and Redis."""

import argparse
import asyncio
import logging
import os

from redis.asyncio import Redis

from secagent.agents.watcher import SecWatcher
from secagent.clients.edgar import EdgarClient
from secagent.config.companies import load_companies


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover SEC filings and publish events"
    )
    parser.add_argument(
        "--cik",
        type=int,
        default=320193,
        help="SEC CIK (default: Apple)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Number of recent matching filings to inspect",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Poll continuously instead of running once",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=300.0,
        help="Seconds between polls in continuous mode",
    )
    return parser.parse_args()



async def main() -> None:
    args = parse_args()

    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        raise SystemExit(
            "SEC_USER_AGENT must identify the application "
            "and provide a real contact email."
        )

    # Load the companies to monitor.
    companies = load_companies("config/companies.yaml")

    if not companies:
        raise ValueError(
            "No enabled companies in config/companies.yaml"
        )

    print(
        f"Monitoring {len(companies)} companies: "
        + ", ".join(company.ticker for company in companies)
    )

    redis_url = os.environ.get(
        "REDIS_URL",
        "redis://localhost:6380/0",
    )

    stream = os.environ.get(
        "OAF_STREAM",
        "oaf.events",
    )

    marker_prefix = os.environ.get(
        "SEC_MARKER_PREFIX",
        f"secagent:published:{stream}",
    )

    redis = Redis.from_url(
        redis_url,
        decode_responses=True,
    )

    try:
        await redis.ping()

        async with EdgarClient(
            user_agent=user_agent,
        ) as client:

            watcher = SecWatcher(
                client=client,
                redis=redis,
                stream=stream,
                marker_prefix=marker_prefix,
            )

            if args.continuous:
                await watcher.run_companies(
                    companies=companies,
                    poll_interval_seconds=args.interval,
                    limit=args.limit,
                )

            else:
                results = await watcher.poll_companies(
                    companies=companies,
                    limit=args.limit,
                )

                for company in companies:
                    result = results.get(company.ticker)

                    if result is None:
                        print(f"{company.ticker}: Poll failed")
                        continue

                    print(
                        f"{company.ticker}: "
                        f"Discovered: {result.discovered}, "
                        f"Published: {result.published}, "
                        f"Duplicates: {result.duplicates}"
                    )

    finally:
        await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
