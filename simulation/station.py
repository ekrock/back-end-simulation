from dataclasses import dataclass
from typing import Optional


@dataclass
class Station:
    name: str
    action_name: str
    state: str = "Idle"               # "Idle" or "Working"
    part_present: bool = False
    locked: bool = False
    current_part_id: Optional[int] = None
    current_robot: Optional[str] = None
