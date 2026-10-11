---
name: icc2-physical-opt
description: Diagnose and optimize ICC2 placement, clock-tree and routing QoR with fixed RTL and stage checkpoints. Use for congestion, physical timing closure, CTS tradeoffs, route DRC and physical implementation experiments.
---

# ICC2 physical optimization

Apply the shared [experiment contract](../eda-qor-experiments/references/run-contract.md); use [stage diagnosis](references/stages.md) to choose the next experiment. Preserve the selected process, metal stack, package/interface constraints and functional RTL.

First establish a valid physical baseline: complete reference libraries and macro physical/timing views, matching technology and RC models, legal site/orientation/rows, floorplan/PG/connectivity, MCMM scenario setup and version-specific settings. Check extraction and parasitic annotation evidence. Missing RC initialization or fallback to zero interconnect delay disqualifies routed-timing comparisons; resolve it before tuning.

Identify the dominant constraint with timing paths and physical evidence. Separate cell-delay problems from net delay, congestion detours, placement displacement and clock effects. Look at regional/layer congestion and macro pin access rather than a single global overflow number.

Create a native design-library/block checkpoint before each branch. Ensure mutable libraries are independent; separate block names can still share mutable library state. Verify restore/reopen before running competing candidates. Record the parent and exact parameter delta. Reuse established place/clock/route commands; validate option names, legal values and availability with native ICC2 help/get_app_options or current project documentation.

Run one stage at a time with logs and explicit completion checks. Review setup/hold across required scenarios, transition/cap/fanout, clock skew/latency, utilization, congestion, route opens/shorts/DRCs and runtime. Early-stage estimates select candidates; final claims need routed extraction and PrimeTime. Keep best candidates per the stated objective without overwriting the baseline.

For CTS and ECO, verify clocks are propagated appropriately, generated/gated clocks are covered, routing/placement legality is maintained, and setup fixes have not broken hold. Verify equivalence after logic-changing physical optimization and synchronize netlist, constraints and parasitics for handoff.

Do not claim foundry DRC/LVS signoff from ICC2 check_routes alone. State which implementation and external signoff checks actually ran, including antenna, connectivity, extraction, SI and variation. Save a reproducible handoff and pass timing validation to `primetime-signoff` when requested.
