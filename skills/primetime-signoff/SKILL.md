---
name: primetime-signoff
description: Review PrimeTime timing validity and closure across modes/corners, constraints, parasitics, setup and hold. Use for routed STA, signoff readiness, timing report diagnosis and ECO verification; report the exact validated scope.
---

# PrimeTime timing validity and closure

Establish the analysis context before interpreting slack. Use the shared [run contract](../eda-qor-experiments/references/run-contract.md) and [evidence checklist](references/evidence.md). The skill name does not imply a design is signoff-ready.

Verify mapped netlist/top, library corners and units, SDC, clocks/generated clocks, mode/case analysis, power intent and extracted parasitics all belong to the same candidate. Check hierarchy/name mapping and parasitic annotation coverage; include intended exclusions explicitly. Never infer full annotation from a successful read_parasitics command.

Derive required scenarios from the project constraints/library qualification, not generic SS-hot/FF-cold defaults. Include setup/hold, recovery/removal, clock-gating and minimum-pulse checks as applicable. Verify the adopted OCV/AOCV/POCV, CPPR and SI method; report unsupported or missing data rather than inventing derates.

Review check_timing and analysis coverage alongside timing summaries. Record worst slack, signed TNS, violating endpoints and coverage separately for each scenario/check. A limited report with no negative paths does not provide numerical worst slack, complete TNS or evidence that all intended paths were checked.

Validate exceptions against the architecture and launch/capture edge relationship. Do not assume every CDC should be false-pathed or every multicycle setup N uses a fixed hold 1. Explain multicycle setup/hold adjustments with the actual clock edges and verify their resulting checks. Do not relax period, uncertainty or I/O budgets as a PPA tuning step.

Classify critical paths by start/end/group, cell/net delay, slew/load/fanout, clock path and common physical cause. Propose targeted fixes to the owning DC/ICC2 stage; then validate the resulting matched netlist/SDC/SPEF across all required scenarios. Keep hold and electrical checks in the loop.

State timing results and remaining verification gaps explicitly. A positive worst slack with missing constraints or RC coverage is not signoff. Power comparisons also require consistent activity and annotation coverage. Deliver evidence paths, accepted/failed checks and ECO guidance; preserve the baseline.
