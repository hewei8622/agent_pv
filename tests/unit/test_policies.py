"""Public-history fixtures test policy reasoning; they are not engine/render evidence."""

import base64
import io
import math

import pytest
from PIL import Image

from pv_sim.contracts import (
    ActionFeedback,
    EncoderSample,
    MeasuredConfirmation,
    Observation,
    RGBSample,
    ScalarSample,
    validate_decision_context,
)
from pv_sim.policies import FixedPolicy, ScanPolicy
from pv_sim.policy_runner import PolicyRunner


def sample(channel, value, capture, *, validity="valid", delivery=None):
    return ScalarSample(
        channel=channel,
        value=value,
        sigma=0.0,
        t_capture_s=capture,
        t_deliver_s=capture + 0.02 if delivery is None else delivery,
        validity=validity,
        sensor_id=channel,
    )


def pair(voltage, current, capture, *, validity="valid"):
    return (
        sample("voltage_v", voltage, capture, validity=validity),
        sample("current_a", current, capture, validity=validity),
    )


def feedback(action, accepted, terminal, *, samples=(), code="completed"):
    return ActionFeedback(
        action_id=action.action_id,
        code=code,
        reason=None,
        t_accepted_s=accepted,
        t_terminal_s=terminal if code not in {"accepted", "executing"} else None,
        commanded_target=action,
        measured_confirmation=tuple(
            MeasuredConfirmation(sample=s, age_s=terminal - s.t_capture_s) for s in samples
        ),
    )


def observation(task, sequence, now, *, scalars=(), rgb=(), encoders=(), feedbacks=()):
    budgets = task.budgets.model_copy(update={"time_s": task.horizon_s - now})
    return Observation(
        schema_version="1.0",
        episode_id=task.episode_id,
        sequence_id=sequence,
        t_deliver_s=now,
        scalars=scalars,
        encoders=encoders,
        rgb=rgb,
        feedback=feedbacks,
        remaining_budgets=budgets,
        terminal=False,
        terminal_reason=None,
    )


def frame(task, capture):
    image = Image.new("RGB", (640, 480), (40, 70, 100))
    payload = io.BytesIO()
    image.save(payload, format="PNG")
    return RGBSample(
        frame_id=f"fixture_{int(capture * 1000)}",
        camera_id="agent_rgb",
        width=640,
        height=480,
        encoding="png_rgb8",
        png_base64=base64.b64encode(payload.getvalue()).decode(),
        calibration_id=task.nominal_calibration.calibration_id,
        k=task.nominal_calibration.k,
        exposure=dict(duration_s=0.012, approximation="midpoint_snapshot"),
        t_start_s=capture - 0.006,
        t_capture_s=capture,
        t_end_s=capture + 0.006,
        t_deliver_s=capture + 0.106,
        validity="valid",
    )


def encoder(action, capture):
    return EncoderSample(
        sensor_id="encoder",
        slide_m=action.slide_m,
        yaw_rad=action.yaw_rad,
        pitch_rad=action.pitch_rad,
        slide_rate_m_s=0.0,
        yaw_rate_rad_s=0.0,
        pitch_rate_rad_s=0.0,
        sigma=dict(slide_m=0.0, yaw_rad=0.0, pitch_rad=0.0),
        t_capture_s=capture,
        t_deliver_s=capture + 0.01,
        validity="valid",
    )


def through_side(task):
    policy = ScanPolicy()
    runner = PolicyRunner(policy, task)
    history = (observation(task, 0, 0.0),)
    home = runner.decide(history)
    assert home.action.kind == "capture_rgb"
    history += (
        observation(
            task, 1, 1.0, rgb=(frame(task, 0.5),), feedbacks=(feedback(home.action, 0.2, 1.0),)
        ),
    )
    side = runner.decide(history)
    assert side.action.kind == "move_camera"
    assert side.action.slide_m == 0.12
    assert side.action.yaw_rad == math.atan(0.12 / 0.45)
    assert side.action.capture_after_settle
    measured = encoder(side.action, 4.0)
    history += (
        observation(
            task,
            2,
            4.5,
            rgb=(frame(task, 4.3),),
            encoders=(measured,),
            feedbacks=(feedback(side.action, 1.2, 4.5, samples=(measured,)),),
        ),
    )
    probe = runner.decide(history)
    assert probe.action.kind == "probe_voltage"
    assert probe.action.voltages_v == (0.8, 1.8, 3.0)
    assert probe.action.dwell_s == 0.5
    return runner, history, probe


def probe_result(task, probe, *, omit=None, stale=None, restoration_power=1000.0, mismatched=None):
    all_samples, confirmations = [], []
    for voltage, current, capture in ((0.8, 1.0, 5.4), (1.8, 0.8, 6.4), (3.0, 0.3, 7.4)):
        samples = pair(voltage, current, capture, validity="stale" if stale == voltage else "valid")
        if mismatched == voltage:
            samples = (samples[0], sample("current_a", current, capture + 0.1))
        all_samples.extend(samples)
        if omit != voltage:
            confirmations.append(
                feedback(probe.action, 4.7, 8.5, samples=samples, code="executing")
            )
    # A high-power old pair and a restoration pair must never influence selection.
    all_samples.extend(pair(3.0, 2000.0, 0.0))
    restored = pair(3.0, restoration_power, 8.0)
    all_samples.extend(restored)
    confirmations.append(feedback(probe.action, 4.7, 8.5, samples=restored))
    return observation(task, 3, 8.5, scalars=tuple(all_samples), feedbacks=tuple(confirmations))


