"""Live smoke test of SECAgents -> OpenAgentFabric -> SEC EDGAR.

Run from the SECAgents repository root, with Redis on port 6380 and
SEC_USER_AGENT set to an identifying application name and real email.
"""
import argparse
import asyncio
import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

from secagent.runtime import run_sec_cycle


def artifact_path(ref: dict) -> Path:
    parsed = urlsplit(ref["uri"])
    if parsed.scheme != "file" or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError(f"Expected local file artifact: {ref['uri']}")
    path = Path(unquote(parsed.path))
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cik", type=int, default=789019)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--output", default="data/filings")
    parser.add_argument("--redis-url", default="redis://localhost:6380/0")
    parser.add_argument(
        "--stream",
        default="secagent.integration",
        help="Redis stream used for the SEC integration test",
    )
    args = parser.parse_args()
    if not os.environ.get("SEC_USER_AGENT"):
        parser.error("Set SEC_USER_AGENT to an application name and real contact email")

    result = await run_sec_cycle(
        cik=args.cik, forms={"10-K", "10-Q"}, as_of=args.as_of,
        limit=args.limit, timeout=args.timeout, output=args.output,
        redis_url=args.redis_url,stream=args.stream,
    )
    if not result["filings"]:
        raise RuntimeError("No qualifying filings found in the recent SEC submissions array")
    for filing in result["filings"]:
        raw = artifact_path(filing["raw_artifact"])
        parsed = artifact_path(filing["parsed_artifact"])
        document = json.loads(parsed.read_text(encoding="utf-8"))
        source = document["source"]
        assert str(source["cik"]) == str(filing["cik"])
        assert source["accession_number"] == filing["accession_number"]
        print(f"Verified raw_artifact: {raw}")
        print(f"Verified parsed_artifact: {parsed}")
        print(f"Correlation: {filing['correlation_id']}")
    print("PASS: SEC workflow produced readable, matching artifacts")


if __name__ == "__main__":
    asyncio.run(main())
