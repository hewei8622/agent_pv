"""Private, deterministic M2 fixture controls; never part of the policy task."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from pv_sim.contracts import Nonnegative, Number, Positive, Record

CommandOrdinal = Annotated[int, Field(strict=True, ge=1)]


class TimingProfile(Record):
    extra_delay_s: Nonnegative = 0.0
    jitter_s: Nonnegative = 0.0
    dropout_probability: Annotated[Number, Field(ge=0, le=1)] = 0.0
    stale_after_s: Positive | None = None


class SensingFixtures(Record):
    numeric: TimingProfile = Field(default_factory=TimingProfile)
    encoder: TimingProfile = Field(default_factory=TimingProfile)
    rgb: TimingProfile = Field(default_factory=TimingProfile)


class ActuationFixtures(Record):
    load_drop_commands: tuple[CommandOrdinal, ...] = ()
    load_extra_delay_s: tuple[tuple[CommandOrdinal, Nonnegative], ...] = ()
    move_stall_commands: tuple[CommandOrdinal, ...] = ()

    @model_validator(mode="after")
    def unique_commands(self) -> Self:
        for values in (
            self.load_drop_commands,
            self.move_stall_commands,
            tuple(ordinal for ordinal, _ in self.load_extra_delay_s),
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate private command ordinal")
        return self


class ViewFixtures(Record):
    screen_half_width_m: Literal[0.03, 0.06] | None = None
    rail_locked: bool = False


class M2Config(Record):
    sensing: SensingFixtures = Field(default_factory=SensingFixtures)
    actuation: ActuationFixtures = Field(default_factory=ActuationFixtures)
    view: ViewFixtures = Field(default_factory=ViewFixtures)
