
"""Display recent Apple filings from SEC EDGAR."""

import asyncio
import os

from secagent.clients.edgar import EdgarClient

APPLE_CIK = 320193


async def main() -> None:
    user_agent = os.environ.get("SEC_USER_AGENT")

    if not user_agent:
        raise SystemExit(
            "Set SEC_USER_AGENT to an identifying application name "
            "and real contact email before accessing EDGAR."
        )

    async with EdgarClient(user_agent=user_agent) as client:
        filings = await client.get_recent_filings(
            cik=APPLE_CIK,
            forms={"10-K", "10-Q"},
            limit=5,
        )

        for filing in filings:
            print(
                f"{filing.filing_date} "
                f"{filing.form:5} "
                f"{filing.accession_number}"
            )
            print(f"  {filing.document_url}")


if __name__ == "__main__":
    asyncio.run(main())
