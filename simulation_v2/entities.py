"""Mutable simulation entities for the V2 multi-cell orchestration engine."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Station:
    name: str                      # "<cell_name><n>"
    number: int                    # 1-based within the cell
    state: str = "Idle"            # Idle | Working | Holding | Starving
    remaining: int = 0
    unit_id: Optional[int] = None
    entry_tick: Optional[int] = None
    part_name: Optional[str] = None
    parts_per_unit: int = 0
    effective_ticks: int = 0
    units_remaining: int = 0       # line-side buffer contents for this station's part
    units_started_at_station: int = 0
    starving_since: Optional[int] = None
    working_ticks: int = 0
    starving_ticks: int = 0
    pending_request: bool = False  # a delivery request queued or an AMR Outbound to it
    used: bool = False             # ever assigned to a job, for reporting


@dataclass
class Cell:
    name: str
    distance_meters: int
    speed_factor: float
    num_stations: int
    lineside_buffer_size: int
    output_buffer_size: int
    stations: list = field(default_factory=list)   # list[Station], index 0 == station 1
    state: str = "Idle"             # Idle | Setup | Running | Blocked | Draining
    job: Optional[str] = None       # current/most recent job name
    job_cycle_ticks: int = 0
    output_buffer_count: int = 0
    blocked_reason: Optional[str] = None
    blocked_since: Optional[int] = None
    pending_pickup: bool = False
    assigned_tick: Optional[int] = None
    next_unit_number: int = 0
    units_completed_at_cell: int = 0
    setup_ticks: int = 0
    running_ticks: int = 0
    blocked_ticks_starved: int = 0
    blocked_ticks_output_full: int = 0
    draining_ticks: int = 0


@dataclass
class Job:
    name: str
    product_name: str
    units: int
    arrival_tick: int
    deadline_tick: int
    capable_cells: list
    steps: list
    file_index: int
    assigned_cell: Optional[str] = None
    assigned_tick: Optional[int] = None
    begin_tick: Optional[int] = None
    complete_at_cell_tick: Optional[int] = None
    completion_tick: Optional[int] = None
    units_delivered_to_store: int = 0
    cycle_ticks_list: list = field(default_factory=list)
    preemption_evaluated: bool = False  # a preemptable job is only ever considered once
    times_preempted: int = 0


@dataclass
class AMR:
    name: str
    type_name: str
    units_carried: int
    speed_m_per_s: float
    cost_dollars: int
    state: str = "Idle"              # Idle | Outbound | Inbound
    remaining: int = 0
    trip_kind: Optional[str] = None  # "delivery" | "pickup" | "return"
    cell_name: Optional[str] = None
    station_name: Optional[str] = None
    part_name: Optional[str] = None
    qty: int = 0
    loaded_qty: int = 0              # actual quantity loaded (may be < units_carried for a
                                      # finite intermediate part if the store can't fill capacity)
    job_name_for_trip: Optional[str] = None
    busy_ticks: int = 0
    trips: int = 0


@dataclass
class TransportRequest:
    kind: str                        # "delivery" | "pickup" | "return"
    cell_name: str
    station_name: Optional[str] = None
    part_name: Optional[str] = None
    qty: Optional[int] = None        # fixed quantity for "return" trips (the buffer is
                                      # cleared instantly at preemption, so this can't be
                                      # recomputed later from cell state like delivery/pickup)
    job_name: Optional[str] = None   # job to attribute a "return" trip's events to,
                                      # captured at preemption time since cell.job changes
                                      # to the new job immediately
