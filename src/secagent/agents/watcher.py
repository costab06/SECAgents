
"""SEC filing discovery and durable event publication."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone

from redis.asyncio import Redis

from shared.correlation.registry import CorrelationRegistry
from shared.eventbus.events import (
    DocumentDiscoveredEvent,
    DocumentDiscoveredPayload,
)
from shared.models import AgentName

from secagent.clients.edgar import EdgarClient, Filing
from collections.abc import Sequence
from secagent.config.companies import Company

logger = logging.getLogger(__name__)


# Both operations execute atomically on the Redis server.
#
# The marker is permanent for this application's namespace.
# Use a dedicated stream and marker prefix for each environment.
PUBLISH_ONCE_SCRIPT = """
local marker = KEYS[1]
local stream = KEYS[2]

local serialized_event = ARGV[1]

if redis.call('EXISTS', marker) == 1 then
    return {0, ''}
end

local message_id = redis.call(
    'XADD', stream, '*', 'event', serialized_event
)

redis.call('SET', marker, message_id)

return {1, message_id}
"""


@dataclass(frozen=True)
class WatcherResult:
    discovered: int
    published: int
    duplicates: int


class SecWatcher:
    """Poll SEC EDGAR and publish newly discovered filings."""

    def __init__(
        self,
        client: EdgarClient,
        redis: Redis,
        stream: str = "oaf.events",
        marker_prefix: str = "secagent:published",
        forms: set[str] | None = None,
    ):
        if not stream:
            raise ValueError("stream must not be empty")
        if not marker_prefix:
            raise ValueError("marker_prefix must not be empty")

        self.client = client
        self.redis = redis
        self.stream = stream
        self.marker_prefix = marker_prefix
        self.forms = (
            set(forms) if forms is not None else {"10-K", "10-Q"}
        )
        self.correlations = CorrelationRegistry(redis)

    def _marker_key(self, filing: Filing) -> str:
        return (
            f"{self.marker_prefix}:"
            f"{filing.cik}:{filing.accession_number}"
        )

    async def publish_filing(self, filing: Filing) -> bool:
        """Publish one filing at most once per marker namespace.

        Returns True if published, False if already published.
        """
        # Derive a stable correlation ID from the filing identity.
        #
        # This date is part of the filing's stable identity, rather
        # than the current time of the polling process.
        trigger_timestamp = datetime.combine(
            filing.filing_date,
            time.min,
            tzinfo=timezone.utc,
        )

        record = await self.correlations.create(
            trigger_type="sec.filing.discovered",
            trigger_timestamp=trigger_timestamp,
            business_fields={
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

        result = await self.redis.eval(
            PUBLISH_ONCE_SCRIPT,
            2,
            self._marker_key(filing),
            self.stream,
            event.model_dump_json(),
        )

        published = int(result[0]) == 1

        if published:
            logger.info(
                "Published %s %s accession=%s event=%s "
                "correlation=%s redis_message=%s",
                filing.company_name,
                filing.form,
                filing.accession_number,
                event.event_id,
                record.correlation_id,
                result[1],
            )
        else:
            logger.info(
                "Already published: %s %s accession=%s",
                filing.company_name,
                filing.form,
                filing.accession_number,
            )

        return published

    async def poll(
        self,
        cik: int,
        limit: int = 5,
    ) -> WatcherResult:
        """Discover and publish recent qualifying filings."""
        filings = await self.client.get_recent_filings(
            cik=cik,
            forms=self.forms,
            limit=limit,
        )

        published = 0

        # Process older filings first when publishing a batch.
        for filing in reversed(filings):
            if await self.publish_filing(filing):
                published += 1

        return WatcherResult(
            discovered=len(filings),
            published=published,
            duplicates=len(filings) - published,
        )

    async def run(
        self,
        cik: int,
        poll_interval_seconds: float = 300.0,
        limit: int = 5,
    ) -> None:
        """Run until cancelled."""
        if poll_interval_seconds <= 0:
            raise ValueError(
                "poll_interval_seconds must be positive"
            )

        while True:
            try:
                result = await self.poll(cik, limit)
                logger.info(
                    "Poll complete: discovered=%d published=%d "
                    "duplicates=%d",
                    result.discovered,
                    result.published,
                    result.duplicates,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("SEC Watcher poll failed")

            await asyncio.sleep(poll_interval_seconds)


    async def poll_companies(
        self,
        companies: Sequence[Company],
        limit: int = 5,
    ) -> dict[str, WatcherResult]:
        """Poll each configured company independently."""
        results: dict[str, WatcherResult] = {}

        for company in companies:
            if not company.enabled:
                continue

            try:
                result = await self.poll(
                    cik=company.cik,
                    limit=limit,
                )
                results[company.ticker] = result

                logger.info(
                    "Company poll complete: ticker=%s cik=%s "
                    "discovered=%d published=%d duplicates=%d",
                    company.ticker,
                    company.cik,
                    result.discovered,
                    result.published,
                    result.duplicates,
                )

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception(
                    "Company poll failed: ticker=%s cik=%s",
                    company.ticker,
                    company.cik,
                )

        return results

    async def run_companies(
        self,
        companies: Sequence[Company],
        poll_interval_seconds: float = 300.0,
        limit: int = 5,
    ) -> None:
        """Continuously poll all configured companies."""
        if poll_interval_seconds <= 0:
            raise ValueError(
                "poll_interval_seconds must be positive"
            )

        if not companies:
            raise ValueError("No companies configured for monitoring")

        while True:
            results = await self.poll_companies(
                companies=companies,
                limit=limit,
            )

            logger.info(
                "Multi-company poll complete: companies=%d "
                "discovered=%d published=%d duplicates=%d",
                len(results),
                sum(r.discovered for r in results.values()),
                sum(r.published for r in results.values()),
                sum(r.duplicates for r in results.values()),
            )

            await asyncio.sleep(poll_interval_seconds)
