"""Versioned public information records, separate from physical action schema 1.0.

This first interface accepts recorded and simulated evidence only. Live provenance
needs an explicitly reviewed transport extension. Text is evidence, never a command.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field, model_validator

from pv_sim.contracts import Identifier, Record

INTERACTION_VERSION = "interaction/1.0"
MAX_WIRE_BYTES = 65_536
InformationChannel = Literal["human", "internet"]
InformationOutcome = Literal[
    "available", "unavailable", "timed_out", "cancelled", "invalid_response"
]
InformationProvenance = Literal["recorded", "simulated"]


def _text_bytes(value: str, maximum: int, *, required: bool) -> str:
    if required and not value.strip():
        raise ValueError("text must contain non-whitespace characters")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError(f"text exceeds {maximum} UTF-8 bytes")
    return value


QuestionText = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=2000),
    AfterValidator(lambda value: _text_bytes(value, 2000, required=True)),
]
ReplyText = Annotated[
    str,
    Field(strict=True, max_length=16000),
    AfterValidator(lambda value: _text_bytes(value, 16000, required=False)),
]
SourceTitle = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=500),
    AfterValidator(lambda value: _text_bytes(value, 500, required=True)),
]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


class InteractionRecord(Record):
    """Wire methods apply byte limits and reject ambiguous JSON before validation."""

    @classmethod
    def from_json(cls, payload: str | bytes) -> Self:
        if not isinstance(payload, (str, bytes)):
            raise TypeError("interaction payload must be a JSON string or UTF-8 bytes")
        wire = payload.encode("utf-8") if isinstance(payload, str) else payload
        if len(wire) > MAX_WIRE_BYTES:
            raise ValueError("interaction payload exceeds 65536 UTF-8 bytes")
        decoded = wire.decode("utf-8")
        try:
            obj = json.loads(
                decoded, object_pairs_hook=_unique_object, parse_constant=_reject_constant
            )
        except RecursionError as exc:
            raise ValueError("interaction JSON nesting exceeds parser capacity") from exc
        if not isinstance(obj, dict):
            raise ValueError("interaction payload must be a JSON object")
        return cls.model_validate_json(decoded)

    def to_json(self) -> str:
        result = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if len(result.encode("utf-8")) > MAX_WIRE_BYTES:
            raise ValueError("interaction payload exceeds 65536 UTF-8 bytes")
        return result

    @model_validator(mode="after")
    def wire_size(self) -> Self:
        self.to_json()
        return self


class InteractionLimits(Record):
    """Frozen Step 2 protocol, shared by scripted drivers and later comparisons."""

    schema_version: Literal["interaction/1.0"] = INTERACTION_VERSION
    max_requests: Annotated[int, Field(strict=True, ge=3, le=3)] = 3
    human_deadline_s: Annotated[float, Field(strict=True, ge=300, le=300)] = 300.0
    internet_deadline_s: Annotated[float, Field(strict=True, ge=30, le=30)] = 30.0
    max_wire_bytes: Annotated[int, Field(strict=True, ge=65536, le=65536)] = MAX_WIRE_BYTES
    max_question_bytes: Annotated[int, Field(strict=True, ge=2000, le=2000)] = 2000
    max_reply_bytes: Annotated[int, Field(strict=True, ge=16000, le=16000)] = 16000

    def deadline_s(self, channel: InformationChannel) -> float:
        if channel == "human":
            return self.human_deadline_s
        if channel == "internet":
            return self.internet_deadline_s
        raise ValueError("unknown information channel")


class InteractionRequest(InteractionRecord):
    schema_version: Literal["interaction/1.0"] = INTERACTION_VERSION
    episode_id: Identifier
    request_id: Identifier
    channel: InformationChannel
    question: QuestionText
    information_gap: QuestionText
    intended_decision: QuestionText
    parent_request_id: Identifier | None = None

    @model_validator(mode="after")
    def not_self_parent(self) -> Self:
        if self.parent_request_id == self.request_id:
            raise ValueError("a follow-up cannot name itself as parent")
        return self


class InformationSource(Record):
    title: SourceTitle
    url: Annotated[str, Field(strict=True, min_length=1, max_length=2048)] | None = None
    source_date: Annotated[str, Field(strict=True, pattern=r"^\d{4}-\d{2}-\d{2}$")] | None = None

    @model_validator(mode="after")
    def valid_source(self) -> Self:
        if self.url is not None:
            _text_bytes(self.url, 2048, required=True)
            if any(character.isspace() or ord(character) < 32 for character in self.url):
                raise ValueError("source URL must not contain whitespace or control characters")
            parsed = urlsplit(self.url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError("source URL must be absolute HTTP or HTTPS")
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("source URL must not contain credentials")
            # Access also checks malformed/out-of-range ports.
            _ = parsed.port
        if self.source_date is not None:
            date.fromisoformat(self.source_date)
        return self


class InformationReply(InteractionRecord):
    schema_version: Literal["interaction/1.0"] = INTERACTION_VERSION
    outcome: InformationOutcome
    text: ReplyText = ""
    provenance: InformationProvenance
    sources: Annotated[tuple[InformationSource, ...], Field(max_length=8)] = ()

    @model_validator(mode="after")
    def attributed_answer(self) -> Self:
        if self.outcome == "available":
            if not self.text.strip():
                raise ValueError("an available reply must contain nonblank text")
            if not self.sources:
                raise ValueError("an available reply must identify at least one source")
        return self
