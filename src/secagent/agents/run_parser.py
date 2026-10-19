
"""Run the SEC Parser as a standalone OpenAgentFabric agent."""

import asyncio
import logging
import os
from pathlib import Path

from shared.correlation.registry import CorrelationRegistry
from shared.eventbus.redis import RedisEventBus

from secagent.agents.parser import SecParser


async def main() -> None:
    redis_url = os.environ.get(
        "REDIS_URL",
        "redis://localhost:6380/0",
    )
    stream = os.environ.get(
        "OAF_STREAM",
        "oaf.events",
    )
    artifact_root = Path(
        os.environ.get(
            "SEC_ARTIFACT_ROOT",
            "data/filings",
        )
    )

    bus = RedisEventBus(redis_url=redis_url)

    try:
        await bus.redis.ping()

        registry = CorrelationRegistry(bus.redis)

        agent = SecParser(
            event_bus=bus,
            correlation_registry=registry,
            artifact_root=artifact_root,
            stream=stream,
        )

        logging.info(
            "Starting SEC Parser: stream=%s group=%s "
            "consumer=%s artifact_root=%s",
            agent.stream,
            agent.group,
            agent.consumer,
            artifact_root.resolve(),
        )

        await agent.run()

    finally:
        await bus.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
