---
name: eda-qor-experiments
description: Plan and evaluate fixed-RTL commercial EDA optimization experiments across DC, ICC2 and PrimeTime. Use for PPA tuning, QoR comparisons, checkpoint experiments, or retaining optimization experience with report evidence.
---

# EDA QoR experiments

Turn a proposed optimization into a reproducible experiment with a valid baseline, bounded cost, and a decision supported by reports. The default scope fixes RTL and functional/timing requirements. A request to install or review skills does not start an EDA sweep.

## Establish the experiment

Read the project's flow, constraints, latest reports and existing run state. For local or remote execution, read [local-environment.md](references/local-environment.md) and discover the project's actual tool environment. Use [run-contract.md](references/run-contract.md) for comparable manifests and [search-and-learning.md](references/search-and-learning.md) for candidate selection. Source provenance and limitations are in [sources.md](references/sources.md).

Establish the top, RTL/file-list hashes, libraries, physical stack, SDC, modes/corners, extraction and variation settings, tool versions, target clock, objective and resource budget. Resolve missing evidence from the project before asking for it. Do not use guessed PVT values or adopt a new process/library as part of tuning.

Audit report quality before ranking candidates:

Resolve helper paths relative to this skill's installed directory and write outputs into the project's run directory.

```bash
python3 scripts/qor.py audit /path/to/reports --out /path/to/audit.json
```

The helper extracts observations with file/line provenance. Its sampled slack is not certified WNS; it does not infer TNS, unknown power, complete coverage or signoff. Read original reports for a diagnosis.

## Run and decide

- Create a separate run directory and restore a known parent checkpoint. Record the native design database as well as reports; a conversation/MCP session snapshot alone is not a recoverable design checkpoint.
- Preserve the baseline. Record exact Tcl changes, environment, start/end/status, command return code, logs and output hashes. Check tool errors and expected outputs even when the shell exits zero. A crash, timeout, unparsed report or license failure is an invalid sample, not bad PPA.
- Start from a reproducible baseline. For an optimization request without a larger budget, use one pilot and at most two justified candidates, one heavy EDA process at a time until measured memory allows more. Do not start a stage that cannot fit the remaining budget. Report partial stage results honestly.
- Match stage and analysis context when making an A/B claim. A post-place/post-route comparison is useful progression data, not controlled evidence that one setting improved QoR.
- Retain a small feasible Pareto set across stage boundaries. Advance shortlisted DC candidates through the same downstream flow; a synthesis win does not establish routed PPA improvement.
- Compare setup AND hold per required scenario; include cell area, congestion, route DRC/opens, power methodology and runtime where applicable. Do not dilute a failing corner by averaging it with passing corners.
- Keep target period, I/O budgets, exceptions, clock definitions and analysis coverage fixed. Editing false paths, omitting corners or reducing activity does not constitute an optimization win. If a constraint is demonstrably wrong, track its correction as a new baseline and explain why.
- Use signed absolute slack deltas. Do not divide by zero or a negative baseline WNS/TNS to rank candidates. Missing values stay unknown. Compare power only under matching activity, voltage, temperature and analysis method.
- Promote only when equivalence and stage-specific correctness requirements are met. Netlist changes from synthesis/physical optimization still need appropriate equivalence evidence even with identical RTL. Stop a candidate after a structural/library/RC prerequisite fails; repair the prerequisite before further tuning.

Use the stage skills `dc-synthesis-opt`, `icc2-physical-opt` and `primetime-signoff` when their stage is requested. They are bundled with this skill; execution does not require any upstream agent/MCP installation. Validate each Tcl option against the installed tool help and the existing flow before use.

For normalized, provenance-backed manifests:

```bash
python3 scripts/qor.py compare baseline.json candidate.json --out comparison.json
```

The comparator only reports componentwise deltas and a conservative Pareto relation. Its eligibility checks do not replace engineering review or signoff.

End with the tested change, decision, evidence paths, resource cost and limitations. Store successful and failed hypotheses with applicability and confidence; one run is a design-specific observation, not a reusable rule.
