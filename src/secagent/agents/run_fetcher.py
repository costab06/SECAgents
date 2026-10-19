
"""Run the SEC Fetcher as a standalone OpenAgentFabric agent."""

import asyncio
import logging
import os
from pathlib import Path

from shared.correlation.registry import CorrelationRegistry
from shared.eventbus.redis import RedisEventBus

from secagent.agents.fetcher import SecFetcher
from secagent.clients.edgar import EdgarClient


async def main() -> None:
    user_agent = os.environ.get("SEC_USER_AGENT")

    if not user_agent:
        raise SystemExit(
            "Set SEC_USER_AGENT to an application identity "
            "and real contact email."
        )

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

        async with EdgarClient(
            user_agent=user_agent,
        ) as edgar:
            agent = SecFetcher(
                event_bus=bus,
                correlation_registry=registry,
                edgar_client=edgar,
                artifact_root=artifact_root,
                stream=stream,
            )

            logging.info(
                "Starting SEC Fetcher: stream=%s group=%s "
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
