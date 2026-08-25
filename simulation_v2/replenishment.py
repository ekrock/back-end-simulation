"""Replenishment policies: UnitsLeft, PercentLeft, PredictedOut (Section 12.3)."""
import math

from simulation_v2.entities import TransportRequest


def run_replenishment(config, cells, jobs_by_name, tick, min_amr_speed, request_queue, log):
    policy_name = config.simulation.replenishment_policy
    policy_value = config.simulation.replenishment_value

    for cell in cells:
        if cell.job is None or cell.state not in ("Setup", "Running", "Blocked"):
            continue
        job = jobs_by_name[cell.job]
        k = len(job.steps)
        for station in cell.stations[:k]:
            if station.pending_request:
                continue

            consumed_so_far = station.units_started_at_station * station.parts_per_unit
            still_needed = job.units * station.parts_per_unit - consumed_so_far - station.units_remaining
            if still_needed <= 0:
                continue

            if policy_name == "UnitsLeft":
                should_request = station.units_remaining <= policy_value
            elif policy_name == "PercentLeft":
                threshold = math.floor(policy_value / 100 * cell.lineside_buffer_size)
                should_request = station.units_remaining <= threshold
            else:  # PredictedOut
                lead_time = 2 * math.ceil(cell.distance_meters / min_amr_speed)
                threshold = math.ceil(station.parts_per_unit * lead_time / cell.job_cycle_ticks) + policy_value
                should_request = station.units_remaining <= threshold

            if should_request:
                station.pending_request = True
                request_queue.append(TransportRequest(kind="delivery", cell_name=cell.name,
                                                       station_name=station.name,
                                                       part_name=station.part_name))
                log("part_request", tick, job=job.name, cell=cell.name, station=station.name,
                    part=station.part_name, units_remaining=station.units_remaining, kind="policy")


def run_pickup_requests(cells, jobs_by_name, tick, request_queue, log):
    for cell in cells:
        if cell.job is None or cell.pending_pickup:
            continue
        job = jobs_by_name[cell.job]
        final_unit_in_buffer = (cell.units_completed_at_cell >= job.units and cell.output_buffer_count > 0)
        should_request = (cell.output_buffer_count >= cell.output_buffer_size) or final_unit_in_buffer
        if should_request:
            cell.pending_pickup = True
            request_queue.append(TransportRequest(kind="pickup", cell_name=cell.name))
            log("pickup_request", tick, job=job.name, cell=cell.name,
                output_buffer_count=cell.output_buffer_count)
