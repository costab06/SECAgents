
import hashlib
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from shared.eventbus.events import (
    DocumentDiscoveredEvent,
    DocumentDiscoveredPayload,
    EventType,
)
from shared.models import AgentName, ArtifactType

from secagent.agents.fetcher import SecFetcher
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
def fetcher(tmp_path):
    bus = SimpleNamespace()
    registry = SimpleNamespace()

    edgar = SimpleNamespace(
        _get=AsyncMock(
            return_value=SimpleNamespace(
                content=b"<html>SEC filing</html>"
            )
        )
    )

    return SecFetcher(
        event_bus=bus,
        correlation_registry=registry,
        edgar_client=edgar,
        artifact_root=tmp_path,
    )


def make_event(filing):
    return DocumentDiscoveredEvent(
        source_agent=AgentName.WATCHER,
        correlation_id=uuid4(),
        payload=DocumentDiscoveredPayload(
            cik=str(filing.cik),
            accession_number=filing.accession_number,
            company_name=filing.company_name,
            filing_type=filing.form,
            filing_date=filing.filing_date.isoformat(),
            filing_url=filing.document_url,
        ),
    )


@pytest.mark.asyncio
async def test_fetcher_creates_artifact(
    fetcher,
    filing,
    tmp_path,
):
    event = make_event(filing)

    downstream = await fetcher.handle_event(event)

    assert len(downstream) == 1

    result = downstream[0]

    assert result.event_type == EventType.DOCUMENT_FETCHED
    assert result.source_agent == AgentName.FETCHER
    assert result.correlation_id == event.correlation_id
    assert result.causation_id == event.event_id

    artifact = result.payload.artifact

    assert artifact.artifact_type == ArtifactType.RAW_DOCUMENT
    assert artifact.checksum == (
        "sha256:"
        + hashlib.sha256(
            b"<html>SEC filing</html>"
        ).hexdigest()
    )

    path = Path(artifact.uri.removeprefix("file://"))

    assert path.exists()
    assert path.read_bytes() == b"<html>SEC filing</html>"
    assert path.is_relative_to(tmp_path)


@pytest.mark.asyncio
async def test_retry_reuses_artifact_path(fetcher, filing):
    event = make_event(filing)

    first = await fetcher.handle_event(event)
    second = await fetcher.handle_event(event)

    assert (
        first[0].payload.artifact.uri
        == second[0].payload.artifact.uri
    )

    assert (
        first[0].payload.artifact.artifact_id
        == second[0].payload.artifact.artifact_id
    )


@pytest.mark.asyncio
async def test_rejects_untrusted_filing_url(fetcher, filing):
    event = make_event(filing)

    event.payload.filing_url = (
        "https://example.com/private-document"
    )

    with pytest.raises(ValueError):
        await fetcher.handle_event(event)

    fetcher.edgar_client._get.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejects_path_traversal(fetcher, filing):
    event = make_event(filing)

    event.payload.filing_url = (
        "https://www.sec.gov/Archives/edgar/data/"
        "320193/000032019326000001/../secret.txt"
    )

    with pytest.raises(ValueError):
        await fetcher.handle_event(event)


@pytest.mark.asyncio
async def test_rejects_empty_document(fetcher, filing):
    event = make_event(filing)

    fetcher.edgar_client._get.return_value = (
        SimpleNamespace(content=b"")
    )

    with pytest.raises(ValueError, match="empty document"):
        await fetcher.handle_event(event)
