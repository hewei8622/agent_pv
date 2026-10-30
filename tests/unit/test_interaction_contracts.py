import json

import pytest
from pydantic import ValidationError

from pv_sim.interaction_contracts import (
    InformationReply,
    InformationSource,
    InteractionLimits,
    InteractionRequest,
)


def request_payload(**updates):
    return dict(
        schema_version="interaction/1.0",
        episode_id="public-episode",
        request_id="question-1",
        channel="human",
        question="What changed near the panel?",
        information_gap="Whether recent work obstructed its light.",
        intended_decision="Choose a camera observation or voltage experiment.",
        parent_request_id=None,
    ) | updates


def reply_payload(**updates):
    return dict(
        schema_version="interaction/1.0",
        outcome="available",
        text="Work was reported nearby; I cannot establish its effect on this panel.",
        provenance="recorded",
        sources=[
            dict(title="Recorded participant observation", url=None, source_date="2026-10-19")
        ],
    ) | updates


def test_request_and_reply_wire_roundtrip_and_deep_freeze():
    request = InteractionRequest.from_json(json.dumps(request_payload()).encode())
    reply = InformationReply.from_json(json.dumps(reply_payload()))
    assert InteractionRequest.from_json(request.to_json()) == request
    assert InformationReply.from_json(reply.to_json()) == reply
    with pytest.raises(ValidationError):
        request.question = "Changed"
    with pytest.raises(ValidationError):
        reply.sources[0].title = "Changed"
    with pytest.raises(TypeError):
        reply.sources[0] = InformationSource(title="Changed")


@pytest.mark.parametrize(
    "updates",
    [
        {"schema_version": "1.0"},
        {"episode_id": "a/b"},
        {"request_id": 1},
        {"channel": "shell"},
        {"question": " "},
        {"question": 5},
        {"question": "é" * 1001},
        {"information_gap": "x" * 2001},
        {"intended_decision": "x" * 2001},
        {"parent_request_id": "question-1"},
        {"parent_request_id": False},
        {"private_config": {"seed": 7}},
        {"action": {"kind": "set_voltage", "voltage_v": 10}},
    ],
)
def test_request_rejects_malformed_or_private_payload(updates):
    with pytest.raises(ValidationError):
        InteractionRequest.from_json(json.dumps(request_payload(**updates)))


def test_questions_and_followups_are_not_restricted_to_fault_taxonomy():
    request = InteractionRequest.from_json(
        json.dumps(
            request_payload(
                request_id="question-2",
                parent_request_id="question-1",
                question="Did you mean the west roof, or the panel beside the tree? 🌞",
                intended_decision="Possibly leave the operating point unchanged.",
            )
        )
    )
    assert request.parent_request_id == "question-1"
    assert request.question.endswith("🌞")


@pytest.mark.parametrize(
    "updates",
    [
        {"provenance": "live"},
        {"provenance": None},
        {"outcome": "true"},
        {"text": " "},
        {"text": "🌞" * 4001},
        {"text": 5},
        {"sources": []},
        {"sources": [{"title": "Fixture", "private_path": "/private/example"}]},
        {"sources": [{"title": "Fixture"}] * 9},
        {"truth": "the cause"},
    ],
)
def test_reply_requires_bounded_attributed_evidence(updates):
    with pytest.raises(ValidationError):
        InformationReply.from_json(json.dumps(reply_payload(**updates)))


@pytest.mark.parametrize("outcome", ["unavailable", "timed_out", "cancelled", "invalid_response"])
def test_explicit_no_answer_outcomes_can_be_empty(outcome):
    reply = InformationReply(outcome=outcome, provenance="simulated")
    assert reply.text == ""
    assert reply.sources == ()
    assert InformationReply.from_json(reply.to_json()) == reply


@pytest.mark.parametrize(
    "updates",
    [
        {"title": " "},
        {"title": "é" * 251},
        {"url": "file:///private/example"},
        {"url": "javascript:alert(1)"},
        {"url": "//example.org/manual"},
        {"url": "https:///manual"},
        {"url": "https://name:secret@example.org/manual"},
        {"url": "https://example.org/a b"},
        {"url": "https://example.org/\nmanual"},
        {"url": "https://example.org:90000/manual"},
        {"url": "https://example.org/" + "é" * 1024},
        {"source_date": "2026-02-30"},
        {"source_date": "2026-1-01"},
        {"source_date": "2026-10-19T00:00:00Z"},
        {"source_date": 20261019},
    ],
)
def test_sources_reject_invalid_dates_urls_and_text(updates):
    with pytest.raises(ValidationError):
        InformationSource.model_validate({"title": "Technical note"} | updates)


def test_source_date_optional_and_http_url_retained_without_retrieval():
    source = InformationSource(title="Manual", url="https://example.org/manual?v=1#voltage")
    assert source.source_date is None
    assert source.url == "https://example.org/manual?v=1#voltage"


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff",
        "[]",
        "null",
        '{"request_id":"one","request_id":"two"}',
        '{"sources":[{"title":"one","title":"two"}]}',
        '{"extra":NaN}',
        '{"extra":Infinity}',
        '{"extra":-Infinity}',
        "{" + " " * 65536 + "}",
        "{invalid}",
    ],
)
def test_wire_rejects_ambiguous_invalid_and_oversized_json(payload):
    with pytest.raises(ValueError):
        InteractionRequest.from_json(payload)


def test_wire_size_applies_to_json_escapes_and_not_just_field_size():
    # 16000 control characters fit the text byte limit but escape to >64 KiB.
    with pytest.raises(ValidationError):
        InformationReply(
            outcome="available",
            text="x" + "\x00" * 15999,
            provenance="simulated",
            sources=(InformationSource(title="Synthetic boundary fixture"),),
        )


def test_utf8_limits_accept_exact_boundary():
    request = InteractionRequest(**request_payload(question="é" * 1000))
    reply = InformationReply(
        outcome="available",
        text="🌞" * 4000,
        provenance="simulated",
        sources=(InformationSource(title="Synthetic boundary fixture"),),
    )
    assert len(request.question.encode()) == 2000
    assert len(reply.text.encode()) == 16000


def test_frozen_protocol_caps_and_channel_deadlines():
    limits = InteractionLimits()
    assert limits.max_requests == 3
    assert limits.deadline_s("human") == 300
    assert limits.deadline_s("internet") == 30
    assert limits.max_wire_bytes == 65536
    assert limits.max_question_bytes == 2000
    assert limits.max_reply_bytes == 16000
    with pytest.raises(ValidationError):
        InteractionLimits(max_requests=4)
    with pytest.raises(ValidationError):
        InteractionLimits(max_requests=3.0)
    with pytest.raises(ValidationError):
        InteractionLimits(human_deadline_s="300")
    with pytest.raises(ValueError):
        limits.deadline_s("shell")
