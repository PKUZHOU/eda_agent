# Synthesis bottlenecks

| Evidence | Candidate family | Countercheck |
|---|---|---|
| Deep cell chain, little estimated net delay | Mapping/compile effort, selected hierarchy treatment, critical-path priority | Area, formal equivalence, impact on other groups |
| High fanout/transition/capacitance | Legal buffering/replication and physical guidance | Congestion, power, DFT/clock/reset semantics |
| Good DC slack but poor placed/routed slack | Examine clustering, hierarchy, wire assumptions and cell density | Same endpoint/path group and same constraints; physical RC validity |
| Large area with comfortable timing | Area recovery, library/drive mix under fixed period | Hold, electrical rules, leakage and downstream routing |
| Apparent improvement after exception or clock changes | Repair comparison context | New baseline required; not a tuning result |

Do not prescribe retiming or clock-gating changes solely as a speed knob. Check the user's scope, flow equivalence support, scan/reset/power assumptions and latency contract. Reuse documented commands from the actual project or native tool help; do not translate an Innovus/OpenROAD command name by analogy.
