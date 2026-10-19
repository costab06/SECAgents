
"""Asynchronous client for SEC EDGAR public filing data."""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class Filing:
    cik: int
    company_name: str
    form: str
    accession_number: str
    filing_date: date
    primary_document: str

    @property
    def accession_number_compact(self) -> str:
        return self.accession_number.replace("-", "")

    @property
    def document_url(self) -> str:
        return (
            f"{ARCHIVES_BASE}/{self.cik}/"
            f"{self.accession_number_compact}/"
            f"{self.primary_document}"
        )

    @property
    def filing_id(self) -> str:
        return f"{self.cik}:{self.accession_number}"


class EdgarClient:
    """HTTP client for SEC submissions and filing documents.

    The SEC requests an identifying User-Agent and limits automated
    request rates. Configure the identity with your real contact details.
    """

    def __init__(
        self,
        user_agent: str,
        requests_per_second: float = 5.0,
        timeout_seconds: float = 30.0,
        max_retries: int = 4,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not user_agent.strip():
            raise ValueError("An identifying SEC User-Agent is required")
        if requests_per_second <= 0 or requests_per_second > 10:
            raise ValueError(
                "requests_per_second must be greater than 0 and at most 10"
            )
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")

        self._interval = 1.0 / requests_per_second
        self._last_request_time = 0.0
        self._rate_lock = asyncio.Lock()
        self._max_retries = max_retries

        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            transport=transport,
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json, text/html, */*",
            },
            follow_redirects=True,
        )

    async def __aenter__(self) -> "EdgarClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _throttle(self) -> None:
        loop = asyncio.get_running_loop()

        async with self._rate_lock:
            now = loop.time()
            delay = max(
                0.0,
                self._interval - (now - self._last_request_time),
            )
            if delay:
                await asyncio.sleep(delay)
            self._last_request_time = loop.time()

    async def _get(self, url: str) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            await self._throttle()

            try:
                response = await self._client.get(url)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == self._max_retries:
                    raise

                await asyncio.sleep(min(2 ** attempt, 30))
                continue

            if (
                response.status_code in RETRYABLE_STATUSES
                and attempt < self._max_retries
            ):
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = (
                        max(0.0, float(retry_after))
                        if retry_after is not None
                        else min(2 ** attempt, 30)
                    )
                except ValueError:
                    delay = min(2 ** attempt, 30)

                logger.warning(
                    "SEC returned HTTP %s; retrying in %.1f seconds",
                    response.status_code,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            response.raise_for_status()
            return response

        raise RuntimeError("Unexpected retry-loop termination")

    async def get_submissions(self, cik: int) -> dict[str, Any]:
        if cik <= 0:
            raise ValueError("CIK must be a positive integer")

        url = f"{SUBMISSIONS_BASE}/CIK{cik:010d}.json"
        response = await self._get(url)
        return response.json()

    async def get_recent_filings(
        self,
        cik: int,
        forms: set[str] | None = None,
        limit: int | None = 20,
    ) -> list[Filing]:
        """Return matching filings from the recent submissions array.

        Does not traverse older supplemental submission files.
        """
        if limit is not None and limit < 0:
            raise ValueError("limit must be nonnegative or None")
        if limit == 0:
            return []

        submissions = await self.get_submissions(cik)
        company_name = submissions.get("name", "")
        recent = submissions["filings"]["recent"]

        accessions = recent["accessionNumber"]
        form_values = recent["form"]
        dates = recent["filingDate"]
        documents = recent["primaryDocument"]

        lengths = {
            len(accessions),
            len(form_values),
            len(dates),
            len(documents),
        }
        if len(lengths) != 1:
            raise ValueError("SEC submissions arrays have unequal lengths")

        selected_forms = forms if forms is not None else {"10-K", "10-Q"}
        filings = []

        for accession, form, filing_date, document in zip(
            accessions,
            form_values,
            dates,
            documents,
        ):
            if form not in selected_forms:
                continue

            if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
                raise ValueError(
                    f"Unexpected SEC accession number: {accession}"
                )

            filings.append(
                Filing(
                    cik=cik,
                    company_name=company_name,
                    form=form,
                    accession_number=accession,
                    filing_date=date.fromisoformat(filing_date),
                    primary_document=document,
                )
            )

            if limit is not None and len(filings) >= limit:
                break

        return filings

    async def download_filing(self, filing: Filing) -> bytes:
        response = await self._get(filing.document_url)
        return response.content
