"""On-demand SEC filing acquisition through OpenAgentFabric Redis Streams.

The continuous SecWatcher is intentionally not used: its permanent deduplication
markers are appropriate for monitoring, but not for repeatable on-demand runs.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis

from shared.correlation.registry import CorrelationRegistry
from shared.eventbus.events import (
    DocumentDiscoveredEvent,
    DocumentDiscoveredPayload,
    EventEnvelope,
    EventType,
)
from shared.eventbus.redis import RedisEventBus
from shared.models import AgentName

from secagent.agents.fetcher import SecFetcher
from secagent.agents.parser import SecParser
from secagent.clients.edgar import EdgarClient, Filing

DEFAULT_REDIS_URL = "redis://localhost:6380/0"
DEFAULT_STREAM = "oaf.events"


def _artifact_dict(artifact: Any) -> dict[str, Any]:
    return artifact.model_dump(mode="json")


def _check_tasks(tasks: list[asyncio.Task[Any]]) -> None:
    for task in tasks:
        if not task.done():
            continue
        if task.cancelled():
            raise RuntimeError(f"SEC agent exited unexpectedly: {task.get_name()} (cancelled)")
        exc = task.exception()
        if exc is not None:
            raise RuntimeError(f"SEC agent failed: {task.get_name()}") from exc
        raise RuntimeError(f"SEC agent exited unexpectedly: {task.get_name()}")


async def run_sec_cycle(
    cik: int,
    forms: set[str] | None = None,
    as_of: date | None = None,
    limit: int = 2,
    output: str | Path = "data/filings",
    redis_url: str | None = None,
    timeout: float = 600.0,
    user_agent: str | None = None,
    stream: str = DEFAULT_STREAM,
) -> dict[str, Any]:
    """Fetch and parse SEC filings through OpenAgentFabric agents.

    Only the SEC's *recent* submissions array is searched. ``as_of`` is an
    inclusive filing-date filter, not a guarantee of historical completeness.
    Each call is a new execution, even when the filing was processed before.

    Returns a JSON-serializable dictionary with a ``filings`` list. Each entry
    includes filing metadata, the correlation ID, and raw/parsed artifact refs.
    """
    if not isinstance(cik, int) or isinstance(cik, bool) or cik <= 0:
        raise ValueError("cik must be a positive integer")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if as_of is not None and not isinstance(as_of, date):
        raise TypeError("as_of must be a datetime.date or None")
    selected_forms = {"10-K", "10-Q"} if forms is None else set(forms)
    if not selected_forms or any(not isinstance(f, str) or not f for f in selected_forms):
        raise ValueError("forms must contain at least one nonempty form name")
    if not stream:
        raise ValueError("stream must not be empty")
    identity = user_agent or os.environ.get("SEC_USER_AGENT")
    if not identity or not identity.strip():
        raise ValueError("Pass user_agent or set SEC_USER_AGENT to a real SEC contact identity")

    root = Path(output).expanduser().resolve()
    url = redis_url or os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)
    deadline = asyncio.get_running_loop().time() + timeout
    request_id = str(uuid4())

    redis = Redis.from_url(url, decode_responses=True)
    bus: RedisEventBus | None = None
    agents: list[Any] = []
    tasks: list[asyncio.Task[Any]] = []
    try:
        await redis.ping()
        bus = RedisEventBus(redis_url=url)
        registry = CorrelationRegistry(redis)

        async with EdgarClient(user_agent=identity) as edgar:
            # Fetch all available matching recent filings BEFORE the as-of
            # filter, so the limit does not discard older eligible filings.
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("SEC cycle timed out before discovery")
            candidates = await asyncio.wait_for(
                edgar.get_recent_filings(cik=cik, forms=selected_forms, limit=None),
                timeout=remaining,
            )
            filings: list[Filing] = [
                filing for filing in candidates
                if as_of is None or filing.filing_date <= as_of
            ][:limit]
            if not filings:
                return {
                    "request_id": request_id,
                    "cik": cik,
                    "forms": sorted(selected_forms),
                    "as_of": as_of.isoformat() if as_of else None,
                    "filings": [],
                }

            agents = [
                SecFetcher(
                    event_bus=bus,
                    correlation_registry=registry,
                    edgar_client=edgar,
                    artifact_root=root,
                    stream=stream,
                ),
                SecParser(
                    event_bus=bus,
                    correlation_registry=registry,
                    artifact_root=root,
                    stream=stream,
                ),
            ]

            # Observe from the current tail, before publishing our requests.
            tail = await redis.xrevrange(stream, count=1)
            cursor = tail[0][0] if tail else "0-0"
            for agent in agents:
                tasks.append(asyncio.create_task(agent.run(), name=f"sec-{agent.name}"))

            pending: dict[str, tuple[Filing, str]] = {}
            results: dict[str, dict[str, Any]] = {}
            for filing in filings:
                _check_tasks(tasks)
                now = datetime.now(timezone.utc)
                record = await registry.create(
                    trigger_type="sec.filing.on_demand",
                    trigger_timestamp=now,
                    business_fields={
                        "request_id": request_id,
                        "cik": str(filing.cik),
                        "accession_number": filing.accession_number,
                    },
                )
                event = DocumentDiscoveredEvent(
                    source_agent=AgentName.WATCHER,
                    correlation_id=record.correlation_id,
                    payload=DocumentDiscoveredPayload(
                        cik=str(filing.cik),
                        accession_number=filing.accession_number,
                        company_name=filing.company_name,
                        filing_type=filing.form,
                        filing_date=filing.filing_date.isoformat(),
                        filing_url=filing.document_url,
                    ),
                )
                pending[str(record.correlation_id)] = (filing, str(event.event_id))
                await bus.publish(stream, event)

            while pending:
                _check_tasks(tasks)
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError(
                        "SEC cycle timed out; unfinished correlations: "
                        + ", ".join(sorted(pending))
                        + f"; inspect {stream} and {stream}.dlq"
                    )
                entries = await redis.xread(
                    {stream: cursor},
                    count=100,
                    block=max(1, min(1000, int(remaining * 1000))),
                )
                for _, messages in entries:
                    for message_id, fields in messages:
                        cursor = message_id
                        event = EventEnvelope.model_validate_json(fields["event"])
                        correlation = str(event.correlation_id)
                        if correlation not in pending or event.event_type != EventType.DOCUMENT_PARSED:
                            continue
                        filing, _ = pending.pop(correlation)
                        payload = event.payload
                        # EventEnvelope may parse a typed payload or a dict.
                        if hasattr(payload, "model_dump"):
                            payload = payload.model_dump(mode="json")
                        results[correlation] = {
                            "cik": filing.cik,
                            "company_name": filing.company_name,
                            "form": filing.form,
                            "filing_date": filing.filing_date.isoformat(),
                            "accession_number": filing.accession_number,
                            "correlation_id": correlation,
                            "raw_artifact": payload["source_artifact"],
                            "parsed_artifact": payload["parsed_artifact"],
                        }

            return {
                "request_id": request_id,
                "cik": cik,
                "forms": sorted(selected_forms),
                "as_of": as_of.isoformat() if as_of else None,
                "filings": [results[c] for c in results],
            }
    finally:
        for agent in agents:
            agent.stop()
        if tasks:
            done, unfinished = await asyncio.wait(tasks, timeout=10)
            for task in unfinished:
                task.cancel()
            if unfinished:
                await asyncio.gather(*unfinished, return_exceptions=True)
        if bus is not None:
            await bus.close()
        await redis.aclose()
