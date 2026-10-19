
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from shared.eventbus.events import (
    DocumentDiscoveredEvent,
    EventType,
)
from shared.models import AgentName

from secagent.agents.watcher import SecWatcher
from secagent.clients.edgar import Filing


@pytest.fixture
def filing():
    return Filing(
        cik=320193,
        company_name="Apple Inc.",
        form="10-Q",
        accession_number="0000320193-26-000001",
        filing_date=date(2026, 1, 3),
        primary_document="quarterly.htm",
    )


@pytest.fixture
def watcher():
    client = SimpleNamespace(
        get_recent_filings=AsyncMock()
    )
    redis = SimpleNamespace(
        eval=AsyncMock()
    )

    instance = SecWatcher(
        client=client,
        redis=redis,
        stream="test.sec.events",
    )

    correlation_id = uuid4()
    instance.correlations.create = AsyncMock(
        return_value=SimpleNamespace(
            correlation_id=correlation_id
        )
    )

    return instance


@pytest.mark.asyncio
async def test_publish_discovered_event(watcher, filing):
    watcher.redis.eval.return_value = [1, "123-0"]

    published = await watcher.publish_filing(filing)

    assert published is True

    args = watcher.redis.eval.await_args.args

    assert args[1] == 2
    assert args[3] == "test.sec.events"

    event = DocumentDiscoveredEvent.model_validate_json(
        args[4]
    )

    assert event.event_type == EventType.DOCUMENT_DISCOVERED
    assert event.source_agent == AgentName.WATCHER
    assert event.payload.cik == "320193"
    assert event.payload.accession_number == (
        "0000320193-26-000001"
    )
    assert event.payload.filing_url == filing.document_url


@pytest.mark.asyncio
async def test_duplicate_is_not_published_again(watcher, filing):
    watcher.redis.eval.return_value = [0, ""]

    published = await watcher.publish_filing(filing)

    assert published is False


@pytest.mark.asyncio
async def test_poll_counts_new_and_duplicate(watcher, filing):
    other = Filing(
        cik=320193,
        company_name="Apple Inc.",
        form="10-K",
        accession_number="0000320193-26-000002",
        filing_date=date(2026, 1, 4),
        primary_document="annual.htm",
    )

    watcher.client.get_recent_filings.return_value = [
        other,
        filing,
    ]

    watcher.redis.eval.side_effect = [
        [1, "123-0"],
        [0, ""],
    ]

    result = await watcher.poll(
        cik=320193,
        limit=2,
    )

    assert result.discovered == 2
    assert result.published == 1
    assert result.duplicates == 1

    watcher.client.get_recent_filings.assert_awaited_once_with(
        cik=320193,
        forms={"10-K", "10-Q"},
        limit=2,
    )


@pytest.mark.asyncio
async def test_correlation_identity_is_stable(watcher, filing):
    watcher.redis.eval.return_value = [1, "123-0"]

    await watcher.publish_filing(filing)
    await watcher.publish_filing(filing)

    first = watcher.correlations.create.await_args_list[0]
    second = watcher.correlations.create.await_args_list[1]

    assert first.kwargs == second.kwargs
    assert first.kwargs["business_fields"] == {
        "cik": "320193",
        "accession_number": "0000320193-26-000001",
    }


def test_rejects_empty_stream():
    with pytest.raises(ValueError):
        SecWatcher(
            client=SimpleNamespace(),
            redis=SimpleNamespace(),
            stream="",
        )
