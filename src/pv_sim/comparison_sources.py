"""Frozen, queryable service-context fixture; no network or hidden physics access.

This endpoint returns its current service record for any newly worded question.
It is deliberately a bounded record lookup, not semantic search or live human
reasoning. The unmodified JSON reply retains both original prose and typed data.
Only a matching declared source and current typed directive grant authority.
The source title is a fixture identity check, not cryptographic authentication.
Contradictory prose versus typed fields is not interpreted semantically.
"""

from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from pv_sim.contracts import Number, Record
from pv_sim.interaction_contracts import InformationReply, InformationSource, InteractionRequest

SOURCE_ID = "service_context_v1"
SOURCE_TITLE = "Controlled current service instructions v1"
Instruction = Literal["hold", "survey", "unknown"]


class PublicBrief(Record):
    """Identical explicit operating priors for both policies, never a case label."""

    nominal_voltage_v: Number = 1.8
    survey_candidates_v: tuple[Number, ...] = (0.8, 1.8, 3.0)
    survey_dwell_s: Number = 0.5
    source_drop_threshold_w_m2: Number = 100.0
    voltage_tolerance_v: Number = 0.02
    initial_observation_s: Number = 2.4
    known_instruction: Literal["hold"] | None = None
    authority_source_id: Literal["service_context_v1"] = SOURCE_ID
    instruction_valid_until_s: Number = 16.0
    horizon_s: Number = 16.0
    finish_tail_s: Number = 2.0
    decision_overhead_s: Number = 0.2
    numeric_capture_period_s: Number = 0.1
    clarification_limit: Annotated[int, Field(ge=0, le=1)] = 1

    @model_validator(mode="after")
    def valid_protocol(self):
        if not 0.2 <= self.nominal_voltage_v <= 4.0:
            raise ValueError("nominal voltage outside public protocol")
        if not 1 <= len(self.survey_candidates_v) <= 3 or len(set(self.survey_candidates_v)) != len(
            self.survey_candidates_v
        ):
            raise ValueError("survey candidates must be distinct and bounded")
        if any(not 0.2 <= v <= 4.0 for v in self.survey_candidates_v):
            raise ValueError("survey target outside public protocol")
        if not 0.2 <= self.survey_dwell_s <= 2.0 or not 0.1 <= self.initial_observation_s <= 5:
            raise ValueError("invalid dwell or initial observation duration")
        if (
            min(
                self.source_drop_threshold_w_m2,
                self.voltage_tolerance_v,
                self.horizon_s,
                self.numeric_capture_period_s,
            )
            <= 0
        ):
            raise ValueError("thresholds and periods must be positive")
        if min(self.finish_tail_s, self.decision_overhead_s, self.instruction_valid_until_s) < 0:
            raise ValueError("negative public timing")
        if self.horizon_s <= self.finish_tail_s + self.decision_overhead_s:
            raise ValueError("no investigation time remains")
        return self


class ServiceDirective(Record):
    source_id: Literal["service_context_v1"] = SOURCE_ID
    instruction: Instruction
    valid_from_s: Annotated[Number, Field(ge=0)] = 0.0
    valid_until_s: Annotated[Number, Field(gt=0)] = 16.0
    original_text: Annotated[str, Field(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def validity(self):
        if self.valid_until_s <= self.valid_from_s:
            raise ValueError("empty service validity window")
        return self


class ServiceEnvelope(Record):
    schema_version: Literal["controlled-service/1.0"] = "controlled-service/1.0"
    source_id: Literal["service_context_v1"] = SOURCE_ID
    corpus_version: Literal["comparison-corpus/1.0"] = "comparison-corpus/1.0"
    records: Annotated[tuple[ServiceDirective, ...], Field(min_length=1, max_length=2)]


class ServiceCorpus(Record):
    schema_version: Literal["comparison-corpus/1.0"] = "comparison-corpus/1.0"
    instruction: Instruction = "hold"
    behavior: Literal["authoritative", "irrelevant", "unavailable", "conflicting"] = "authoritative"
    valid_from_s: Annotated[Number, Field(ge=0)] = 0.0
    valid_until_s: Annotated[Number, Field(gt=0)] = 16.0

    @model_validator(mode="after")
    def validity(self):
        if self.valid_until_s <= self.valid_from_s:
            raise ValueError("empty corpus validity window")
        return self


class ControlledServiceSource:
    """Deterministic service-record lookup accepting arbitrary valid questions."""

    def __init__(self, corpus: ServiceCorpus):
        self.corpus = ServiceCorpus.model_validate_json(corpus.model_dump_json())

    def request(self, request: InteractionRequest) -> InformationReply:
        InteractionRequest.from_json(request.to_json())
        if self.corpus.behavior == "unavailable":
            return InformationReply(
                outcome="unavailable",
                provenance="simulated",
                text="The authored service record is unavailable.",
            )
        if self.corpus.behavior == "irrelevant":
            return InformationReply(
                outcome="available",
                provenance="simulated",
                text="Generic PV guidance: a voltage survey may help measure a power curve. "
                "This document does not grant operational permission.",
                sources=(InformationSource(title="Controlled generic PV guidance v1"),),
            )
        modes = (
            ("hold", "survey")
            if self.corpus.behavior == "conflicting"
            else (self.corpus.instruction,)
        )
        prose = {
            "hold": "Hold the nominal operating point. A voltage survey is not permitted.",
            "survey": "Current service permission allows the declared bounded voltage survey.",
            "unknown": "The current service instruction is not established; permission is unknown.",
        }
        envelope = ServiceEnvelope(
            records=tuple(
                ServiceDirective(
                    instruction=mode,
                    valid_from_s=self.corpus.valid_from_s,
                    valid_until_s=self.corpus.valid_until_s,
                    original_text=prose[mode],
                )
                for mode in modes
            )
        )
        return InformationReply(
            outcome="available",
            provenance="simulated",
            text=envelope.model_dump_json(),
            sources=(InformationSource(title=SOURCE_TITLE),),
        )


def read_service_reply(reply: InformationReply, now_s: float) -> tuple[Instruction, str]:
    """Fail closed on malformed, stale, conflicting or unverified service evidence."""
    if reply.outcome != "available":
        return "unknown", reply.outcome
    if reply.sources != (InformationSource(title=SOURCE_TITLE),):
        return "unknown", "unverified_or_irrelevant_source"
    try:
        # Reject duplicate keys instead of accepting an overwritten permission.
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate service field")
                value[key] = item
            return value

        obj = json.loads(reply.text, object_pairs_hook=unique)
        envelope = ServiceEnvelope.model_validate_json(json.dumps(obj, allow_nan=False))
    except (ValueError, TypeError, RecursionError):
        return "unknown", "invalid_service_envelope"
    current = [r for r in envelope.records if r.valid_from_s <= now_s <= r.valid_until_s]
    if len(current) != len(envelope.records):
        return "unknown", "noncurrent_service_record"
    values = {r.instruction for r in current}
    if len(values) != 1:
        return "unknown", "conflicting_service_records"
    value = values.pop()
    return (
        value,
        "current_authorized_service_record" if value != "unknown" else "unknown_instruction",
    )
