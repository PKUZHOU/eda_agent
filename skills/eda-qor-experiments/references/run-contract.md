# Comparable run contract

Every run has a unique ID, immutable baseline/parent checkpoint, exact parameter delta, objective and budget. Capture source hashes and observed metadata, not directory names that merely look like a corner or stage.

Keep native DC DDC or ICC2 design library/block state, exported netlist/SDC, reports, invocation Tcl, logs, manifest and completion status together. Record SPEF content hashes per run; different routed candidates are expected to have different SPEF. Compare the extraction methodology/corner, not equality of SPEF contents. Verify a checkpoint can be reopened before using it for branches.

## Manifest consumed by `qor.py compare`

JSON fields:

- `run_id`: unique nonempty string; `status`: `completed`.
- `context`: nonempty values for `design`, `rtl_sha256`, `constraints_sha256`, `libraries_sha256`, `physical_technology_sha256`, `rc_method`, `stage`, `tool_versions`, `seed`, `time_unit`, `area_unit`, `scenarios`. These must match exactly across a controlled pair. Use explicit `not_applicable` where warranted and justify it in the run notes. Valid stages: `synthesis`, `placement`, `cts`, `route`, `route_opt`, `signoff`. `scenarios` is the exact list of analyzed mode/corner names.
- `validity`: Boolean `constraints_checked`, `coverage_checked`, `parasitics_checked`; `equivalence` is `pass`, `fail` or `unknown`. True indicates evidence exists for this run/stage; it cannot be populated from a successful tool exit alone.
- `metrics`: numeric `cell_area`; `scenarios` maps every context scenario to numeric `setup_wns`, `setup_tns`, `hold_wns`, `hold_tns`. Slack uses the context time unit, signed TNS is nonpositive. WNS here is the minimum reported slack, which may be positive; do not mix clamped-zero WNS conventions.
- Route/route_opt/signoff metrics also include integer `drc_count`, `open_net_count` and `unconstrained_endpoint_count`. Earlier stages still record unconstrained endpoints and any applicable electrical or physical checks in their evidence.
- Optional `total_power` requires matching `context.power_method`, `context.activity_sha256`, `context.power_unit`. Store voltage, temperature, SAIF hierarchy/window, clock activity and annotation coverage within the power method metadata. Without them power is not comparable.
- `evidence`: nonempty array of objects with `path` and `sha256`, pointing to actual reports. For each metric retain report command, corner, report timestamp and extraction location in the accompanying notes. The comparator checks presence of provenance; it does not certify report contents.

Compute hashes from actual contents; include file-list order and RTL defines/parameters. Library manifests include per-file identities/checksums. Preserve diagnostic logs even for failed runs; they are not eligible numeric observations.

## Review beyond the numeric comparator

A feasible point must meet the user's area/power/timing budgets and stage checks. A dominance result is a metric relation, not proof of feasibility or signoff. Review electrical rules, hold, clock gating, recovery/removal, minimum pulse width, SI/variation, formal status and physical-verification scope as applicable. Unknown/unwaived coverage prevents final acceptance. A reduction from 211 DRCs to 100 is progress but is still not route-clean.

Never estimate TNS by summing `report_timing -max_paths N`: endpoints may repeat and violating endpoints may be omitted. Use an authoritative summary or an exhaustive, deduplicated endpoint analysis with documented semantics.
