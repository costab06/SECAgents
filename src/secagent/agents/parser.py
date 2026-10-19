
"""Parse downloaded SEC filings into structured JSON artifacts."""

import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, Tag
from secagent.parsing.xbrl import extract_inline_xbrl
from secagent.parsing.xbrl_normalize import normalize_xbrl

from shared.agent.base import BaseAgent
from shared.correlation.registry import CorrelationRegistry
from shared.eventbus.base import EventBus
from shared.eventbus.events import (
    DocumentFetchedPayload,
    DocumentParsedEvent,
    DocumentParsedPayload,
    EventEnvelope,
    EventType,
)
from shared.models import AgentName, ArtifactRef, ArtifactType


class SecParser(BaseAgent):
    """Convert SEC filing HTML into structured document artifacts."""

    def __init__(
        self,
        event_bus: EventBus,
        correlation_registry: CorrelationRegistry,
        artifact_root: Path,
        **agent_options,
    ):
        super().__init__(
            name=AgentName.PARSER,
            event_bus=event_bus,
            correlation_registry=correlation_registry,
            subscribed_event_types={EventType.DOCUMENT_FETCHED},
            **agent_options,
        )

        self.artifact_root = Path(artifact_root).resolve()

    async def handle_event(
        self,
        event: EventEnvelope,
    ) -> list[EventEnvelope]:
        payload = DocumentFetchedPayload.model_validate(
            event.payload
        )

        parsed_artifact = await asyncio.to_thread(
            self._parse_and_store,
            payload,
        )

        return [
            DocumentParsedEvent(
                source_agent=AgentName.PARSER,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload=DocumentParsedPayload(
                    source_artifact=payload.artifact,
                    parsed_artifact=parsed_artifact,
                ),
            )
        ]

    def _parse_and_store(
        self,
        payload: DocumentFetchedPayload,
    ) -> ArtifactRef:
        source = self._resolve_source(payload.artifact)

        raw = source.read_bytes()
        if not raw:
            raise ValueError("Source filing is empty")

        source_checksum = (
            "sha256:" + hashlib.sha256(raw).hexdigest()
        )

        if (
            payload.artifact.checksum is not None
            and source_checksum != payload.artifact.checksum
        ):
            raise ValueError("Source artifact checksum mismatch")

        document = self._parse_html(raw)
        xbrl = extract_inline_xbrl(raw)
        normalized_xbrl = normalize_xbrl(xbrl, raw)

        result = {
            "schema_version": "1.0",
            "source": {
                "cik": payload.cik,
                "accession_number": payload.accession_number,
                "company_name": payload.company_name,
                "filing_type": payload.filing_type,
                "artifact_id": payload.artifact.artifact_id,
                "artifact_uri": payload.artifact.uri,
                "checksum": source_checksum,
            },
            "document": document,
            "xbrl": xbrl,
            "normalized_xbrl": normalized_xbrl,
        }

        encoded = json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")

        target = (
            self.artifact_root
            / payload.cik
            / payload.accession_number
            / "parsed.json"
        )

        self._write_atomic(target, encoded)

        return ArtifactRef(
            artifact_id=(
                f"sec:{payload.cik}:"
                f"{payload.accession_number}:parsed"
            ),
            artifact_type=ArtifactType.PARSED_DOCUMENT,
            uri=target.as_uri(),
            checksum=(
                "sha256:"
                + hashlib.sha256(encoded).hexdigest()
            ),
        )

    def _resolve_source(
        self,
        artifact: ArtifactRef,
    ) -> Path:
        if artifact.artifact_type != ArtifactType.RAW_DOCUMENT:
            raise ValueError("Expected a raw document artifact")

        parsed = urlsplit(artifact.uri)

        if (
            parsed.scheme != "file"
            or parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Expected a local file artifact URI")

        path = Path(unquote(parsed.path)).resolve()

        if not path.is_relative_to(self.artifact_root):
            raise ValueError(
                "Source artifact is outside the artifact root"
            )

        if not path.is_file():
            raise FileNotFoundError(path)

        return path

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(value.split())

    @classmethod
    def _parse_html(cls, raw: bytes) -> dict:
        soup = BeautifulSoup(raw, "html.parser")

        for tag in soup(
            ["script", "style", "noscript", "iframe"]
        ):
            tag.decompose()

        root = soup.body or soup

        blocks = []
        text_parts = []

        block_tags = {
            "h1", "h2", "h3", "h4", "h5", "h6",
            "p", "li", "table",
        }

        def visit(node):
            if not isinstance(node, Tag):
                return

            if node.name == "table":
                table = cls._extract_table(node)
                if table["rows"]:
                    blocks.append(table)
                    text_parts.append(table["text"])
                return

            if node.name in block_tags:
                # If this block contains another recognized block,
                # recurse to avoid duplicating nested content.
                nested = any(
                    isinstance(child, Tag)
                    and child.name in block_tags
                    for child in node.children
                )

                if nested:
                    for child in node.children:
                        visit(child)
                    return

                text = cls._normalize_text(
                    node.get_text(" ", strip=True)
                )

                if text:
                    kind = (
                        "heading"
                        if node.name.startswith("h")
                        else "list_item"
                        if node.name == "li"
                        else "paragraph"
                    )

                    block = {
                        "type": kind,
                        "text": text,
                    }

                    if kind == "heading":
                        block["level"] = int(node.name[1])

                    blocks.append(block)
                    text_parts.append(text)

                return

            for child in node.children:
                visit(child)

        visit(root)

        return {
            "title": (
                cls._normalize_text(soup.title.get_text())
                if soup.title
                else None
            ),
            "blocks": blocks,
            "text": "\n\n".join(text_parts),
            "block_count": len(blocks),
            "table_count": sum(
                block["type"] == "table"
                for block in blocks
            ),
        }

    @classmethod
    def _extract_table(cls, table: Tag) -> dict:
        rows = []

        for tr in table.find_all("tr"):
            # Exclude rows from nested tables.
            if tr.find_parent("table") is not table:
                continue

            cells = []

            for cell in tr.find_all(
                ["th", "td"],
                recursive=False,
            ):
                text = cls._normalize_text(
                    cell.get_text(" ", strip=True)
                )

                def span(name):
                    try:
                        return max(
                            1,
                            int(cell.get(name, 1)),
                        )
                    except (TypeError, ValueError):
                        return 1

                cells.append({
                    "text": text,
                    "header": cell.name == "th",
                    "rowspan": span("rowspan"),
                    "colspan": span("colspan"),
                })

            if cells:
                rows.append(cells)

        table_text = "\n".join(
            " | ".join(cell["text"] for cell in row)
            for row in rows
        )

        return {
            "type": "table",
            "rows": rows,
            "text": table_text,
        }

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
