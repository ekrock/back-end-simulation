from dataclasses import dataclass, field


@dataclass
class LineState:
    input_buffer_size: int = 0
    output_buffer_size: int = 0
    central_store_distance_meters: int = 0
    fetch_trigger_threshold: int = 0
    deliver_trigger_threshold: int = 0
    input_buffer_count: int = 0
    output_buffer_count: int = 0
    parts_completed: int = 0
    job_started: bool = False
    next_part_id: int = 1
    entry_tick: dict = field(default_factory=dict)  # part_id -> tick entered station 1
    parts_started: int = 0  # parts that have entered station 1; capped at parts_to_build
