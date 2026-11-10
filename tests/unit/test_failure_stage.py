"""The public error says where the plan stopped.

An acceptance run hit `wait_for failed: timeout` and could only locate the stage by
reading the local audit log and matching it against the plan source. Three different
waits in one Web of Science search — the query editor, the result list, and the capture
stream — produced the identical public message.

`stage` names the kind of thing that was being waited for. It never carries the selector
itself: which elements a channel uses is implementation detail, and on some paths the
selector is derived from page content.
"""

from __future__ import annotations

import pytest

from scholar_search.core.contracts import Action, ActionOutcome
from scholar_search.core.errors import ActionError
from scholar_search.core.service import ScholarService
from scholar_search.server import _payload


def _outcome(verb: str, params: dict[str, object], error: str = "timeout") -> ActionOutcome:
    return ActionOutcome(action=Action(verb, params), ok=False, error=error)


@pytest.mark.parametrize(
    ("verb", "params", "expected"),
    [
        # The three that used to be indistinguishable.
        ("wait_for", {"selector": "textarea#advancedSearchInputArea"}, "wait.query-input"),
        ("wait_for", {"selector": "button[data-ta='next-page-button']"}, "wait.result-list"),
        ("wait_for", {"selector": "#wensu-wos-capture[data-ready='1']"}, "wait.capture"),
        # Other stages a caller might need to tell apart.
        ("goto", {"reload": True}, "navigate.reload"),
        ("goto", {"url": "https://example.org"}, "navigate.open"),
        ("type", {"selector": "textarea"}, "input.fill"),
        ("read_text", {"selector": "#wensu-wos-capture"}, "action.read_text"),
    ],
)
def test_each_stage_has_its_own_label(verb: str, params: dict[str, object], expected: str) -> None:
    assert ScholarService._stage_of(_outcome(verb, params), index=0) == expected


def test_a_capture_wait_is_not_confused_with_a_result_list() -> None:
    """The specific confusion the acceptance run had to resolve by hand."""

    capture = ScholarService._stage_of(
        _outcome("wait_for", {"selector": "#wensu-wos-capture[data-ready='1']"}), index=0
    )
    result_list = ScholarService._stage_of(
        _outcome("wait_for", {"selector": "button[data-ta='next-page-button']"}), index=0
    )
    assert capture != result_list


def test_the_message_names_the_step_and_the_stage() -> None:
    failed = _outcome("wait_for", {"selector": "#wensu-wos-capture[data-ready='1']"})
    outcomes = [ActionOutcome(action=Action("goto", {}), ok=True)] * 7 + [failed]
    message = ScholarService._failure_message(failed, 7, outcomes)
    assert "wait.capture" in message
    assert "step 8/8" in message
    assert failed.error in message


def test_the_selector_never_reaches_the_payload() -> None:
    """A selector can be derived from page content; the stage must not leak it."""

    error = ActionError(
        "wait_for failed: timeout (step 9/12, stage wait.capture)",
        verb="wait_for",
        code="timeout",
        stage="wait.capture",
    )
    payload = _payload(error)
    assert payload["stage"] == "wait.capture"
    assert "#wensu" not in str(payload)
    assert "textarea" not in str(payload)


def test_an_error_without_a_stage_omits_the_field() -> None:
    error = ActionError("boom", verb="goto", code="action.failed")
    assert "stage" not in _payload(error)
