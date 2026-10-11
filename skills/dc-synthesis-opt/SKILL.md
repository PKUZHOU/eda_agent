---
name: dc-synthesis-opt
description: Optimize Synopsys Design Compiler synthesis settings with fixed RTL, measured timing/area and downstream physical feedback. Use for DC QoR tuning, mapping/hierarchy tradeoffs and synthesis experiment planning.
---

# Fixed-RTL Design Compiler optimization

Use the established synthesis flow and the shared [experiment contract](../eda-qor-experiments/references/run-contract.md). Read the [local environment](../eda-qor-experiments/references/local-environment.md) when establishing tool access. RTL, functional latency and design requirements remain fixed unless the user changes scope.

Establish a linked baseline with the exact RTL elaboration configuration, library subset/Vt choices, SDC, topographical/physical mode, hierarchy, DFT/UPF assumptions and tool version. Read check_design/check_timing, unresolved references, black boxes, latch inference and required exceptions before treating timing as meaningful. Distinguish intentional memory macros from unresolved SRAM models.

Read worst setup and hold paths by group and corner. Diagnose logic depth/cell delay, fanout/transition, load, hierarchy boundaries and interconnect assumptions. Use the branch guidance in [diagnosis.md](references/diagnosis.md). Do not replace wire-load estimates with routed timing claims.

For each candidate, record a small Tcl delta supported by installed DC `help`/`man` and the current flow. Candidate families include compile effort, incremental optimization, selective hierarchy/ungroup behavior, critical path grouping, allowed library subset, buffering and area recovery. These are search dimensions, not validated command lines. Preserve constraints and respect dont_touch, DFT, power intent and naming/handoff requirements.

Save DDC, mapped netlist, SDC, equivalence guidance such as SVF where supported, and reports in a unique run directory. Reopen the checkpoint where appropriate and verify exports correspond to the same run. Check formal equivalence when mapping options change sequential transformations or before promoting a candidate. Fixed RTL does not make every netlist transformation automatically validated.

Compare at equal synthesis context using `eda-qor-experiments`. Keep a small Pareto set and run the same physical flow on shortlisted candidates. Report a DC-only improvement as synthesis-only until ICC2 and extracted PrimeTime support the downstream claim. If the physical/RC baseline is invalid, fix that prerequisite before using it to choose a synthesis winner.
