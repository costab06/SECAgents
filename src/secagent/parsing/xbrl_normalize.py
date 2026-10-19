
"""Normalize extracted inline XBRL facts and resolve their contexts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any

from bs4 import BeautifulSoup, Tag


SUPPORTED_NUMERIC_FORMATS = {
    None,
    "",
    "ixt:num-dot-decimal",
    "ixt:numdotdecimal",
    "ixt:zerodash",
    "ixt:zero-dash",
}

NUMERIC_PATTERN = re.compile(
    r"^(?:\d+(?:\.\d*)?|\.\d+)$"
)


def _text(tag: Tag | None) -> str | None:
    if tag is None:
        return None
    return " ".join(tag.stripped_strings)


def _find(tag: Tag, local_name: str) -> Tag | None:
    """Find a descendant by namespace-independent local name."""
    for child in tag.find_all(True):
        if child.name.split(":")[-1].lower() == local_name.lower():
            return child
    return None


def _children(tag: Tag, local_name: str) -> list[Tag]:
    return [
        child
        for child in tag.find_all(True)
        if child.name.split(":")[-1].lower() == local_name.lower()
    ]


def extract_context_details(raw: bytes) -> dict[str, dict]:
    """Extract periods, entity IDs and dimensional qualifiers."""

    soup = BeautifulSoup(raw, "html.parser")
    contexts = {}

    for tag in soup.find_all(True):
        if tag.name.split(":")[-1].lower() != "context":
            continue

        context_id = tag.get("id")
        if not context_id:
            continue

        instant = _text(_find(tag, "instant"))
        start = _text(_find(tag, "startDate"))
        end = _text(_find(tag, "endDate"))
        identifier = _text(_find(tag, "identifier"))

        dimensions = []

        for member in _children(tag, "explicitMember"):
            dimensions.append({
                "type": "explicit",
                "dimension": member.get("dimension"),
                "member": _text(member),
            })

        for member in _children(tag, "typedMember"):
            dimensions.append({
                "type": "typed",
                "dimension": member.get("dimension"),
                "value": member.decode_contents().strip(),
            })

        contexts[str(context_id)] = {
            "entity_identifier": identifier,
            "period_type": (
                "instant" if instant
                else "duration" if start and end
                else "unknown"
            ),
            "instant": instant,
            "start_date": start,
            "end_date": end,
            "dimensions": dimensions,
            "consolidated_candidate": not dimensions,
        }

    return contexts


def normalize_numeric_fact(fact: dict) -> dict:
    """Normalize an XBRL numeric fact without guessing its format."""

    raw_value = fact.get("value")
    raw_format = fact.get("format")
    numeric_format = (
        str(raw_format).lower()
        if raw_format is not None
        else None
    )

    result = {
        "normalized_value": None,
        "normalization_status": "unresolved",
        "normalization_error": None,
    }

    if not fact.get("numeric", False):
        result["normalization_status"] = "not_numeric"
        return result

    if numeric_format not in SUPPORTED_NUMERIC_FORMATS:
        result["normalization_error"] = (
            f"Unsupported numeric format: {raw_format}"
        )
        return result

    if raw_value is None:
        result["normalization_error"] = "Missing value"
        return result

    text = str(raw_value).strip()

    if numeric_format in {
        "ixt:zerodash",
        "ixt:zero-dash",
    } and text in {"-", "–", "—"}:
        text = "0"

    # Parentheses conventionally represent negative values.
    # Avoid combining this with an explicit sign attribute.
    parenthesized = (
        text.startswith("(")
        and text.endswith(")")
    )

    if parenthesized:
        text = text[1:-1].strip()

    text = text.replace(",", "").replace(" ", "")

    if not NUMERIC_PATTERN.fullmatch(text):
        result["normalization_error"] = (
            f"Unsupported numeric representation: {raw_value}"
        )
        return result

    sign = fact.get("sign")

    if sign not in {None, "", "-", "+"}:
        result["normalization_error"] = (
            f"Unsupported sign: {sign}"
        )
        return result

    if parenthesized and sign in {"-", "+"}:
        result["normalization_error"] = (
            "Conflicting parentheses and sign attribute"
        )
        return result

    try:
        scale = int(fact.get("scale") or 0)

        if abs(scale) > 100:
            raise ValueError("Scale outside supported range")

        value = Decimal(text) * (Decimal(10) ** scale)

        if parenthesized or sign == "-":
            value = -value

        result["normalized_value"] = format(value, "f")
        if "." in result["normalized_value"]:
            result["normalized_value"] = (
                result["normalized_value"]
                .rstrip("0")
                .rstrip(".")
            )



        result["normalization_status"] = "normalized"

    except (InvalidOperation, ValueError, OverflowError) as exc:
        result["normalization_error"] = str(exc)

    return result


def normalize_xbrl(
    xbrl: dict[str, Any],
    raw_html: bytes,
) -> dict[str, Any]:
    """Enrich extracted XBRL facts with values and resolved contexts."""

    contexts = extract_context_details(raw_html)
    normalized_facts = []
    counts = {
        "normalized": 0,
        "unresolved": 0,
        "not_numeric": 0,
    }

    for fact in xbrl.get("facts", []):
        normalized = normalize_numeric_fact(fact)

        context_ref = fact.get("context_ref")
        context = contexts.get(context_ref)

        enriched = {
            **fact,
            **normalized,
            "resolved_context": context,
            "context_status": (
                "resolved" if context is not None
                else "missing"
            ),
        }

        normalized_facts.append(enriched)
        counts[normalized["normalization_status"]] += 1

    return {
        "schema_version": "1.0",
        "fact_count": len(normalized_facts),
        "contexts": contexts,
        "units": xbrl.get("units", {}),
        "normalization_counts": counts,
        "facts": normalized_facts,
    }
