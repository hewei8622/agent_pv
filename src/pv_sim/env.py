"""Trusted local orchestrator: real dynamics, immutable timed sensors and actions.

Only PublicTask/Observation cross into PolicyRunner. Core tests may explicitly
disable RGB; production CLI episodes always require the genuine backend renderer.
This synchronous interface accepts one blocking action at a time. It does not
provide a hostile-code sandbox or a concurrent command transport.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict
from typing import Callable

from pydantic import ValidationError

from pv_sim.actions import gate, required_tokens
from pv_sim.backends.mujoco_backend import MujocoBackend
from pv_sim.config import Config
from pv_sim.contracts import (
    ACTION_ADAPTER,
    Action,
    ActionFeedback,
    CaptureRGB,
    EncoderSample,
    Finish,
    MeasuredConfirmation,
    MoveCamera,
    Observation,
    ProbeVoltage,
    RGBSample,
    SafeStop,
    ScalarSample,
    SetVoltage,
    Wait,
    validate_observation_context,
)
from pv_sim.costs import Ledger
from pv_sim.optics import Optics
from pv_sim.pv import NumericalError, PVModel
from pv_sim.scene import Scene
from pv_sim.scheduler import Scheduler, ticks
from pv_sim.sensors import SensorModel, build_public_task
from pv_sim.thermal import EnergyBalanceError, ThermalModel


class RenderUnavailable(RuntimeError):
    """A required real camera failed. No placeholder or numeric-only fallback."""


class SafetyStopError(RuntimeError):
    """Bounded cleanup failed to establish a measured stop; trial is incomplete."""


class _TravelBudgetStop(Exception):
    """Unwind the current action before performing its latched stop response."""


class PVEnv:
    def __init__(self, config: Config, *, enable_rendering: bool = True, recorder=None):
        self.config = config
        self.enable_rendering = enable_rendering
        self.recorder = recorder
        self.scene = Scene.from_config(config)
        self.optics = Optics(self.scene, config)
        self.backend = MujocoBackend(config, self.scene)
        self.pv = PVModel(config)
        self.thermal = ThermalModel(config)
        self._active = False
        self._has_reset = False
        self._information_token: str | None = None

    @property
    def information_wait_pending(self) -> bool:
        """Whether the trusted information coordinator has paused this episode."""
        return self._information_token is not None

    def _require_information_running(self) -> None:
        if self.information_wait_pending:
            raise RuntimeError("information wait is pending")

    @staticmethod
    def _validate_information_token(token: str) -> None:
        if type(token) is not str or not 1 <= len(token) <= 128 or any(
            not 33 <= ord(character) <= 126 for character in token
        ):
            raise ValueError("information token must contain 1 to 128 visible ASCII characters")

    def _information_boundary_ready(self) -> bool:
        """No command is pending and actual motion meets existing stop tolerances.

        Sensor packets awaiting delivery are allowed: their capture timestamps
        and delivery queue are frozen with the world during the information wait.
        A newly issued trajectory is rejected even before its first moving tick.
        """
        state = self.backend.snapshot()
        return (
            self._pending_load is None
            and self._pending_rgb is None
            and abs(self.applied_voltage_v - self._load_target) <= 1e-10
            and all(abs(value) < 1e-10 for value in state.setpoint_rate)
            and all(
                abs(a - b) <= 1e-10
                for a, b in zip(state.setpoint, self.backend.targets, strict=True)
            )
            and all(
                abs(a - b) <= limit
                for a, b, limit in zip(state.q, state.setpoint, (0.001, 0.01, 0.01), strict=True)
            )
            and all(
                abs(value) <= limit
                for value, limit in zip(state.qdot, (0.005, 0.02, 0.02), strict=True)
            )
        )

    def begin_information_wait(self, token: str) -> Observation:
        """Charge one new external decision, then pause at a physical boundary.

        This opt-in bridge belongs to the trusted interaction coordinator, not
        the physical action schema. It performs no retrieval. The coordinator
        owns request validation, external budgets, wall deadlines and retry
        caching. Calling this method again while pending is never a retry.

        The fixed decision overhead advances physics normally. An intervening
        protection returns its terminal observation without installing a pause;
        failure to confirm a measured safety stop remains a SafetyStopError.
        """
        self._validate_information_token(token)
        if not self._has_reset:
            raise RuntimeError("reset must precede information requests")
        self._require_information_running()
        if self._budget_stop_failed or self._stop_failed:
            raise SafetyStopError("measured stop remains unconfirmed; reset is required")
        if self._active:
            raise RuntimeError("synchronous environment cannot accept concurrent actions")
        if self.terminal_reason:
            raise RuntimeError("terminal episode cannot accept information requests")
        if not self._information_boundary_ready():
            raise RuntimeError("information request requires a settled decision boundary")
        # Reserve the next Finish decision and its overhead as well as the
        # unchanged verification tail, so an accepted request cannot consume
        # the resources needed to verify a final decision.
        overhead = self._ticks(self.config.simulation.decision_overhead_s)
        tail = self._ticks(self.config.simulation.verification_tail_s)
        if self.ledger.decisions + 2 > self.config.budgets.decisions:
            raise RuntimeError("information request exceeds decision budget")
        if self.tick + 2 * overhead + tail > self._horizon:
            raise RuntimeError("information request exceeds time budget")
        self._active = True
        self._intervention = {"kind": "information_request"}
        self.ledger.decisions += 1
        try:
            try:
                self._advance_to(self.tick + overhead)
            except _TravelBudgetStop:
                self._finish_budget_stop()
            observation = self._observation()
            if not observation.terminal:
                self._information_token = token
            return observation
        finally:
            self._active = False

    def end_information_wait(self, token: str) -> None:
        """Resume the same clock; no samples, energy or decisions are added."""
        self._validate_information_token(token)
        if self._information_token is None:
            raise RuntimeError("no information wait is pending")
        if token != self._information_token:
            raise ValueError("information token does not match the pending request")
        self._information_token = None

    @property
    def tick(self) -> int:
        return self.clock.tick

    @property
    def time_s(self) -> float:
        return self.clock.time_s

    def _ticks(self, duration: float, rounding: str = "exact") -> int:
        return ticks(duration, self.config.simulation.dt_s, rounding=rounding)

    def reset(self, seed: int = 20261016, episode_id: str | None = None):
        self._require_information_running()
        if self._active:
            raise RuntimeError("synchronous environment cannot reset during an action")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        if self._has_reset and self.recorder:
            raise ValueError("a recorder belongs to exactly one episode")
        # A repeated reset restarts the private exogenous schedule as well as
        # dynamics. The initial immutable scene must not retain a later source.
        self.scene = Scene.from_config(self.config)
        self.optics = Optics(self.scene, self.config)
        self.backend.reset(self.scene)
        self._source_steps = {
            self._ticks(step.time_s): step for step in self.config.source_schedule or ()
        }
        self.clock = Scheduler(self.config.simulation.dt_s)
        self.ledger = Ledger()
        self.seed = seed
        self.sensors = SensorModel(self.config, seed)
        self.task = build_public_task(
            self.config, episode_id or uuid.uuid4().hex, enable_rendering=self.enable_rendering
        )
        self.temperature_c = self.config.private_world.initial_temperature_c
        self.requested_voltage_v = self.config.pv.initial_voltage_v
        self.applied_voltage_v = self.requested_voltage_v
        self._load_target = self.requested_voltage_v
        self._pending_load = None
        self._load_command_count = 0
        self._move_command_count = 0
        self._current_action_id = None
        self._failure_reason = "tracking_timeout"
        self.disconnected = False
        self.terminal_reason = None
        self._horizon = self._ticks(self.config.simulation.horizon_s)
        self._sequence = 0
        self._highest_id = 0
        self._cache = {}
        self._pending_rgb = None
        self._last_rgb_start = -self._ticks(1 / self.config.sensors.rgb_max_hz)
        self._latest_scalars = {}
        self._latest_encoder = None
        self._buffer = []
        self._feedback = []
        self._previous_q = self.backend.snapshot().q
        self._verification_tail_complete = False
        self._intervention = None
        self._budget_stop_tick = None
        self._budget_stop_in_progress = False
        self._budget_stop_failed = False
        self._stop_failed = False
        self.point = self.pv.operate(
            self.optics.irradiance_w_m2, self.temperature_c, self.applied_voltage_v
        )
        self._has_reset = True
        if self.recorder:
            self.recorder.start(self.config, seed, self.task)
            self.recorder.truth(
                {
                    "tick": 0,
                    "time_s": 0.0,
                    "dynamics": asdict(self.backend.snapshot()),
                    "irradiance_w_m2": self.optics.irradiance_w_m2,
                    "reference_w_m2": self.optics.reference_w_m2,
                    "temperature_c": self.temperature_c,
                    "point": asdict(self.point),
                    "requested_voltage_v": self.requested_voltage_v,
                    "applied_voltage_v": self.applied_voltage_v,
                    "disconnected": False,
                    "terminal_reason": None,
                    "intervention": None,
                }
            )
        self._capture_periodic()
        self._deliver_due()
        # Initial samples are captured at zero and delivered after their true
        # latency. This initial 20 ms is physical time, included in the ledger.
        self._advance_to(self._ticks(self.config.sensors.numeric_latency_s))
        return self.task, self._observation()

    def _capture_periodic(self) -> None:
        self._require_information_running()
        sensors = self.config.sensors
        if self.tick % self._ticks(1 / sensors.numeric_hz) == 0:
            samples = self.sensors.capture_scalars(
                self.point,
                self.temperature_c,
                self.optics.reference_w_m2,
                self.tick,
            )
            for sample in samples:
                self.clock.enqueue(self._ticks(sample.t_deliver_s), sample)
        if self.tick % self._ticks(1 / sensors.encoder_hz) == 0:
            sample = self.sensors.capture_encoder(self.backend.snapshot())
            self.clock.enqueue(self._ticks(sample.t_deliver_s), sample, event_kind="encoder")

    def _tick(self) -> None:
        self._require_information_running()
        if self.terminal_reason:
            return
        dt = self.config.simulation.dt_s
        next_tick = self.tick + 1
        if self._pending_load and next_tick >= self._pending_load[0]:
            self._load_target = self._pending_load[1]
            self.disconnected = False
            self._actuation_event(
                "load_applied",
                tick=next_tick,
                command_number=self._pending_load[2],
                voltage_v=self._load_target,
            )
            self._pending_load = None
        delta = self._load_target - self.applied_voltage_v
        self.applied_voltage_v += math.copysign(
            min(abs(delta), self.config.load.slew_v_s * dt), delta
        )
        try:
            self.backend.advance()
        except (FloatingPointError, OverflowError):
            self.clock.tick = next_tick
            self.ledger.elapsed_s = self.time_s
            self._trip("numerical_error")
            if self.recorder:
                self.recorder.truth(
                    {
                        "tick": self.tick,
                        "time_s": self.time_s,
                        "terminal_reason": "numerical_error",
                        "dynamics": None,
                        "intervention": "nonfinite_dynamics",
                    }
                )
            return
        self.clock.tick = next_tick
        snapshot = self.backend.snapshot()
        assert snapshot.tick == self.tick
        travel = tuple(abs(a - b) for a, b in zip(snapshot.q, self._previous_q, strict=True))
        self._previous_q = snapshot.q
        self.ledger.slide_path_m += travel[0]
        self.ledger.yaw_path_rad += travel[1]
        self.ledger.pitch_path_rad += travel[2]
        self.ledger.actuator_work_j = snapshot.actuator_work_j
        self.ledger.elapsed_s = self.time_s
        try:
            # Electrical and absorbed power are frozen at the interval's initial
            # thermal state, after commands due at this tick have been applied.
            point = self.pv.operate(
                self.optics.irradiance_w_m2,
                self.temperature_c,
                self.applied_voltage_v,
                self.disconnected,
            )
            maximum = self.pv.maximum_power(self.optics.irradiance_w_m2, self.temperature_c)
            update = self.thermal.advance(
                self.temperature_c, self.optics.irradiance_w_m2, point.power_w, dt
            )
            self.temperature_c = update.temperature_c
            for name in ("absorbed_j", "heat_loss_j", "storage_j"):
                setattr(self.ledger, name, getattr(self.ledger, name) + getattr(update, name))
            self.ledger.pv_energy_j += update.electrical_j
            self.ledger.potential_energy_j += maximum.power_w * dt
            # A source event at t applies to [t, next_t), never to the interval
            # just integrated. Temperature and accumulated energy stay continuous;
            # endpoint electrical/reference/RGB captures see the new source.
            if self.tick in self._source_steps:
                self.scene = self.scene.with_source_dni(self._source_steps[self.tick].dni_w_m2)
                self.optics = Optics(self.scene, self.config)
                self.backend.apply_source_state(self.tick)
            # End-of-tick V/I/T samples refer to one common physical instant.
            self.point = self.pv.operate(
                self.optics.irradiance_w_m2,
                self.temperature_c,
                self.applied_voltage_v,
                self.disconnected,
            )
        except (NumericalError, EnergyBalanceError, ValueError, OverflowError):
            self._trip("numerical_error")
        if self.terminal_reason != "numerical_error":
            self._capture_periodic()
        if self._pending_rgb and self.tick == self._pending_rgb[1]:
            start, _, frame_id = self._pending_rgb
            try:
                frame = self.backend.render_rgb(snapshot)
                sample = self.sensors.capture_rgb(frame, frame_id, start)
            except Exception as exc:
                # Preserve the partial recorder and fail visibly. Rendering is
                # required evidence and is never replaced by another image.
                raise RenderUnavailable("required MuJoCo agent_rgb capture failed") from exc
            self.clock.enqueue(self._ticks(sample.t_deliver_s), sample, event_kind="rgb")
            self._pending_rgb = None
        self._deliver_due()
        if not self.terminal_reason:
            if self.temperature_c >= self.config.thermal.trip_temperature_c:
                self._trip("thermal_trip")
            elif self.point.current_a > self.config.pv.current_limit_a:
                self._trip("overcurrent")
            elif not self.backend.limits_ok():
                self._trip("joint_limit")
            elif not self.backend.clearance_ok():
                self._trip("clearance")
            elif self.tick >= self._horizon:
                self._trip("horizon")
            elif self._budget_stop_tick is None and (
                self.ledger.slide_path_m > self.config.budgets.slide_path_m
                or self.ledger.yaw_path_rad + self.ledger.pitch_path_rad
                > self.config.budgets.angular_path_rad
            ):
                self._request_budget_stop()
        if self.recorder:
            self.recorder.truth(
                {
                    "tick": self.tick,
                    "time_s": self.time_s,
                    "dynamics": asdict(snapshot),
                    "irradiance_w_m2": self.optics.irradiance_w_m2,
                    "reference_w_m2": self.optics.reference_w_m2,
                    "temperature_c": self.temperature_c,
                    "point": None
                    if self.terminal_reason == "numerical_error"
                    else asdict(self.point),
                    "requested_voltage_v": self.requested_voltage_v,
                    "applied_voltage_v": self.applied_voltage_v,
                    "disconnected": self.disconnected,
                    "terminal_reason": self.terminal_reason,
                    "intervention": self._intervention,
                }
            )

    def _deliver_due(self) -> None:
        self._require_information_running()
        for sample in self.clock.deliver():
            self._buffer.append(sample)
            # A late older packet remains visible in the history. It cannot
            # overwrite a newer valid reading used for measured confirmation.
            if isinstance(sample, ScalarSample) and sample.validity == "valid":
                previous = self._latest_scalars.get(sample.channel)
                if previous is None or sample.t_capture_s >= previous.t_capture_s:
                    self._latest_scalars[sample.channel] = sample
            elif isinstance(sample, EncoderSample) and sample.validity == "valid":
                if (
                    self._latest_encoder is None
                    or sample.t_capture_s >= self._latest_encoder.t_capture_s
                ):
                    self._latest_encoder = sample

    def _trip(self, reason: str) -> None:
        self.terminal_reason = reason
        self.disconnected = True
        self._cancel_pending_load(reason)
        self._pending_rgb = None
        self.backend.halt()

    def _request_budget_stop(self) -> None:
        """Latch at the guard tick; never run an advancing loop inside _tick."""
        self._budget_stop_tick = self.tick
        self._intervention = {
            "kind": "travel_budget_brake",
            "trigger_tick": self.tick,
            "cleanup_deadline_tick": self._cleanup_deadline(),
        }
        self.disconnected = True
        self._cancel_pending_load("travel_budget")
        self._pending_rgb = None
        self._load_target = self.applied_voltage_v
        self.backend.halt()

    def _interrupt_for_budget_stop(self) -> None:
        if self._budget_stop_tick is not None and not self._budget_stop_in_progress:
            raise _TravelBudgetStop

    def _until(self, condition: Callable[[], bool], deadline: int) -> bool:
        self._require_information_running()
        self._interrupt_for_budget_stop()
        while not condition() and not self.terminal_reason and self.tick < deadline:
            self._tick()
            # Check before the completion predicate: the guard also cancels an
            # action whose nominal finish happens to coincide with this tick.
            self._interrupt_for_budget_stop()
        return condition() and self.terminal_reason in (None, "horizon")

    def _advance_to(self, target: int, deadline: int | None = None) -> bool:
        stop = self._horizon if deadline is None else deadline
        return self._until(lambda: self.tick >= target, min(target, stop))

    def _observation(self) -> Observation:
        self._require_information_running()
        feedback = tuple(
            ActionFeedback(
                **base,
                measured_confirmation=tuple(
                    MeasuredConfirmation(sample=s, age_s=self.time_s - s.t_capture_s)
                    for s in samples
                ),
            )
            for base, samples in self._feedback
        )
        observation = Observation(
            schema_version="1.0",
            episode_id=self.task.episode_id,
            sequence_id=self._sequence,
            t_deliver_s=self.time_s,
            scalars=tuple(s for s in self._buffer if isinstance(s, ScalarSample)),
            encoders=tuple(s for s in self._buffer if isinstance(s, EncoderSample)),
            rgb=tuple(s for s in self._buffer if isinstance(s, RGBSample)),
            feedback=feedback,
            remaining_budgets=self.ledger.remaining(self.config),
            terminal=self.terminal_reason is not None,
            terminal_reason=self.terminal_reason,
        )
        validate_observation_context(observation, self.task)
        self._sequence += 1
        self._buffer = []
        self._feedback = []
        if self.recorder:
            self.recorder.observation(observation, tick=self.tick)
        return observation

    def _add_feedback(
        self, action, code: str, accepted: float | None, *, reason=None, samples=(), action_id=None
    ) -> None:
        self._feedback.append(
            (
                {
                    "action_id": action.action_id if action else action_id,
                    "code": code,
                    "reason": reason,
                    "t_accepted_s": accepted,
                    "t_terminal_s": None if code in ("accepted", "executing") else self.time_s,
                    "commanded_target": action,
                },
                tuple(samples),
            )
        )

    def step(self, payload: Action | dict | str) -> Observation:
        if not self._has_reset:
            raise RuntimeError("reset must precede actions")
        self._require_information_running()
        if self._budget_stop_failed or self._stop_failed:
            raise SafetyStopError("measured stop remains unconfirmed; reset is required")
        if self._active:
            raise RuntimeError("synchronous environment cannot accept concurrent actions")
        raw = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
        action, invalid = None, None
        decoded_raw = raw
        if isinstance(raw, str):
            try:
                decoded_raw = json.loads(raw)
            except (ValueError, TypeError):
                pass
        raw_id = decoded_raw.get("action_id") if isinstance(decoded_raw, dict) else None
        canonicalizable = True
        try:
            canonical = json.dumps(decoded_raw, sort_keys=True, allow_nan=True)
        except (TypeError, ValueError):
            # Outside the JSON wire contract, preserve a bounded rejection marker
            # rather than invoke arbitrary Python repr or expose object internals.
            canonicalizable = False
            raw = {"kind": "invalid_non_json_payload", "action_id": raw_id}
            canonical = json.dumps(raw, sort_keys=True, allow_nan=True)
        if self.recorder:
            self.recorder.action(raw, self.tick)
        try:
            encoded = raw if isinstance(raw, str) else json.dumps(raw, allow_nan=False)
            action = ACTION_ADAPTER.validate_json(encoded)
            canonical = json.dumps(action.model_dump(mode="json"), sort_keys=True)
        except (ValidationError, ValueError, TypeError):
            invalid = "invalid_payload"
        identity = (
            action.action_id if action else (raw_id if type(raw_id) is int and raw_id > 0 else None)
        )
        if identity in self._cache:
            old_payload, observation = self._cache[identity]
            if canonical == old_payload:
                if self.recorder:
                    self.recorder.observation(observation, tick=self.tick)
                return observation
            invalid = "command_conflict"
        if identity is not None and identity <= self._highest_id:
            invalid = "command_conflict"
        action_id = (
            action.action_id
            if action
            else (raw_id if type(raw_id) is int and raw_id > 0 else self._highest_id + 1)
        )
        self._highest_id = max(self._highest_id, action_id)
        self._active = True
        self._current_action_id = action_id
        self._failure_reason = "tracking_timeout"
        self._intervention = {"kind": "decision", "action_id": action_id}
        accepted = None
        try:
            if self.terminal_reason:
                self._add_feedback(action, "rejected", None, reason="budget", action_id=action_id)
                observation = self._observation()
                if canonicalizable and identity is not None and identity not in self._cache:
                    self._cache[identity] = canonical, observation
                return observation
            decisions_available = self.ledger.decisions < self.config.budgets.decisions
            self.ledger.decisions += 1
            self._advance_to(self.tick + self._ticks(self.config.simulation.decision_overhead_s))
            if not decisions_available and not isinstance(action, SafeStop):
                invalid = "budget"
            if self.terminal_reason:
                invalid = "budget"
            if action and not invalid:
                invalid = gate(
                    action,
                    self.task,
                    self.ledger.remaining(self.config),
                    self.config,
                    self.backend.snapshot().q,
                )
            if invalid:
                self._add_feedback(action, "rejected", None, reason=invalid, action_id=action_id)
                # Exhausted decision allowance cannot create an endless zero-time
                # invalid-action loop. Its last available action is safe stop.
                if not decisions_available and not self.terminal_reason:
                    self._safe_stop(self._cleanup_deadline())
                observation = self._observation()
            else:
                accepted = self.time_s
                deadline = min(self._horizon, self.tick + self._ticks(action.timeout_s, "down"))
                self._add_feedback(action, "accepted", accepted)
                _, points = required_tokens(action)
                self.ledger.voltage_points += points
                completed, samples = self._execute(action, deadline, accepted)
                self._add_feedback(
                    action,
                    "completed" if completed else "timed_out",
                    accepted,
                    reason=None if completed else self._failure_reason,
                    samples=samples,
                )
                observation = self._observation()
            if canonicalizable and identity is not None and identity not in self._cache:
                self._cache[identity] = canonical, observation
            return observation
        except _TravelBudgetStop:
            # The action has unwound: a probe cannot restore/reconnect, a move
            # cannot resume, and a finish cannot claim its verification tail.
            samples = self._finish_budget_stop()
            self._feedback = [
                (base, measured)
                for base, measured in self._feedback
                if base["action_id"] != action_id or base["code"] in ("accepted", "executing")
            ]
            self._add_feedback(
                action,
                "cancelled" if accepted is not None else "rejected",
                accepted,
                reason="budget",
                samples=samples,
                action_id=action_id,
            )
            observation = self._observation()
            if canonicalizable and identity is not None and identity not in self._cache:
                self._cache[identity] = canonical, observation
            return observation
        finally:
            self._active = False
            self._current_action_id = None

    def _actuation_event(self, kind: str, *, tick: int | None = None, **fields) -> None:
        """Private command/application evidence; never a public acknowledgement.

        M1 recordings retain their accepted event layout. Minimal in-memory
        recorders used by core fixtures may omit this optional private stream.
        """
        if self.config.m2 is not None and self.recorder and hasattr(self.recorder, "actuation"):
            self.recorder.actuation(
                {"kind": kind, **fields},
                self.tick if tick is None else tick,
                action_id=self._current_action_id,
            )

    def _set_load(self, voltage: float) -> None:
        self._cancel_pending_load("superseded")
        self._load_command_count += 1
        number = self._load_command_count
        self.requested_voltage_v = voltage
        faults = self.config.m2.actuation if self.config.m2 is not None else None
        extra = dict(faults.load_extra_delay_s).get(number, 0.0) if faults else 0.0
        due = self.tick + self._ticks(self.config.load.delay_s + extra)
        self._actuation_event(
            "load_issued",
            command_number=number,
            voltage_v=voltage,
            due_tick=due,
        )
        if faults and number in faults.load_drop_commands:
            self._pending_load = None
            self._actuation_event("load_dropped", command_number=number, voltage_v=voltage)
        else:
            self._pending_load = (due, voltage, number)

    def _cancel_pending_load(self, reason: str) -> None:
        if self._pending_load is not None:
            self._actuation_event(
                "load_cancelled",
                command_number=self._pending_load[2],
                reason=reason,
            )
        self._pending_load = None

    def _load_settled(self, deadline: int) -> bool:
        stable_since = None

        def settled():
            nonlocal stable_since
            reached = (
                self._pending_load is None
                and not self.disconnected
                and abs(self.applied_voltage_v - self.requested_voltage_v) <= 1e-10
            )
            if not reached:
                stable_since = None
            elif stable_since is None:
                stable_since = self.tick
            return stable_since is not None and self.tick - stable_since >= self._ticks(
                self.config.load.settle_s, "up"
            )

        return self._until(settled, deadline)

    def _scalar_confirmation(self, since: int, deadline: int) -> tuple:
        def ready():
            v = self._latest_scalars.get("voltage_v")
            i = self._latest_scalars.get("current_a")
            return bool(
                v
                and i
                and v.validity == i.validity == "valid"
                and v.t_capture_s >= since * self.clock.dt_s
                and v.t_capture_s == i.t_capture_s
            )

        if not self._until(ready, deadline):
            self._failure_reason = "sensor_unavailable"
            return ()
        return self._latest_scalars["voltage_v"], self._latest_scalars["current_a"]

    def _encoder_confirmation(self, since: int, deadline: int) -> tuple:
        def ready():
            return self._latest_encoder is not None and (
                self._latest_encoder.validity == "valid"
                and self._latest_encoder.t_capture_s >= since * self.clock.dt_s
            )

        if not self._until(ready, deadline):
            self._failure_reason = "sensor_unavailable"
            return ()
        return (self._latest_encoder,)

    def _capture(self, deadline: int) -> bool:
        earliest = self._last_rgb_start + self._ticks(1 / self.config.sensors.rgb_max_hz)
        duration = self._ticks(self.config.sensors.rgb_exposure_s)
        latency = self._ticks(self.config.sensors.rgb_latency_s)
        start = max(self.tick, earliest)
        # M2 transports a real requested exposure even when hidden delivery
        # jitter makes it late. A later wait may receive that historical frame.
        required = duration + (latency if self.config.m2 is None else 0)
        if start + required > deadline:
            self._failure_reason = "sensor_unavailable"
            return False
        if not self._advance_to(start, deadline):
            return False
        self.ledger.rgb_frames += 1
        self._last_rgb_start = self.tick
        frame_id = f"frame_{self.ledger.rgb_frames:06d}"
        self._pending_rgb = (self.tick, self.tick + duration // 2, frame_id)
        delivered = self._until(
            lambda: any(isinstance(s, RGBSample) and s.frame_id == frame_id for s in self._buffer),
            deadline,
        )
        valid = delivered and any(
            isinstance(s, RGBSample) and s.frame_id == frame_id and s.validity == "valid"
            for s in self._buffer
        )
        if not valid:
            self._failure_reason = "sensor_unavailable"
        return valid

    def _motion_settled(self, target: tuple, deadline: int) -> bool:
        stable_since = None

        def settled():
            nonlocal stable_since
            snapshot = self.backend.snapshot()
            close = all(
                abs(a - b) <= e
                for a, b, e in zip(snapshot.q, target, (0.001, 0.01, 0.01), strict=True)
            ) and all(abs(v) <= e for v, e in zip(snapshot.qdot, (0.005, 0.02, 0.02), strict=True))
            if not close:
                stable_since = None
            elif stable_since is None:
                stable_since = self.tick
            return stable_since is not None and self.tick - stable_since >= self._ticks(
                self.config.camera.settle_s, "up"
            )

        return self._until(settled, deadline)

    def _safe_stop(self, deadline: int) -> bool:
        cleanup_deadline = min(self._horizon, max(deadline, self._cleanup_deadline()))
        self._intervention = {"kind": "safe_stop", "requested_deadline_tick": deadline}
        self.disconnected = True
        self._cancel_pending_load("safe_stop")
        self.backend.halt()
        stopped = self._motion_stopped(cleanup_deadline)
        if stopped and not self.terminal_reason:
            samples = self._scalar_confirmation(self.tick, cleanup_deadline)
            encoder = self._encoder_confirmation(self.tick, cleanup_deadline)
            stopped = bool(samples and encoder)
        if stopped and self.terminal_reason is None:
            self.terminal_reason = "safe_stop"
        elif not stopped and self.terminal_reason is None:
            self._stop_failed = True
            raise SafetyStopError("bounded braking did not produce measured stop confirmation")
        return stopped and self.tick <= deadline

    def _finish_budget_stop(self) -> tuple:
        """One charged, bounded stop response outside the interrupted action.

        The latched budget guard stays disabled while dynamics and all other
        protections keep advancing normally. A horizon or another protection
        takes precedence over a safe-stop claim. No confirmed stop is invented
        when the fixed cleanup deadline cannot establish fresh measurements.
        """
        deadline = min(
            self._horizon,
            self._budget_stop_tick + self._ticks(self.config.simulation.verification_tail_s),
        )
        self._budget_stop_in_progress = True
        try:
            stopped = self._motion_stopped(deadline)
            if self.terminal_reason:
                return ()
            samples = self._scalar_confirmation(self.tick, deadline) if stopped else ()
            encoders = self._encoder_confirmation(self.tick, deadline) if samples else ()
            if self.terminal_reason:
                return samples + encoders
            if not stopped or not samples or not encoders:
                self._budget_stop_failed = True
                raise SafetyStopError(
                    "travel budget stop did not produce bounded measured confirmation"
                )
            self.terminal_reason = "safe_stop"
            return samples + encoders
        finally:
            self._budget_stop_in_progress = False

    def _cleanup_deadline(self) -> int:
        return min(
            self._horizon, self.tick + self._ticks(self.config.simulation.verification_tail_s)
        )

    def _disconnect_cleanup(self, deadline: int | None = None) -> tuple:
        self._intervention = {"kind": "timeout_disconnect", "tick": self.tick}
        self.disconnected = True
        self._cancel_pending_load("timeout_disconnect")
        self._load_target = self.applied_voltage_v
        self._actuation_event("load_disconnected")
        if self.terminal_reason:
            return ()
        return self._scalar_confirmation(
            self.tick + 1, self._cleanup_deadline() if deadline is None else deadline
        )

    def _disconnect_reserve(self) -> int:
        """Room for a post-disconnect scalar capture and transport, within one tail."""
        delay = self.config.sensors.numeric_latency_s
        if self.config.m2 is not None:
            profile = self.config.m2.sensing.numeric
            delay += profile.extra_delay_s + profile.jitter_s
        return self._ticks(1 / self.config.sensors.numeric_hz + delay) + 1

    def _motion_stopped(self, deadline: int) -> bool:
        stable_since = None

        def stopped():
            nonlocal stable_since
            snapshot = self.backend.snapshot()
            low_rates = all(
                abs(v) <= limit for v, limit in zip(snapshot.qdot, (0.005, 0.02, 0.02), strict=True)
            ) and all(abs(v) < 1e-10 for v in snapshot.setpoint_rate)
            if not low_rates:
                stable_since = None
            elif stable_since is None:
                stable_since = self.tick
            return stable_since is not None and self.tick - stable_since >= self._ticks(
                self.config.camera.settle_s, "up"
            )

        return self._until(stopped, deadline)

    def _execute(self, action: Action, deadline: int, accepted: float) -> tuple[bool, tuple]:
        if isinstance(action, Wait):
            return self._advance_to(self.tick + self._ticks(action.duration_s, "up"), deadline), ()
        if isinstance(action, CaptureRGB):
            return self._capture(deadline), ()
        if isinstance(action, MoveCamera):
            target = action.slide_m, action.yaw_rad, action.pitch_rad
            self._move_command_count += 1
            number = self._move_command_count
            self._actuation_event("move_issued", command_number=number, target=target)
            faults = self.config.m2.actuation if self.config.m2 is not None else None
            if faults and number in faults.move_stall_commands:
                # Explicit drive-command inhibition, not a mechanical blockage.
                # Existing finite servos brake/hold; actual mj_step still runs.
                self.backend.halt()
                self._actuation_event("move_inhibited", command_number=number, target=target)
            else:
                self.backend.command_joint_targets(target)
                self._actuation_event(
                    "move_command_applied",
                    command_number=number,
                    target=target,
                )
            completed = self._motion_settled(target, deadline)
            samples = self._encoder_confirmation(self.tick, deadline) if completed else ()
            completed = completed and bool(samples)
            if completed and action.capture_after_settle:
                completed = self._capture(deadline)
            if not completed:
                self._intervention = {
                    "kind": "move_timeout_brake",
                    "requested_deadline_tick": deadline,
                }
                self.backend.halt()
                cleanup_deadline = self._cleanup_deadline()
                stopped = self._motion_stopped(cleanup_deadline)
                samples = self._encoder_confirmation(self.tick, cleanup_deadline) if stopped else ()
                if (not stopped or not samples) and not self.terminal_reason:
                    self._stop_failed = True
                    raise SafetyStopError("move timeout cleanup did not establish measured stop")
            return completed, samples
        if isinstance(action, SetVoltage):
            self._set_load(action.voltage_v)
            completed = self._load_settled(deadline)
            samples = self._scalar_confirmation(self.tick, deadline) if completed else ()
            completed = completed and bool(samples)
            if not completed:
                samples = self._disconnect_cleanup()
            return completed, samples
        if isinstance(action, ProbeVoltage):
            previous = self.requested_voltage_v
            completed = True
            for voltage in action.voltages_v:
                self._set_load(voltage)
                if not self._load_settled(deadline):
                    completed = False
                    break
                dwell_start = self.tick
                if not self._advance_to(self.tick + self._ticks(action.dwell_s, "up"), deadline):
                    completed = False
                    break
                samples = self._scalar_confirmation(dwell_start, deadline)
                if not samples:
                    completed = False
                    break
                # Executing feedback means this settled point's dwell completed;
                # final completed feedback below refers only to restoration.
                self._add_feedback(action, "executing", accepted, samples=samples)
            if self.terminal_reason:
                return False, ()
            self._set_load(previous)
            # One fixed tail belongs to this action. Restoration attempts must
            # not restart that clock, and leave room for measured disconnection.
            cleanup_deadline = min(
                self._horizon, deadline + self._ticks(self.config.simulation.verification_tail_s)
            )
            fallback_tick = max(self.tick, cleanup_deadline - self._disconnect_reserve())
            restore_deadline = deadline if completed else fallback_tick
            restored = self._load_settled(restore_deadline)
            confirmation = (
                self._scalar_confirmation(self.tick, restore_deadline) if restored else ()
            )
            if (not restored or not confirmation) and not self.terminal_reason:
                completed = False
                self._intervention = {
                    "kind": "probe_timeout_restore",
                    "requested_deadline_tick": deadline,
                }
                restored = self._load_settled(fallback_tick)
                confirmation = (
                    self._scalar_confirmation(self.tick, fallback_tick) if restored else ()
                )
            if not restored or not confirmation:
                confirmation = self._disconnect_cleanup(cleanup_deadline)
            return completed and restored and bool(confirmation), confirmation
        if isinstance(action, SafeStop):
            completed = self._safe_stop(deadline)
            samples = tuple(self._latest_scalars.values())
            if self._latest_encoder:
                samples += (self._latest_encoder,)
            return completed, samples
        if isinstance(action, Finish):
            start = self.tick
            tail = self._ticks(self.config.simulation.verification_tail_s)
            completed = self._advance_to(start + tail, deadline)
            if completed and self.terminal_reason in (None, "horizon"):
                self._verification_tail_complete = True
                self.terminal_reason = "finished"
            return completed, tuple(self._latest_scalars.values())
        raise AssertionError("unavailable action escaped the gate")

    def metrics(self) -> dict:
        return {
            **self.ledger.report(self.config),
            "tick": self.tick,
            "terminal_reason": self.terminal_reason,
            "verification_tail_complete": self._verification_tail_complete,
            "core_only": not self.enable_rendering,
            "mode": "trusted-policy/local",
            "final_temperature_c": self.temperature_c,
            "final_operating_point": (
                None if self.terminal_reason == "numerical_error" else asdict(self.point)
            ),
            "final_dynamics": (
                None
                if self.terminal_reason == "numerical_error"
                else asdict(self.backend.snapshot())
            ),
            "load_disconnected": self.disconnected,
            "prediction_coverage": 0.0,
        }

    def close(self) -> None:
        self.backend.close()
