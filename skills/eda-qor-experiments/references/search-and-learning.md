# Candidate selection and retained experience

Start with the measured bottleneck and a constrained hypothesis. Record the expected affected path group, cost in area/power/runtime, exact knob and permitted values, native help evidence, parent checkpoint and rejection criteria. Change a small interpretable set of knobs before adding a search optimizer.

Across synthesis, placement, CTS and routing, retain several nondominated candidates when affordable. Preserve complete parameter lineage: a later-stage experiment inherits an identified earlier-stage configuration and checkpoint. Compare intermediate results only with the same-stage baseline. Spend complete P&R/PrimeTime work on shortlisted candidates.

AstroTune motivates warm starts from similar designs and propagation of multiple candidates across stages. In this package those are workflow recommendations, not an implemented Bayesian optimizer or AST retrieval service. A future search adapter must only sample a version-verified parameter space, record failed/timeout runs separately, honor walltime/memory/license budgets and resume idempotently.

Similarity should include architecture, critical-path structure, hierarchy, macro use, utilization, process/library/RC and tool version. A fast adder optimization from another process is a hypothesis, not a known win for this design.

Write one experience object per run with design/context fingerprints, baseline/candidate IDs, hypothesis, exact parameter delta, stage/corner results, correctness checks, runtime, outcome and evidence paths. Keep negative results. Distill a reusable rule only after independent reproduction under stated conditions. Record exclusions and confidence; do not turn a single tool error into a permanent global prohibition.

For timing-constrained PPA, first retain feasibility, then compare area/power/runtime tradeoffs. Do not reuse a signed-baseline normalized WNS/TNS score without checking its direction and zero behavior. Small improvements near report rounding require higher precision or repeated matched runs, not exaggerated percentages.
