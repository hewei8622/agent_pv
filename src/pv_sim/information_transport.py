"""Exact recorded/replay adapters. They receive public requests, never simulator state.

Adapters do not access files or the network, execute text, or create live evidence.
The session owns budgets, deadlines, idempotence and durable event recording.
"""

from __future__ import annotations

from typing import Protocol

from pv_sim.contracts import Record
from pv_sim.interaction_contracts import InformationReply, InteractionRequest


class InformationTransport(Protocol):
    def request(self, request: InteractionRequest) -> InformationReply: ...


class RecordedExchange(Record):
    request: InteractionRequest
    reply: InformationReply


def _validated_exchange(exchange: RecordedExchange) -> RecordedExchange:
    if not isinstance(exchange, RecordedExchange):
        raise TypeError("recorded exchanges must be validated records")
    # Revalidate even model_construct/model_copy inputs at the adapter boundary.
    return RecordedExchange(
        request=InteractionRequest.from_json(exchange.request.to_json()),
        reply=InformationReply.from_json(exchange.reply.to_json()),
    )


def _validated_request(request: InteractionRequest) -> InteractionRequest:
    if not isinstance(request, InteractionRequest):
        raise TypeError("transport accepts only a public InteractionRequest")
    return InteractionRequest.from_json(request.to_json())


class RecordedTransport:
    """Return a fixture only when every field of its public request matches."""

    def __init__(self, exchanges: tuple[RecordedExchange, ...]) -> None:
        self._exchanges: dict[tuple[str, str], RecordedExchange] = {}
        for raw in exchanges:
            exchange = _validated_exchange(raw)
            key = (exchange.request.episode_id, exchange.request.request_id)
            if key in self._exchanges:
                raise ValueError("duplicate request identity in recorded collection")
            self._exchanges[key] = exchange

    def request(self, request: InteractionRequest) -> InformationReply:
        request = _validated_request(request)
        key = (request.episode_id, request.request_id)
        if key not in self._exchanges:
            raise LookupError("no recorded response for this request")
        exchange = self._exchanges[key]
        if request != exchange.request:
            raise ValueError("request conflicts with its recorded payload")
        return exchange.reply


class ReplayTransport:
    """Consume an exact ordered trace without making any external calls.

    Reply provenance is preserved, not relabelled as live or as newly collected.
    Request retries must be handled by the session cache before this adapter.
    """

    def __init__(self, exchanges: tuple[RecordedExchange, ...]) -> None:
        self._exchanges = tuple(_validated_exchange(exchange) for exchange in exchanges)
        identities = [
            (exchange.request.episode_id, exchange.request.request_id)
            for exchange in self._exchanges
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("replay trace must contain unique request identities")
        self._consumed = 0

    @property
    def consumed(self) -> int:
        return self._consumed

    @property
    def remaining(self) -> int:
        return len(self._exchanges) - self._consumed

    def request(self, request: InteractionRequest) -> InformationReply:
        request = _validated_request(request)
        if self._consumed == len(self._exchanges):
            raise LookupError("replay trace exhausted")
        exchange = self._exchanges[self._consumed]
        if request != exchange.request:
            raise ValueError("request does not match the next replay entry")
        self._consumed += 1
        return exchange.reply
