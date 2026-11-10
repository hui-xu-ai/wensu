"""A `detail` response must be usable as an `export` input.

The acceptance flow is: find a record, read its details, hand the result to the export
tool. That used to fail on wensu's own bookkeeping fields:

    unknown record fields: ['quota_charged', 'quota_remaining']

`detail` flattens the response envelope onto the record, so the obvious thing a caller
does — pass it straight through — was the thing that did not work. The caller had to
know which keys were "real", which is knowledge an interface should not require.

Envelope keys are dropped; a genuine typo is still rejected. Both halves are asserted
here, because the fix must not turn a strict schema into a permissive one.
"""

from __future__ import annotations

import pytest

from scholar_search.core.contracts import Record
from scholar_search.core.export import ENVELOPE_FIELDS, record_from_payload, to_endnote, to_ris
from scholar_search.server import _detail_payload


def _detail_response(**kwargs: object) -> dict[str, object]:
    record = Record(
        title="Hofmeister effect-mediated bilayer hydrogel actuators",
        channel="webofscience",
        authors=["Zhang, Y"],
        source="SENSORS AND ACTUATORS B-CHEMICAL",
        year=2026,
        doi="10.1016/j.snb.2026.141132",
        impact_factor=8.3,
        impact_factor_year=2025,
    )
    return _detail_payload(
        record.to_dict(),
        include_abstract=True,
        fields=None,
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_detail_response_goes_straight_into_export() -> None:
    response = _detail_response(quota_charged=0, quota_remaining=87)
    assert ENVELOPE_FIELDS & set(response), "the payload should carry envelope keys"

    record = record_from_payload(response)
    assert record.doi == "10.1016/j.snb.2026.141132"
    assert "10.1016/j.snb.2026.141132" in to_ris([record])
    assert "10.1016/j.snb.2026.141132" in to_endnote([record])


def test_the_envelope_fields_never_reach_the_record() -> None:
    """They are bookkeeping, not bibliographic data."""

    record = record_from_payload(_detail_response(quota_charged=4, quota_remaining=83))
    assert not hasattr(record, "quota_charged")
    assert "quota_charged" not in record.to_dict()


@pytest.mark.parametrize("bogus", ["titel", "athors", "impact_facter"])
def test_a_genuine_typo_is_still_rejected(bogus: str) -> None:
    with pytest.raises(ValueError, match="unknown record fields"):
        record_from_payload({**_detail_response(), bogus: "x"})


def test_a_record_without_envelope_fields_is_unchanged() -> None:
    """The tolerant path must not alter a payload that never had them."""

    plain = _detail_response()
    assert not ENVELOPE_FIELDS & set(plain)
    assert record_from_payload(plain).title == record_from_payload(plain).title.strip()
