
from secagent.parsing.xbrl_normalize import (
    extract_context_details,
    normalize_numeric_fact,
    normalize_xbrl,
)


HTML = b"""
<html>
<body>
<ix:header>
  <ix:resources>
    <xbrli:context id="c1">
      <xbrli:entity>
        <xbrli:identifier>0000320193</xbrli:identifier>
      </xbrli:entity>
      <xbrli:period>
        <xbrli:startDate>2026-04-01</xbrli:startDate>
        <xbrli:endDate>2026-06-30</xbrli:endDate>
      </xbrli:period>
    </xbrli:context>
    <xbrli:context id="c2">
      <xbrli:period>
        <xbrli:instant>2026-06-30</xbrli:instant>
      </xbrli:period>
      <xbrli:scenario>
        <xbrldi:explicitMember
          dimension="us-gaap:StatementBusinessSegmentsAxis">
          aapl:ServicesMember
        </xbrldi:explicitMember>
      </xbrli:scenario>
    </xbrli:context>
  </ix:resources>
</ix:header>
</body>
</html>
"""


def fact(value, **kwargs):
    return {
        "name": "us-gaap:Revenues",
        "value": value,
        "numeric": True,
        "scale": "0",
        "sign": None,
        "format": "ixt:num-dot-decimal",
        "context_ref": "c1",
        **kwargs,
    }


def test_scale_and_precision():
    result = normalize_numeric_fact({
        **fact("125,000"),
        "scale": "6",
    })

    assert result["normalization_status"] == "normalized"
    assert result["normalized_value"] == "125000000000"


def test_negative_sign():
    result = normalize_numeric_fact({
        **fact("42.5"),
        "sign": "-",
        "scale": "6",
    })

    assert result["normalized_value"] == "-42500000"


def test_parenthesized_negative():
    result = normalize_numeric_fact(fact("(1,250)"))

    assert result["normalized_value"] == "-1250"


def test_unsupported_format_is_unresolved():
    result = normalize_numeric_fact({
        **fact("1.234,56"),
        "format": "ixt:num-comma-decimal",
    })

    assert result["normalization_status"] == "unresolved"
    assert result["normalized_value"] is None


def test_text_fact_not_numeric():
    result = normalize_numeric_fact({
        **fact("Q3"),
        "numeric": False,
    })

    assert result["normalization_status"] == "not_numeric"


def test_context_periods_and_dimensions():
    contexts = extract_context_details(HTML)

    assert contexts["c1"]["period_type"] == "duration"
    assert contexts["c1"]["start_date"] == "2026-04-01"
    assert contexts["c1"]["end_date"] == "2026-06-30"
    assert contexts["c1"]["consolidated_candidate"]

    assert contexts["c2"]["period_type"] == "instant"
    assert contexts["c2"]["instant"] == "2026-06-30"
    assert not contexts["c2"]["consolidated_candidate"]

    assert contexts["c2"]["dimensions"][0]["member"] == (
        "aapl:ServicesMember"
    )


def test_normalization_preserves_original_fact():
    raw_fact = fact("125")

    result = normalize_xbrl(
        {"facts": [raw_fact], "units": {}},
        HTML,
    )

    enriched = result["facts"][0]

    assert enriched["value"] == "125"
    assert enriched["normalized_value"] == "125"
    assert enriched["resolved_context"]["period_type"] == "duration"
    assert result["normalization_counts"]["normalized"] == 1
