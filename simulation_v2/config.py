"""Dataclasses for the V2 (multi-cell orchestration) simulation config."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SimulationConfigV2:
    name: str
    description: str
    max_ticks: int
    scheduling_policy: str          # "FIFO" | "EDD"
    replenishment_policy: str       # "UnitsLeft" | "PercentLeft" | "PredictedOut"
    replenishment_value: int
    preemption_enabled: bool = False


@dataclass
class AMRTypeDef:
    type_name: str
    units_carried: int
    speed_m_per_s: float
    cost_dollars: int


@dataclass
class AMRCountDef:
    type_name: str
    count: int


@dataclass
class CellDef:
    cell_name: str
    distance_meters: int
    speed_factor: float
    num_stations: int
    lineside_buffer_size: int
    output_buffer_size: int


@dataclass
class JobStepDef:
    station_number: int
    part_name: str
    parts_per_unit: int
    ticks: int
    min_available: Optional[int] = None  # P1-2 threshold gate: None = require full producer
                                # completion (legacy behavior); an int = schedulable
                                # once the store holds at least this many units.


@dataclass
class JobDef:
    job_name: str
    product_name: str
    units: int
    arrival_tick: int
    deadline_tick: int
    capable_cells: list
    steps: list = field(default_factory=list)  # list[JobStepDef], ascending station_number


@dataclass
class SimConfigV2:
    simulation: SimulationConfigV2
    amr_types: list
    amr_counts: list
    cells: list
    parts: list      # list[str], external part names
    jobs: list        # list[JobDef], file order