def test_scan_complete_public_sequence_uses_probe_then_new_verification(task):
    runner, history, probe = through_side(task)
    history += (probe_result(task, probe),)
    chosen = runner.decide(history)
    assert chosen.action.kind == "set_voltage"
    assert chosen.action.voltage_v == 1.8  # P=1.44 exceeds .8 and .9; restoration excluded.
    assert chosen.evidence_refs == (3,)
    new_samples = pair(1.8, 0.8, 9.1)
    history += (
        observation(
            task,
            4,
            9.3,
            scalars=new_samples,
            feedbacks=(feedback(chosen.action, 8.7, 9.3, samples=new_samples),),
        ),
    )
    verify = runner.decide(history)
    assert verify.action.kind == "wait"
    fresh_samples = pair(1.8, 0.8, 9.9)
    history += (
        observation(
            task, 5, 10.2, scalars=fresh_samples, feedbacks=(feedback(verify.action, 9.5, 10.2),)
        ),
    )
    finish = runner.decide(history)
    assert finish.action.kind == "finish"
    assert finish.action.resolution == "unresolved"
    assert finish.evidence_refs == (5,)
    for decision in (probe, chosen, verify, finish):
        assert decision.predictions == ()
        assert decision.hypothesis_probabilities is None
        assert decision.unresolved_hypotheses == task.hypothesis_classes
        validate_decision_context(decision, task, history)
    assert runner.last_failure is None


@pytest.mark.parametrize("change", [{"omit": 0.8}, {"stale": 1.8}, {"mismatched": 3.0}])
def test_scan_missing_stale_or_unmatched_dwell_point_stops(task, change):
    runner, history, probe = through_side(task)
    history += (probe_result(task, probe, **change),)
    assert runner.decide(history).action.kind == "safe_stop"


def test_scan_old_measurements_cannot_verify_new_set(task):
    runner, history, probe = through_side(task)
    history += (probe_result(task, probe),)
    chosen = runner.decide(history)
    readings = pair(1.8, 0.8, 9.1)
    history += (
        observation(
            task,
            4,
            9.3,
            scalars=readings,
            feedbacks=(feedback(chosen.action, 8.7, 9.3, samples=readings),),
        ),
    )
    wait = runner.decide(history)
    history += (
        observation(task, 5, 10.2, scalars=readings, feedbacks=(feedback(wait.action, 9.5, 10.2),)),
    )
    assert runner.decide(history).action.kind == "safe_stop"


@pytest.mark.parametrize("code", ["accepted", "rejected", "timed_out", "failed", "cancelled"])
@pytest.mark.parametrize("policy_type", [FixedPolicy, ScanPolicy])
def test_baselines_do_not_assume_action_success(task, code, policy_type):
    runner = PolicyRunner(policy_type(), task)
    history = (observation(task, 0, 0.0),)
    decision = runner.decide(history)
    history += (
        observation(task, 1, 1.0, feedbacks=(feedback(decision.action, 0.2, 1.0, code=code),)),
    )
    assert runner.decide(history).action.kind == "safe_stop"
    assert runner.last_failure is None


def test_scan_completed_move_without_encoder_confirmation_stops(task):
    runner = PolicyRunner(ScanPolicy(), task)
    history = (observation(task, 0, 0.0),)
    home = runner.decide(history)
    history += (
        observation(
            task, 1, 1.0, rgb=(frame(task, 0.5),), feedbacks=(feedback(home.action, 0.2, 1.0),)
        ),
    )
    side = runner.decide(history)
    history += (
        observation(
            task, 2, 4.5, rgb=(frame(task, 4.3),), feedbacks=(feedback(side.action, 1.2, 4.5),)
        ),
    )
    assert runner.decide(history).action.kind == "safe_stop"


def test_fixed_waits_to_leave_two_second_tail_without_camera_or_help(task):
    runner = PolicyRunner(FixedPolicy(), task)
    history = (observation(task, 0, 0.0),)
    decision = runner.decide(history)
    assert decision.action.kind == "set_voltage"
    assert decision.action.voltage_v == 1.8
    readings = pair(1.8, 0.8, 0.5)
    history += (
        observation(
            task,
            1,
            0.7,
            scalars=readings,
            feedbacks=(feedback(decision.action, 0.2, 0.7, samples=readings),),
        ),
    )
    kinds = []
    for sequence in range(2, 30):
        decision = runner.decide(history)
        kinds.append(decision.action.kind)
        assert decision.action.action_id == sequence
        if decision.action.kind == "finish":
            break
        assert decision.action.kind == "wait"
        accepted = history[-1].t_deliver_s + 0.2
        now = accepted + decision.action.duration_s
        history += (
            observation(task, sequence, now, feedbacks=(feedback(decision.action, accepted, now),)),
        )
    assert kinds[-1] == "finish"
    assert history[-1].remaining_budgets.time_s >= 2.2 - 1e-9
    assert set(kinds) == {"wait", "finish"}
    assert runner.last_failure is None
