
"""Extract inline XBRL facts from SEC filing HTML.

This module preserves the raw financial fact and its references.
It does not attempt to interpret accounting concepts or resolve
XBRL contexts into financial periods.
"""

from bs4 import BeautifulSoup, Tag


def _text(tag: Tag) -> str:
    return " ".join(tag.stripped_strings)


def _attribute(tag: Tag, name: str) -> str | None:
    value = tag.get(name)
    return str(value) if value is not None else None


def extract_inline_xbrl(raw: bytes) -> dict:
    """Extract inline XBRL facts and context/unit definitions."""

    soup = BeautifulSoup(raw, "html.parser")

    facts = []
    contexts = {}
    units = {}

    for tag in soup.find_all(True):
        name = tag.name.lower()

        if name in {"ix:nonfraction", "ix:nonnumeric"}:
            facts.append({
                "name": _attribute(tag, "name"),
                "context_ref": _attribute(tag, "contextref"),
                "unit_ref": _attribute(tag, "unitref"),
                "decimals": _attribute(tag, "decimals"),
                "scale": _attribute(tag, "scale"),
                "sign": _attribute(tag, "sign"),
                "format": _attribute(tag, "format"),
                "id": _attribute(tag, "id"),
                "value": _text(tag),
                "numeric": name == "ix:nonfraction",
            })

        elif name == "xbrli:context":
            context_id = _attribute(tag, "id")

            if context_id:
                identifier = tag.find(
                    "xbrli:identifier"
                )
                start = tag.find("xbrli:startdate")
                end = tag.find("xbrli:enddate")
                instant = tag.find("xbrli:instant")

                contexts[context_id] = {
                    "entity_identifier": (
                        _text(identifier)
                        if identifier else None
                    ),
                    "start_date": (
                        _text(start) if start else None
                    ),
                    "end_date": (
                        _text(end) if end else None
                    ),
                    "instant": (
                        _text(instant)
                        if instant else None
                    ),
                }

        elif name == "xbrli:unit":
            unit_id = _attribute(tag, "id")

            if unit_id:
                measures = [
                    _text(measure)
                    for measure in tag.find_all(
                        "xbrli:measure"
                    )
                ]

                units[unit_id] = {
                    "measures": measures,
                }

    return {
        "fact_count": len(facts),
        "context_count": len(contexts),
        "unit_count": len(units),
        "facts": facts,
        "contexts": contexts,
        "units": units,
    }
