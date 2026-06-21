# Cable Back-End Assembly — Cases 2–5 Performance Analysis

*Last Updated: 2026-06-21*

## Scenario Overview

Five simulation cases study how adding robots to a three-station cable back-end assembly line affects throughput and per-part latency. Each case adds one robot to the previous configuration and measures the impact.

**Stations (in order):**

1. Insert Cable into Port A — Assembler: 8 ticks, Arm: 5 ticks
2. Route and Clip Cable — Assembler: 28 ticks, Arm: 16 ticks *(precision bottleneck)*
3. Insert Cable into Port B — Assembler: 8 ticks, Arm: 5 ticks

**Target:** 20 ticks per operation (i.e., only the Arm meets target for Route and Clip).

**Robot costs:** AMR $40,000 · Stationary Assembler $25,000 · Dexterous Robotic Arm $80,000

---

## Results Table

| Case | Fleet | Parts | Total Ticks | Part CT | Full CT | NVA | Fleet Cost | Robot Util | Station Util |
|------|-------|-------|-------------|---------|---------|-----|------------|------------|--------------|
| Case 2 — Single Assembler | 1 AMR + 1 Assembler | 20 | 1,309 | 44.0 | 244.0 | 200.0 | $65,000 | 68.0% | 22.4% |
| Case 3 — Add Dexterous Arm | + 1 Arm | 20 | 931 | 33.6 | 233.6 | 200.0 | $145,000 | 51.6% | 22.9% |
| Case 4 — Two Assemblers + Arm | + 1 Assembler | 20 | 915 | 38.4 | 238.4 | 200.0 | $170,000 | 39.4% | 23.3% |
| Case 5 — Two Assemblers + Arm + Two AMRs | + 1 AMR | 20 | 769 | 38.4 | 238.4 | 200.0 | $210,000 | 40.0% | 27.7% |

**Metric definitions:**

- **Part Cycle Time (Part CT):** ticks from Station 1 entry (cable removed from Input Buffer) to Output Buffer arrival. Includes inter-station waiting time.
- **Full Cycle Time (Full CT):** Part CT + avg fetch duration + avg deliver duration.
- **Non-Value-Added Time (NVA):** Full CT − Part CT (time spent on fetch and deliver, not assembly).

---

## Case-by-Case Analysis

### Case 2 → Case 3: Add Dexterous Arm (+$80,000)

**What changed:** A Dexterous Robotic Arm is added. The assignment rule routes it to Route and Clip (the only station where the Assembler's 28-tick time exceeds the 20-tick target). The Arm handles routing at 16 ticks; the Assembler alternates between Port A and Port B at 8 ticks each.

**Result:** Total Ticks drops 378 (1,309 → 931, −29%). Part CT drops from 44.0 to 33.6 ticks.

**Why:** Previously the Assembler's 28-tick Route and Clip was the throughput ceiling. The Arm cuts that to 16 ticks and perfectly matches the Assembler's combined Port A + Port B time (8 + 8 = 16), eliminating the bottleneck. This is the highest-impact change in the series.

---

### Case 3 → Case 4: Add Second Assembler (+$25,000)

**What changed:** A second Stationary Assembler is added. Assembler 1 dedicates to Port A, Assembler 2 to Port B, leaving the Arm solely on Route and Clip.

**Result:** Total Ticks drops only 16 (931 → 915, −2%). Part CT *increases* from 33.6 to 38.4 ticks.

**Why the Part CT increase is counterintuitive:** In Case 3, the single Assembler alternates between Port A and Port B. Its combined cycle (8 + 8 = 16 ticks) exactly matches the Arm's 16-tick routing cycle, so cables flow through with no inter-station waiting.

In Case 4, the dedicated Assembler at Port A grabs the next cable the moment Station 1 clears — but Route and Clip is still occupied. The cable sits blocked at Port A for 8 ticks waiting for the Arm. That inter-station wait inflates Part CT by 8 ticks (33.6 → 38.4).

**Why Total Ticks still improves slightly:** In Case 3, the single Assembler occasionally creates brief stalls on the Arm at Route and Clip — when a cable exits Route and Clip and needs Port B exactly as the Assembler is mid-way through Port A for a new cable, the Arm must wait up to 8 ticks for Port B to clear. In Case 4, Assembler 2 is always ready at Port B, so the Arm never stalls. This tighter pipeline recovers roughly one cable-cycle worth of total time (16 ticks).

**The trap:** The second Assembler moves the queue from "robot idle" to "part blocked" without relieving the real bottleneck (the 16-tick Arm at Route and Clip). Adding a robot to a non-bottleneck station does not improve throughput — it only relocates the wait. At $25,000 extra for a 2-tick total improvement and worse per-part latency, this is a poor investment.

---

### Case 4 → Case 5: Add Second AMR (+$40,000)

**What changed:** A second AMR is added. One AMR can fetch from Central Store while the other delivers to the output destination simultaneously.

**Result:** Total Ticks drops 146 (915 → 769, −16%). Part CT unchanged at 38.4. NVA unchanged at 200 ticks.

**Why:** In Case 4, a single AMR must alternate between fetching and delivering — it cannot do both at once. At 100 ticks per trip each way, this serialization becomes the binding constraint at higher throughput levels. Adding a second AMR eliminates the fetch/deliver conflict; both operations run in parallel.

**Why NVA is unchanged:** NVA measures the average non-assembly time *per part* (fetch + deliver). Each cable still requires one 100-tick fetch trip and one 100-tick deliver trip. Adding a second AMR reduces waiting between those trips but does not change the trip durations themselves. NVA stays at 200 ticks across all cases.

---

## Key Takeaways

**Case 3 is the best value.** It delivers the lowest Part CT (33.6 ticks), a 29% throughput improvement over Case 2, and costs $80,000 more — all from targeting the true bottleneck (Route and Clip).

**Adding robots to non-bottleneck stations is wasteful.** Case 4's second Assembler costs $25,000, worsens Part CT, and barely moves total throughput. Always identify and attack the constraint before adding capacity elsewhere.

**NVA is a floor, not a variable.** All four cases show NVA = 200 ticks because fetch and deliver distances are fixed. The only way to reduce NVA is to shorten the distance to Central Store or add AMRs (which reduces waiting between trips, not trip duration).

**The AMR is the hidden constraint at scale.** Case 5 shows the largest absolute throughput gain (−146 ticks) once the assembly robots are fast enough to expose the AMR serialization. At higher parts-to-build targets, the AMR bottleneck would become even more pronounced.
