
"""Reset persistent SECAgents demo state safely."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from pathlib import Path
from uuid import UUID

from redis.asyncio import Redis

from shared.correlation.registry import CorrelationRegistry
from shared.eventbus.events import DocumentDiscoveredEvent


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "data" / "filings"

DEFAULT_STREAM = "secagent.multicompany.v1"
DEFAULT_MARKER_PREFIX = "secagent:multicompany:v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset SECAgents demo state."
    )

    parser.add_argument(
        "--stream",
        default=os.environ.get(
            "OAF_STREAM", DEFAULT_STREAM
        ),
    )
    parser.add_argument(
        "--marker-prefix",
        default=os.environ.get(
            "SEC_MARKER_PREFIX",
            DEFAULT_MARKER_PREFIX,
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Also delete downloaded and parsed artifacts.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation.",
    )

    return parser.parse_args()


async def discover_correlations(
    redis: Redis,
    stream: str,
) -> set[UUID]:
    correlations: set[UUID] = set()

    if not await redis.exists(stream):
        return correlations

    start = "-"

    while True:
        messages = await redis.xrange(
            stream,
            min=start,
            max="+",
            count=500,
        )

        if not messages:
            break

        for _, fields in messages:
            serialized = fields.get("event")

            if not serialized:
                continue

            try:
                event = (
                    DocumentDiscoveredEvent.model_validate_json(
                        serialized
                    )
                )
            except Exception:
                continue

            correlations.add(event.correlation_id)

        start = f"({messages[-1][0]}"

    return correlations


async def delete_markers(
    redis: Redis,
    marker_prefix: str,
) -> int:
    deleted = 0
    batch: list[str] = []

    async for key in redis.scan_iter(
        match=f"{marker_prefix}:*",
        count=500,
    ):
        batch.append(key)

        if len(batch) >= 500:
            deleted += await redis.unlink(*batch)
            batch.clear()

    if batch:
        deleted += await redis.unlink(*batch)

    return deleted


def artifact_directory() -> Path:
    configured = Path(
        os.environ.get(
            "SEC_ARTIFACT_ROOT",
            str(DEFAULT_ARTIFACT_ROOT),
        )
    )

    if not configured.is_absolute():
        configured = PROJECT_ROOT / configured

    return configured.resolve()


def validate_artifact_directory(path: Path) -> None:
    data_root = (PROJECT_ROOT / "data").resolve()

    if path == data_root or data_root not in path.parents:
        raise ValueError(
            "Refusing to delete artifacts outside a "
            "subdirectory of the project's data directory."
        )


async def main() -> None:
    args = parse_args()

    if not args.stream.startswith("secagent."):
        raise ValueError(
            "Refusing to reset a non-demo stream."
        )

    if not args.marker_prefix.startswith("secagent:"):
        raise ValueError(
            "Refusing to reset a non-SECAgents marker prefix."
        )

    root = artifact_directory()

    if args.all:
        validate_artifact_directory(root)

    redis_url = os.environ.get(
        "REDIS_URL",
        "redis://localhost:6380/0",
    )

    redis = Redis.from_url(
        redis_url,
        decode_responses=True,
    )

    try:
        await redis.ping()

        stream_exists = bool(
            await redis.exists(args.stream)
        )

        correlations = await discover_correlations(
            redis,
            args.stream,
        )

        print("\nSECAgents Demo Reset")
        print("=" * 50)
        print(f"Redis: {redis_url}")
        print(f"Stream: {args.stream}")
        print(f"Stream exists: {stream_exists}")
        print(f"Correlations identified: {len(correlations)}")
        print(f"Marker prefix: {args.marker_prefix}")
        print(f"Delete artifacts: {args.all}")

        if args.all:
            print(f"Artifact directory: {root}")

        if not args.yes:
            confirmation = input(
                "\nType RESET to confirm: "
            )

            if confirmation != "RESET":
                print("Cancelled.")
                return

        # Remove stream and its consumer groups.
        if stream_exists:
            await redis.delete(args.stream)
            print("Deleted demo stream.")

        # Remove publication markers.
        marker_count = await delete_markers(
            redis,
            args.marker_prefix,
        )
        print(
            f"Deleted publication markers: {marker_count}"
        )

        # Remove only identified correlation records.
        registry = CorrelationRegistry(redis)
        deleted_correlations = 0

        for correlation_id in correlations:
            if await registry.delete(correlation_id):
                deleted_correlations += 1

        print(
            "Deleted correlation records: "
            f"{deleted_correlations}"
        )

        if args.all and root.exists():
            shutil.rmtree(root)
            print(f"Deleted artifacts: {root}")

        print("\nDemo reset complete.")

    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
