# SECAgents

**An event-driven, multi-agent SEC EDGAR ingestion pipeline built on OpenAgentFabric.**

**Version:** 0.1.0  
**Python:** 3.12  
**License:** Apache 2.0

SECAgents discovers SEC EDGAR filings, downloads their source documents, and extracts structured information using three independently running agents connected through Redis Streams.

The application is built on [OpenAgentFabric](https://github.com/costab06/OpenAgentFabric), which provides the shared agent runtime, event bus, correlation tracking, and consumer-group infrastructure.

**SECAgents v0.1.0 is an engineering demonstration**, not an investment-recommendation service, a production financial-data platform, or a guarantee of comprehensive financial-statement extraction.

## Architecture

```text
                  SEC EDGAR
                      |
                      v
                 +---------+
                 | Watcher |
                 +---------+
                      |
                      | document.discovered
                      v
                Redis Streams
                      |
                      v
                 +---------+
                 | Fetcher |
                 +---------+
                      |
                      | downloaded document
                      v
                Redis Streams
                      |
                      v
                 +---------+
                 | Parser  |
                 +---------+
                      |
                      v
               Structured artifacts
                  parsed.json
```

The pipeline consists of three agents:

- **Watcher** polls SEC EDGAR for recent filings from enabled companies. It publishes discovery events and maintains Redis-backed markers to prevent repeated publication within the configured namespace.
- **Fetcher** downloads discovered filing documents and records checksums.
- **Parser** processes downloaded filings, extracts inline XBRL facts and related context, and writes structured artifacts.

Each agent runs independently. Redis Streams provides the event transport between stages.

OpenAgentFabric supplies the common infrastructure used by these agents, including message consumption, correlation tracking, and agent lifecycle behavior.

## Demonstrated results

In a local demonstration using four companies, the pipeline processed two filings each for Apple, Microsoft, Amazon, and JPMorgan Chase.

| Company | Filings processed |
|---|---:|
| Apple | 2 |
| Microsoft | 2 |
| Amazon | 2 |
| JPMorgan Chase | 2 |
| **Total** | **8** |

The demonstration produced eight `parsed.json` artifacts.

After processing, both the Fetcher and Parser Redis consumer groups reported:

- **Pending messages:** 0
- **Consumer lag:** 0

The SECAgents test suite passed **49 tests**.

In a separate Apple financial-summary validation, **18 of 18 selected facts** matched SEC Company Facts for the tested filing.

These results establish the behavior observed in the tested configurations. They are not guarantees about processing throughput, recovery under every failure condition, coverage across all issuers, or the accuracy of every extracted financial fact.

## Requirements

- Linux, macOS, or another environment capable of running Python 3.12 and Redis
- Python 3.12
- Git
- A running Redis server
- Network access to SEC EDGAR
- An SEC-compliant application identity supplied through `SEC_USER_AGENT`

The development configuration uses Redis at:

```text
redis://localhost:6380/0
```

You can use a different Redis endpoint by setting `REDIS_URL` consistently for all agents and maintenance commands.

## Installation

SECAgents depends on OpenAgentFabric v0.1.0. The framework is maintained in a separate repository.

The following procedure installs OpenAgentFabric from its versioned GitHub release and then installs SECAgents.

### 1. Clone SECAgents

```bash
git clone https://github.com/costab06/SECAgents.git
cd SECAgents
```

### 2. Create a Python environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
```

### 3. Install OpenAgentFabric

```bash
python -m pip install \
  "openagentfabric @ git+https://github.com/costab06/OpenAgentFabric.git@v0.1.0"
```

This installs the framework from its `v0.1.0` Git tag. A sibling checkout of the framework is not required.

### 4. Install SECAgents

```bash
python -m pip install -e ".[dev]"
```

The `dev` extra installs development and testing dependencies.

### 5. Verify the installation

```bash
python -m pip check
python -m pytest -q
```

The release candidate was also tested in a fresh Python 3.12 environment with OpenAgentFabric installed directly from the GitHub tag. The tests passed.

**Important:** The installation instructions assume the GitHub repositories are accessible over HTTPS. If the repositories are private, appropriate GitHub access is required.

## Configuration

### Company selection

Edit:

```text
config/companies.yaml
```

This file controls which companies the Watcher monitors.

The demonstration configuration includes Apple, Microsoft, Amazon, and JPMorgan Chase.

### SEC application identity

The SEC expects automated clients to identify themselves appropriately.

Set `SEC_USER_AGENT` before running the Watcher or Fetcher:

```bash
export SEC_USER_AGENT="Your Application your-email@example.com"
```

Replace the example with an identity and contact address you control.

Do not use the example address as your actual application identity.

Follow the SEC's published automated-access policies, including applicable request-rate limits.

### Environment variables

| Variable | Development default | Used by |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6380/0` | All agents and reset utility |
| `SEC_MARKER_PREFIX` | `secagent:multicompany:v1` | Watcher and reset utility |
| `SEC_ARTIFACT_ROOT` | `data/filings` | Fetcher, Parser, and reset utility |
| `SEC_USER_AGENT` | No public default; must be supplied | Watcher and Fetcher |

Set environment variables in each terminal used to launch an agent, or provide them through your preferred environment-management mechanism.

All agents must use compatible Redis and artifact-root settings.

## Running the pipeline

Start Redis before launching the agents.

The demonstration configuration expects Redis on port **6380**. If your Redis server uses another port, set `REDIS_URL` accordingly.

Open three terminals in the SECAgents repository, activate the Python environment in each, and start the agents in the following order.

### Terminal 1 — Parser

```bash
source .venv/bin/activate
./start_parser.sh
```

### Terminal 2 — Fetcher

```bash
source .venv/bin/activate
export SEC_USER_AGENT="Your Application your-email@example.com"
./start_fetcher.sh
```

### Terminal 3 — Watcher

```bash
source .venv/bin/activate
export SEC_USER_AGENT="Your Application your-email@example.com"
./start_watcher.sh
```

The Watcher runs continuously, polling every **300 seconds** and inspecting up to **two recent qualifying filings per enabled company** on each cycle.

Redis publication markers prevent the same filing from being republished within the configured marker namespace.

### Python entry points

The corresponding module entry points are:

```bash
python -m secagent.agents.run_parser
```

```bash
python -m secagent.agents.run_fetcher
```

```bash
python -m secagent.agents.run_watcher \
  --continuous \
  --interval 300 \
  --limit 2
```

The shell launchers provide the repository's standard startup procedure.

### Shutdown

For an orderly shutdown:

1. Stop the Watcher first to prevent new discovery events.
2. Allow the Fetcher and Parser to finish processing outstanding messages.
3. Stop the Fetcher and Parser.

Stopping consumers before the pipeline drains may leave messages pending for later recovery.

## Verifying a demonstration run

Verification involves checking both Redis delivery state and the resulting artifacts.

### 1. Inspect Redis consumer groups

For the development configuration:

```bash
redis-cli -p 6380 XINFO GROUPS secagent.multicompany.v1
```

After the pipeline finishes processing, inspect the Fetcher and Parser groups.

The expected settled state is:

```text
pending: 0
lag: 0
```

These counters indicate message-delivery progress. They do not independently establish that every filing was parsed successfully.

### 2. Inspect generated artifacts

Structured filing artifacts are written beneath the configured `SEC_ARTIFACT_ROOT`, which defaults to:

```text
data/filings
```

To find parsed outputs:

```bash
find data/filings -name parsed.json -type f
```

To count them:

```bash
find data/filings -name parsed.json -type f | wc -l
```

For the previously demonstrated two-filings-per-company run, eight parsed files were observed.

A new run may produce a different count depending on the configured companies, currently available filings, Redis publication markers, and previously processed documents.

### 3. Inspect the extracted data

Open a generated `parsed.json` file to inspect the structured extraction.

For example:

```bash
python -m json.tool path/to/parsed.json
```

Replace `path/to/parsed.json` with an actual path returned by the `find` command.

Successful message delivery and successful JSON creation should both be verified before treating a filing as processed.

## Resetting the demonstration

SECAgents includes a Python reset utility:

```text
scripts/reset_demo.py
```

To inspect the supported options:

```bash
python scripts/reset_demo.py --help
```

To reset the dedicated demonstration state:

```bash
python scripts/reset_demo.py
```

The reset utility is designed to remove the dedicated demo Redis stream, its consumer groups, publication markers, and correlation records discoverable from `document.discovered` entries still present in that stream.

A normal reset preserves downloaded and parsed artifacts.

### Removing artifacts as well

The utility also supports an `--all` mode:

```bash
python scripts/reset_demo.py --all
```

**Warning:** The `--all` option recursively removes the configured `SEC_ARTIFACT_ROOT`, normally `data/filings`, including previously generated validation artifacts.

Preserve any research outputs you want to retain before using this option.

The utility requests confirmation unless `--yes` is provided.

Use the reset utility only with a dedicated demonstration stream and marker namespace. Do not use it against shared or production Redis resources.

Correlation records not represented by retained discovery events may remain until their TTL expires.

## Validation utilities

The repository includes additional validation scripts:

```text
scripts/validate_apple_summary.py
scripts/validate_sec_companyfacts.py
```

These utilities support targeted comparisons of extracted information against SEC reference data.

They are separate from the normal three-agent ingestion pipeline.

The reported Apple validation matched 18 of 18 selected facts for the tested filing. That is a bounded validation result, not a general accuracy claim for all issuers or filings.

## Testing

Run the complete test suite with:

```bash
python -m pytest -q
```

Check installed dependency consistency with:

```bash
python -m pip check
```

OpenAgentFabric v0.1.0 separately passed **67 tests** in its release environment.

SECAgents passed **49 tests** in its release validation, including a subsequent clean-environment test using the tagged OpenAgentFabric dependency.

Automated tests and a successful demonstration are complementary: tests verify defined behaviors, while an end-to-end run verifies interaction among the agents, Redis, SEC EDGAR, and the filesystem.

## Project structure

```text
SECAgents/
├── config/
│   └── companies.yaml
├── scripts/
│   ├── reset_demo.py
│   ├── validate_apple_summary.py
│   └── validate_sec_companyfacts.py
├── src/
│   └── secagent/
│       └── agents/
│           ├── ...
│           ├── run_watcher.py
│           ├── run_fetcher.py
│           └── run_parser.py
├── tests/
├── start_watcher.sh
├── start_fetcher.sh
├── start_parser.sh
├── pyproject.toml
├── LICENSE
└── README.md
```

The `src/secagent/agents/` directory contains the Watcher, Fetcher, Parser, and their launch modules.

The `scripts/` directory contains the reset and validation utilities.

OpenAgentFabric is a separate Python package and repository, not a copied component of SECAgents.

## Scope and limitations

Version 0.1.0 establishes a working multi-agent SEC filing ingestion demonstration with structured artifact generation.

It does not claim:

- Comprehensive extraction of every financial statement or disclosure.
- Complete coverage of SEC filing types or issuer-specific formatting.
- Guaranteed accuracy for every inline XBRL fact.
- Proven throughput or scalability under production workloads.
- Exhaustive validation of all failure and recovery scenarios.
- Investment advice, securities valuation, or trading recommendations.

Redis Streams and the OpenAgentFabric runtime provide infrastructure for event delivery and recovery behavior, but production suitability requires additional operational validation.

## Related project

**[OpenAgentFabric](https://github.com/costab06/OpenAgentFabric)**

SECAgents uses OpenAgentFabric v0.1.0 as its shared agent framework.

The framework and application are separately versioned so they can evolve independently.


## SEC data and responsible access

SEC EDGAR data is provided by the U.S. Securities and Exchange Commission and reporting issuers.

Users are responsible for following the SEC's applicable automated-access policies, including proper identification and request-rate limits.

SECAgents is an independent open-source demonstration and is not affiliated with or endorsed by the SEC.

## License

Licensed under the **Apache License, Version 2.0**.

See [LICENSE](LICENSE) for the complete license text.
