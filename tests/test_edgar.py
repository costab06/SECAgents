
import httpx
import pytest

from secagent.clients.edgar import EdgarClient, Filing


@pytest.fixture
def submissions_payload():
    return {
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-26-000001",
                    "0000320193-26-000002",
                    "0000320193-26-000003",
                ],
                "form": ["10-K", "8-K", "10-Q"],
                "filingDate": [
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-03",
                ],
                "primaryDocument": [
                    "annual.htm",
                    "current.htm",
                    "quarterly.htm",
                ],
            }
        },
    }


@pytest.mark.asyncio
async def test_recent_filings_filter(submissions_payload):
    def handler(request):
        return httpx.Response(200, json=submissions_payload)

    async with EdgarClient(
        user_agent="SECAgent test@example.com",
        transport=httpx.MockTransport(handler),
    ) as client:
        filings = await client.get_recent_filings(
            cik=320193,
            forms={"10-K", "10-Q"},
        )

    assert len(filings) == 2
    assert [filing.form for filing in filings] == ["10-K", "10-Q"]
    assert filings[0].company_name == "Apple Inc."


@pytest.mark.asyncio
async def test_document_url(submissions_payload):
    def handler(request):
        return httpx.Response(200, json=submissions_payload)

    async with EdgarClient(
        user_agent="SECAgent test@example.com",
        transport=httpx.MockTransport(handler),
    ) as client:
        filings = await client.get_recent_filings(320193)

    assert filings[0].document_url == (
        "https://www.sec.gov/Archives/edgar/data/"
        "320193/000032019326000001/annual.htm"
    )


@pytest.mark.asyncio
async def test_retry_on_server_error():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1

        if calls == 1:
            return httpx.Response(503)

        return httpx.Response(
            200,
            json={"name": "Apple Inc."},
        )

    async with EdgarClient(
        user_agent="SECAgent test@example.com",
        requests_per_second=10,
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await client.get_submissions(320193)

    assert calls == 2
    assert result["name"] == "Apple Inc."


@pytest.mark.asyncio
async def test_invalid_cik():
    async with EdgarClient(
        user_agent="SECAgent test@example.com",
    ) as client:
        with pytest.raises(ValueError):
            await client.get_submissions(0)


@pytest.mark.asyncio
async def test_download_filing():
    def handler(request):
        return httpx.Response(
            200,
            content=b"<html>SEC filing</html>",
        )

    filing = Filing(
        cik=320193,
        company_name="Apple Inc.",
        form="10-K",
        accession_number="0000320193-26-000001",
        filing_date=__import__("datetime").date(2026, 1, 1),
        primary_document="annual.htm",
    )

    async with EdgarClient(
        user_agent="SECAgent test@example.com",
        transport=httpx.MockTransport(handler),
    ) as client:
        content = await client.download_filing(filing)

    assert content == b"<html>SEC filing</html>"
