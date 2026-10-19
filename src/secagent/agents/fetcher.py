
"""SEC filing fetcher implemented as an OpenAgentFabric agent."""

import asyncio
import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path

from shared.agent.base import BaseAgent
from shared.correlation.registry import CorrelationRegistry
from shared.eventbus.base import EventBus
from shared.eventbus.events import (
    DocumentDiscoveredPayload,
    DocumentFetchedEvent,
    DocumentFetchedPayload,
    EventEnvelope,
    EventType,
)
from shared.models import AgentName, ArtifactRef, ArtifactType

from secagent.clients.edgar import EdgarClient

logger = logging.getLogger(__name__)

ACCESSION_PATTERN = re.compile(r"^\d{10}-\d{2}-\d{6}$")


class SecFetcher(BaseAgent):
    """Download SEC filings and publish artifact references."""

    def __init__(
        self,
        event_bus: EventBus,
        correlation_registry: CorrelationRegistry,
        edgar_client: EdgarClient,
        artifact_root: Path,
        **agent_options,
    ):
        super().__init__(
            name=AgentName.FETCHER,
            event_bus=event_bus,
            correlation_registry=correlation_registry,
            subscribed_event_types={EventType.DOCUMENT_DISCOVERED},
            **agent_options,
        )

        self.edgar_client = edgar_client
        self.artifact_root = Path(artifact_root).resolve()

    async def handle_event(
        self,
        event: EventEnvelope,
    ) -> list[EventEnvelope]:
        payload = DocumentDiscoveredPayload.model_validate(
            event.payload
        )

        artifact = await self._fetch_and_store(payload)

        downstream = DocumentFetchedEvent(
            source_agent=AgentName.FETCHER,
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            payload=DocumentFetchedPayload(
                cik=payload.cik,
                accession_number=payload.accession_number,
                company_name=payload.company_name,
                filing_type=payload.filing_type,
                artifact=artifact,
            ),
        )

        logger.info(
            "Fetched %s %s accession=%s artifact=%s",
            payload.company_name,
            payload.filing_type,
            payload.accession_number,
            artifact.uri,
        )

        return [downstream]

    async def _fetch_and_store(
        self,
        payload: DocumentDiscoveredPayload,
    ) -> ArtifactRef:
        if not payload.cik.isdigit() or int(payload.cik) <= 0:
            raise ValueError("Invalid SEC CIK")

        if not ACCESSION_PATTERN.fullmatch(
            payload.accession_number
        ):
            raise ValueError("Invalid SEC accession number")

        cik = int(payload.cik)
        accession = payload.accession_number
        compact = accession.replace("-", "")

        # Derive the URL from validated identifiers rather than
        # following an arbitrary URL contained in an event.
        # The primary document is taken from the SEC URL after
        # verifying its exact archive directory.
        from urllib.parse import urlsplit, unquote

        parsed = urlsplit(payload.filing_url)

        expected_prefix = (
            f"/Archives/edgar/data/{cik}/{compact}/"
        )

        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.sec.gov"
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith(expected_prefix)
        ):
            raise ValueError("Unexpected SEC filing URL")

        document = unquote(
            parsed.path[len(expected_prefix):]
        )

        if (
            not document
            or document in {".", ".."}
            or "/" in document
            or "\\" in document
            or "%" in document
            or any(ord(char) < 32 for char in document)
        ):
            raise ValueError("Unsafe SEC document name")

        directory = (
            self.artifact_root
            / str(cik)
            / accession
        )
        target = directory / document

        # Deterministic path: reprocessing the same filing does
        # not create a new artifact name.
        content = await self.edgar_client._get(
            payload.filing_url
        )
        data = content.content

        if not data:
            raise ValueError("SEC returned an empty document")

        digest = hashlib.sha256(data).hexdigest()

        await asyncio.to_thread(
            self._write_atomic,
            target,
            data,
        )

        return ArtifactRef(
            artifact_id=f"sec:{cik}:{accession}:raw",
            artifact_type=ArtifactType.RAW_DOCUMENT,
            uri=target.as_uri(),
            checksum=f"sha256:{digest}",
        )

    @staticmethod
    def _write_atomic(target: Path, data: bytes) -> None:
        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=".secagent-",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temporary, target)

        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
