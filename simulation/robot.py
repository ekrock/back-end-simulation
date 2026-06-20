from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RobotType:
    type_name: str
    speed_meters_per_tick: Optional[int]  # None for non-moving robots
    cost_dollars: int
    actions: dict = field(default_factory=dict)  # action_name -> ticks_per_action


@dataclass
class Robot:
    name: str
    robot_type: RobotType
    state: str = "Idle"                   # "Idle" or "Working"
    remaining_ticks: int = 0
    current_action: Optional[str] = None
    current_station: Optional[str] = None
    current_part_id: Optional[int] = None
    working_ticks: int = 0

    def can_do(self, action: str) -> bool:
        return action in self.robot_type.actions

    def ticks_for(self, action: str) -> int:
        return self.robot_type.actions[action]

    @property
    def cost_dollars(self) -> int:
        return self.robot_type.cost_dollars

    @property
    def speed(self) -> Optional[int]:
        return self.robot_type.speed_meters_per_tick
