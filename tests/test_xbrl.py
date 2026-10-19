
from secagent.parsing.xbrl import extract_inline_xbrl


SAMPLE = b"""
<html>
<body>
<ix:header>
  <ix:resources>
    <xbrli:context id="c1">
      <xbrli:entity>
        <xbrli:identifier scheme="http://www.sec.gov/CIK">
          0000320193
        </xbrli:identifier>
      </xbrli:entity>
      <xbrli:period>
        <xbrli:startDate>2026-01-01</xbrli:startDate>
        <xbrli:endDate>2026-06-30</xbrli:endDate>
      </xbrli:period>
    </xbrli:context>
    <xbrli:unit id="usd">
      <xbrli:measure>iso4217:USD</xbrli:measure>
    </xbrli:unit>
  </ix:resources>
</ix:header>

<p>
  Revenue:
  <ix:nonFraction
    name="us-gaap:Revenues"
    contextRef="c1"
    unitRef="usd"
    decimals="-6"
    scale="6">
    125
  </ix:nonFraction>
</p>
</body>
</html>
"""


def test_extracts_numeric_fact():
    result = extract_inline_xbrl(SAMPLE)

    assert result["fact_count"] == 1

    fact = result["facts"][0]

    assert fact["name"] == "us-gaap:Revenues"
    assert fact["context_ref"] == "c1"
    assert fact["unit_ref"] == "usd"
    assert fact["decimals"] == "-6"
    assert fact["scale"] == "6"
    assert fact["value"] == "125"
    assert fact["numeric"] is True


def test_extracts_context():
    result = extract_inline_xbrl(SAMPLE)

    context = result["contexts"]["c1"]

    assert context["entity_identifier"] == "0000320193"
    assert context["start_date"] == "2026-01-01"
    assert context["end_date"] == "2026-06-30"


def test_extracts_unit():
    result = extract_inline_xbrl(SAMPLE)

    assert result["units"]["usd"]["measures"] == [
        "iso4217:USD"
    ]


def test_empty_document():
    result = extract_inline_xbrl(
        b"<html><body>No XBRL here.</body></html>"
    )

    assert result["fact_count"] == 0
    assert result["context_count"] == 0
    assert result["unit_count"] == 0
