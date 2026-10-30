"""B0: keep the home camera and 1.8 V load, without causal diagnosis."""

from pv_sim.contracts import Decision, Observation
from pv_sim.policies.protocol import PublicBaseline


class FixedPolicy(PublicBaseline):
    """Reserve the published 2 s finish tail and 0.2 s decision overhead."""

    def act(self, history: tuple[Observation, ...]) -> Decision:
        if history and history[-1].terminal:
            return self._stop(history, "Episode is already terminal.")
        if self.stage == "start":
            self.stage = "holding"
            return self._emit(
                history, "set_voltage", "Hold the fixed 1.8 V baseline load.", voltage_v=1.8
            )
        if self.stage != "holding":
            return self._stop(history, "No further baseline work is scheduled.")
        feedback = self._completion(history)
        if feedback is None or feedback.code != "completed":
            return self._stop(history, "The previous action lacks successful completion feedback.")
        if self.pending.kind == "set_voltage" and not self._voltage_confirmed(feedback, 1.8):
            return self._stop(history, "The fixed voltage was not confirmed by a new measurement.")
        remaining = history[-1].remaining_budgets.time_s if history else self.task.horizon_s
        # Every following wait incurs 0.2 s, and finish also incurs 0.2 s.
        # The extra 0.1 s allows a final minimum-length wait without overshoot.
        if remaining <= 2.5 + 1e-9:
            self.stage = "finished"
            return self._emit(
                history,
                "finish",
                "Fixed control is complete; retain the load for the verification tail.",
                resolution="unresolved",
                timeout_s=2.0,
            )
        duration = min(5.0, remaining - 2.4)
        return self._emit(
            history,
            "wait",
            "Collect the ordinary sensor stream at the fixed operating point.",
            duration_s=duration,
            timeout_s=duration + 0.1,
        )
