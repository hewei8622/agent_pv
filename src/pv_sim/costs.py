"""Raw dimensional accounting, distinct from synthetic planning utility."""

from dataclasses import asdict, dataclass

from pv_sim.config import Config
from pv_sim.contracts import Budgets


@dataclass
class Ledger:
    elapsed_s: float = 0.0
    policy_wall_s: float = 0.0
    decisions: int = 0
    rgb_frames: int = 0
    voltage_points: int = 0
    slide_path_m: float = 0.0
    yaw_path_rad: float = 0.0
    pitch_path_rad: float = 0.0
    help_requests: int = 0
    help_delay_s: float = 0.0
    pv_energy_j: float = 0.0
    potential_energy_j: float = 0.0
    actuator_work_j: float = 0.0
    absorbed_j: float = 0.0
    heat_loss_j: float = 0.0
    storage_j: float = 0.0

    def remaining(self, config: Config) -> Budgets:
        b = config.budgets
        return Budgets(
            time_s=max(0.0, b.time_s - self.elapsed_s),
            decisions=max(0, b.decisions - self.decisions),
            rgb_frames=max(0, b.rgb_frames - self.rgb_frames),
            voltage_points=max(0, b.voltage_points - self.voltage_points),
            help_requests=max(0, b.help_requests - self.help_requests),
            slide_path_m=max(0.0, b.slide_path_m - self.slide_path_m),
            angular_path_rad=max(0.0, b.angular_path_rad - self.yaw_path_rad - self.pitch_path_rad),
        )

    def report(self, config: Config) -> dict:
        report = asdict(self)
        w = config.cost_weights
        report["synthetic_dimensionless_utility"] = (
            self.pv_energy_j / w.pv_energy_scale_j
            - w.rgb * self.rgb_frames
            - w.voltage_point * self.voltage_points
            - w.help_request * self.help_requests
            - w.slide_per_m * self.slide_path_m
            - w.angle_per_rad * (self.yaw_path_rad + self.pitch_path_rad)
        )
        report["energy_balance_residual_j"] = (
            self.absorbed_j - self.pv_energy_j - self.heat_loss_j - self.storage_j
        )
        return report
