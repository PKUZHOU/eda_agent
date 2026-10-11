# Timing evidence to collect

Use native tool help to select commands/options supported by the installed PrimeTime release. This is an evidence inventory, not a drop-in Tcl script.

- Tool/version, source netlist/SDC/lib/SPEF identities and units.
- Clock definitions and generated-clock source/edge relationships; propagated/ideal status appropriate to stage.
- Constraints/coverage: missing input/output delays, no-clock endpoints, unconstrained paths, disabled arcs, case analysis, exceptions, untested checks and approved exclusions.
- Extraction: annotation counts, names/hierarchy matches, RC corner/method, coupling/SI treatment and warnings. Match the RC technology to the library/physical stack.
- Per mode/corner: setup and hold minima, authoritative TNS and endpoint counts, path groups and detailed representative paths. Include recovery/removal, gating and pulse width where applicable.
- Methodology: variation/derates, CPPR, SI, waveform modeling, operating conditions and intended voltage/temperature domains.
- ECO: implementation delta, formal result, incremental vs full extraction status and same-candidate timing rerun.

Read report commands in the report header. `-max_paths 5` is diagnostic sampling. `-slack_lesser_than 0` can produce an empty report for passing paths, untested coverage or absent paths; inspect constraints and coverage before interpreting it. Do not replace missing values with zero.
