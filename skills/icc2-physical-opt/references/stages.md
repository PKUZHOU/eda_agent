# Stage-specific choices

| Stage and evidence | Candidate families | Acceptance evidence |
|---|---|---|
| Floorplan/placement: local density or blocked macro pins | Utilization, placement blockages/padding, legal macro spacing/orientation, pin access | Legality, PG/connectivity, regional congestion, timing across scenarios |
| Placement: long critical nets | Critical-cell placement priorities, buffering/drive mix, fanout treatment | Extracted/estimated RC clearly labeled; compare area and congestion |
| CTS: skew or latency dominates | Legal clock-cell list, tree strategy, routing layers/NDR where supported | Propagated setup and hold; clock power/area, clock DRC and generated clocks |
| Route: shorts/spacing/pin access | Targeted congestion/placement fixes, routing effort and legal layer choices | Final route DRC counts by type, opens, antenna status, timing with valid RC |
| Post-route: net-delay setup violations | Targeted sizing/buffering/placement ECO under legality constraints | Re-extraction, MCMM setup/hold, equivalence and updated checkpoint |

Candidate commands must come from the installed version. In particular, Innovus placement/CTS/routing knobs in AstroTune are not ICC2 flags. Do not modify process rules, select a different metal stack or change SDC exceptions to manufacture a clean metric.

A physical-verification failure should be classified: technology/view mismatch, flow setup, global congestion, local pin access or a specific ECO side effect. Repeating an optimizer with more effort will not repair missing layer mapping or incompatible reference cells.
