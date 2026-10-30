import math
from pathlib import Path

import pytest

from pv_sim.contracts import PublicTask

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def action():
    return {
        "schema_version": "1.0",
        "action_id": 1,
        "kind": "move_camera",
        "timeout_s": 8.0,
        "slide_m": 0.15,
        "yaw_rad": 0.0,
        "pitch_rad": 0.0,
        "capture_after_settle": True,
    }


@pytest.fixture
def decision(action):
    return dict(
        schema_version="1.0",
        action=action,
        predictions=[],
        hypothesis_probabilities=None,
        unresolved_hypotheses=[],
        evidence_refs=[],
        rationale="Inspect the region.",
    )


@pytest.fixture
def task():
    f = 480 / (2 * math.tan(math.pi / 8))
    return PublicTask(
        schema_version="1.0",
        episode_id="episode_opaque",
        goal="Inspect and verify",
        sensors=("voltage_v", "current_a", "temperature_c", "reference_w_m2", "encoders", "rgb"),
        limits=dict(
            slide_m=(-0.15, 0.15),
            yaw_rad=(-math.pi / 4, math.pi / 4),
            pitch_rad=(-math.pi / 6, math.pi / 6),
            voltage_v=(0.2, 4.0),
        ),
        available_actions=(
            "move_camera",
            "set_voltage",
            "probe_voltage",
            "capture_rgb",
            "wait",
            "safe_stop",
            "finish",
        ),
        available_help=(),
        horizon_s=60.0,
        budgets=dict(
            time_s=60.0,
            rgb_frames=20,
            voltage_points=12,
            help_requests=1,
            decisions=100,
            slide_path_m=1.5,
            angular_path_rad=6.0,
        ),
        cost_weights=dict(
            pv_energy_scale_j=60.0,
            rgb=0.1,
            voltage_point=0.2,
            help_request=1.0,
            slide_per_m=0.5,
            angle_per_rad=0.05,
        ),
        nominal_calibration=dict(
            calibration_id="nominal_v1",
            camera_id="agent_rgb",
            width=640,
            height=480,
            fovy_deg=45.0,
            k=(f, 0, 319.5, 0, f, 239.5, 0, 0, 1),
            home_position_m=(0, -0.45, 0.35),
            pixel_convention="top_left_center_0_0_x_right_y_down",
            camera_axes="x_right_y_up_minus_z_forward",
        ),
        knowledge_condition="nominal v7 geometry",
        allowed_adaptation="none",
        hypothesis_classes=("h_a", "h_b"),
    )


@pytest.fixture
def scalar():
    return dict(
        channel="voltage_v",
        value=1.8,
        sigma=0.01,
        t_capture_s=0.0,
        t_deliver_s=0.02,
        validity="valid",
        sensor_id="v_sensor",
    )


@pytest.fixture
def observation(task, scalar):
    return dict(
        schema_version="1.0",
        episode_id=task.episode_id,
        sequence_id=0,
        t_deliver_s=0.02,
        scalars=[scalar],
        encoders=[],
        rgb=[],
        feedback=[],
        remaining_budgets=task.budgets.model_dump(mode="json"),
        terminal=False,
        terminal_reason=None,
    )
