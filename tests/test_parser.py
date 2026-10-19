
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from shared.eventbus.events import (
    DocumentFetchedEvent,
    DocumentFetchedPayload,
    EventType,
)
from shared.models import (
    AgentName,
    ArtifactRef,
    ArtifactType,
)

from secagent.agents.parser import SecParser


HTML = b"""
<html>
<head><title>Example 10-Q</title></head>
<body>
<h1>Quarterly Report</h1>
<p>For the period ended June 30.</p>
<table>
<tr><th>Metric</th><th>2026</th><th>2025</th></tr>
<tr><td>Revenue</td><td>125</td><td>100</td></tr>
<tr><td>Net income</td><td colspan="2">50</td></tr>
</table>
<p>Additional disclosures.</p>
</body>
</html>
"""


@pytest.fixture
def parser(tmp_path):
    return SecParser(
        event_bus=SimpleNamespace(),
        correlation_registry=SimpleNamespace(),
        artifact_root=tmp_path,
    )


@pytest.fixture
def fetched_event(tmp_path):
    source = (
        tmp_path
        / "320193"
        / "0000320193-26-000001"
        / "quarterly.htm"
    )
    source.parent.mkdir(parents=True)
    source.write_bytes(HTML)

    artifact = ArtifactRef(
        artifact_id="sec:320193:0000320193-26-000001:raw",
        artifact_type=ArtifactType.RAW_DOCUMENT,
        uri=source.as_uri(),
        checksum=(
            "sha256:" + hashlib.sha256(HTML).hexdigest()
        ),
    )

    return DocumentFetchedEvent(
        source_agent=AgentName.FETCHER,
        correlation_id=uuid4(),
        payload=DocumentFetchedPayload(
            cik="320193",
            accession_number="0000320193-26-000001",
            company_name="Apple Inc.",
            filing_type="10-Q",
            artifact=artifact,
        ),
    )


def test_extracts_document_structure():
    document = SecParser._parse_html(HTML)

    assert document["title"] == "Example 10-Q"
    assert document["table_count"] == 1
    assert document["block_count"] == 4

    assert [
        block["type"] for block in document["blocks"]
    ] == [
        "heading",
        "paragraph",
        "table",
        "paragraph",
    ]

    assert "Quarterly Report" in document["text"]
    assert "Additional disclosures" in document["text"]


def test_preserves_financial_table():
    document = SecParser._parse_html(HTML)

    table = next(
        block
        for block in document["blocks"]
        if block["type"] == "table"
    )

    assert len(table["rows"]) == 3
    assert table["rows"][0][0]["header"] is True
    assert table["rows"][1][0]["text"] == "Revenue"
    assert table["rows"][1][1]["text"] == "125"
    assert table["rows"][2][1]["colspan"] == 2


@pytest.mark.asyncio
async def test_parser_creates_downstream_event(
    parser,
    fetched_event,
):
    downstream = await parser.handle_event(fetched_event)

    assert len(downstream) == 1

    event = downstream[0]

    assert event.event_type == EventType.DOCUMENT_PARSED
    assert event.source_agent == AgentName.PARSER
    assert event.correlation_id == fetched_event.correlation_id
    assert event.causation_id == fetched_event.event_id

    parsed_artifact = event.payload.parsed_artifact

    assert (
        parsed_artifact.artifact_type
        == ArtifactType.PARSED_DOCUMENT
    )

    path = Path(
        parsed_artifact.uri.removeprefix("file://")
    )
    assert path.exists()

    data = json.loads(path.read_text())

    assert data["source"]["company_name"] == "Apple Inc."
    assert data["document"]["table_count"] == 1

    checksum = (
        "sha256:"
        + hashlib.sha256(path.read_bytes()).hexdigest()
    )

    assert parsed_artifact.checksum == checksum


@pytest.mark.asyncio
async def test_parser_retry_is_deterministic(
    parser,
    fetched_event,
):
    first = await parser.handle_event(fetched_event)
    second = await parser.handle_event(fetched_event)

    first_artifact = first[0].payload.parsed_artifact
    second_artifact = second[0].payload.parsed_artifact

    assert first_artifact.artifact_id == second_artifact.artifact_id
    assert first_artifact.uri == second_artifact.uri
    assert first_artifact.checksum == second_artifact.checksum


@pytest.mark.asyncio
async def test_rejects_checksum_mismatch(
    parser,
    fetched_event,
):
    fetched_event.payload.artifact.checksum = (
        "sha256:" + "0" * 64
    )

    with pytest.raises(
        ValueError,
        match="checksum mismatch",
    ):
        await parser.handle_event(fetched_event)


@pytest.mark.asyncio
async def test_rejects_external_file(
    parser,
    fetched_event,
    tmp_path,
):
    external = tmp_path.parent / "outside-secagent.htm"
    fetched_event.payload.artifact.uri = external.as_uri()

    with pytest.raises(
        ValueError,
        match="outside the artifact root",
    ):
        await parser.handle_event(fetched_event)
