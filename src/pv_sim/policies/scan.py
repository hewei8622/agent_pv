"""B1 M1 schedule: home/side RGB, three measured points, then fresh verification.

The frozen public feedback convention identifies probe dwell evidence without a
new schema: each point emits executing feedback after its settled dwell completes.
Its measured_confirmation contains matched delivered V/I from that final dwell;
the identical readings are in Observation.scalars. Completed probe feedback is
restoration evidence and is never a candidate operating point. This policy trusts
that producer convention, not arbitrary readings near a requested voltage.
"""

from __future__ import annotations

import math

from pv_sim.contracts import (
    ActionFeedback,
    Decision,
    EncoderSample,
    MoveCamera,
    Observation,
    PublicTask,
    ScalarSample,
)
from pv_sim.policies.protocol import VOLTAGE_TOLERANCE_V, PublicBaseline, matched_pairs


class ScanPolicy(PublicBaseline):
    """Smallest integrated M1 scan; no help rule or causal confidence is claimed."""

    def reset(self, task: PublicTask) -> None:
        super().reset(task)
        self.chosen_voltage: float | None = None
        self.verification_after_s: float | None = None
        self.probe_evidence_refs: tuple[int, ...] = ()

    def act(self, history: tuple[Observation, ...]) -> Decision:
        if history and history[-1].terminal:
            return self._stop(history, "Episode is already terminal.")
        if self.stage == "start":
            if not {"rgb", "encoders", "voltage_v", "current_a"} <= set(self.task.sensors):
                return self._stop(
                    history, "The scripted scan requires advertised RGB, encoders and V/I."
                )
            self.stage = "home"
            return self._emit(history, "capture_rgb", "Capture the initial home view.")
        if self.stage in {"stopped", "finished"}:
            return self._stop(history, "No further investigation is scheduled.")
        feedback = self._completion(history)
        if feedback is None or feedback.code != "completed":
            return self._stop(history, "The previous action lacks successful completion feedback.")
        if self.stage == "home":
            if not self._has_frame(history, feedback):
                return self._stop(history, "The requested home image was not delivered.")
            self.stage = "side"
            return self._emit(
                history,
                "move_camera",
                "Move to the reachable side view using public nominal geometry.",
                slide_m=0.12,
                yaw_rad=math.atan(0.12 / 0.45),
                pitch_rad=0.0,
                capture_after_settle=True,
            )
        if self.stage == "side":
            if not self._has_frame(history, feedback) or not self._pose_confirmed(feedback):
                return self._stop(
                    history, "A settled side view lacks delivered image or encoder evidence."
                )
            self.stage = "probe"
            return self._emit(
                history,
                "probe_voltage",
                "Measure the fixed voltage schedule with 0.5 s settled dwell per point.",
                voltages_v=(0.8, 1.8, 3.0),
                dwell_s=0.5,
            )
        if self.stage == "probe":
            self.chosen_voltage = self._select_probe_point(history, feedback)
            if self.chosen_voltage is None:
                return self._stop(
                    history, "The probe lacks matched delivered V/I evidence for every point."
                )
            self.stage = "set"
            return self._emit(
                history,
                "set_voltage",
                "Select the scheduled point with the greatest measured V times I.",
                evidence_refs=self.probe_evidence_refs,
                voltage_v=self.chosen_voltage,
            )
        if self.stage == "set":
            if not self._voltage_confirmed(feedback, self.chosen_voltage):
                return self._stop(
                    history, "The selected voltage lacks fresh measured confirmation."
                )
            self.verification_after_s = feedback.t_terminal_s
            self.stage = "verify"
            return self._emit(
                history,
                "wait",
                "Collect newer timestamped V/I after the selected operating point settles.",
                duration_s=0.5,
                timeout_s=1.0,
            )
        if self.stage == "verify":
            refs = self._verification_refs(history)
            if not refs:
                return self._stop(
                    history, "No newer matched V/I verifies the selected operating point."
                )
            self.stage = "finished"
            return self._emit(
                history,
                "finish",
                "Fresh V/I verifies the operating point; causal diagnosis remains unresolved.",
                evidence_refs=refs,
                resolution="unresolved",
                timeout_s=2.0,
            )
        return self._stop(history, "Unknown policy stage.")

    def _pose_confirmed(self, feedback: ActionFeedback) -> bool:
        target = self.pending
        if not isinstance(target, MoveCamera) or not target.capture_after_settle:
            return False
        return feedback.t_accepted_s is not None and any(
            isinstance(m.sample, EncoderSample)
            and m.sample.validity == "valid"
            and m.sample.t_capture_s >= feedback.t_accepted_s
            and abs(m.sample.slide_m - target.slide_m) <= 0.002
            and abs(m.sample.yaw_rad - target.yaw_rad) <= 0.01
            and abs(m.sample.pitch_rad - target.pitch_rad) <= 0.01
            for m in feedback.measured_confirmation
        )

    def _select_probe_point(
        self, history: tuple[Observation, ...], completed: ActionFeedback
    ) -> float | None:
        points: dict[float, tuple[float, float, int]] = {}
        for observation in history:
            for feedback in observation.feedback:
                if (
                    feedback.action_id != self.pending.action_id
                    or feedback.code != "executing"
                    or feedback.commanded_target != self.pending
                    or feedback.t_accepted_s is None
                ):
                    continue
                samples = tuple(
                    m.sample
                    for m in feedback.measured_confirmation
                    if isinstance(m.sample, ScalarSample) and m.sample in observation.scalars
                )
                for voltage, current in matched_pairs(samples):
                    if not feedback.t_accepted_s <= voltage.t_capture_s < completed.t_terminal_s:
                        continue
                    for target in self.pending.voltages_v:
                        if abs(voltage.value - target) <= VOLTAGE_TOLERANCE_V:
                            candidate = (
                                voltage.t_capture_s,
                                voltage.value * current.value,
                                observation.sequence_id,
                            )
                            if target not in points or candidate[0] > points[target][0]:
                                points[target] = candidate
        if set(points) != set(self.pending.voltages_v):
            return None
        self.probe_evidence_refs = tuple(sorted({point[2] for point in points.values()}))
        return max(self.pending.voltages_v, key=lambda target: points[target][1])

    def _verification_refs(self, history: tuple[Observation, ...]) -> tuple[int, ...]:
        for observation in reversed(history):
            for voltage, current in reversed(matched_pairs(observation.scalars)):
                if (
                    voltage.t_capture_s > self.verification_after_s
                    and abs(voltage.value - self.chosen_voltage) <= VOLTAGE_TOLERANCE_V
                    and current.value >= 0
                ):
                    return (observation.sequence_id,)
        return ()
