# Research provenance and adaptation boundaries

These skills and the QoR helper are newly authored for fixed-RTL DC/ICC2/PrimeTime work. Upstream files were inspected as reference material; no upstream runtime, MCP service, orchestrator, or tuning algorithm is installed.

## HiPilot

- Repository: https://github.com/qfliuyang/hipilot
- Inspected commit: [`3c641fc`](https://github.com/qfliuyang/hipilot/commit/3c641fc56abc949eed269df82af9a3596c92f376)
- Referenced files: [Synthesis skill](https://github.com/qfliuyang/hipilot/blob/3c641fc56abc949eed269df82af9a3596c92f376/skills/synthesis.md), [QoR comparison skill](https://github.com/qfliuyang/hipilot/blob/3c641fc56abc949eed269df82af9a3596c92f376/skills/compare-qor.md), [Checkpoint skill](https://github.com/qfliuyang/hipilot/blob/3c641fc56abc949eed269df82af9a3596c92f376/skills/create-checkpoint.md)
- Default branch when inspected: `dev/environment-setup-7005`

## digital-chip-design-agents

- Repository: https://github.com/hdl-tools/digital-chip-design-agents
- Inspected commit: [`38736b1`](https://github.com/hdl-tools/digital-chip-design-agents/commit/38736b15a8aa2cf72b8aef98b0f1047145143441)
- Referenced files: [Logic synthesis skill](https://github.com/hdl-tools/digital-chip-design-agents/blob/38736b15a8aa2cf72b8aef98b0f1047145143441/plugins/synthesis/skills/logic-synthesis/SKILL.md), [Physical design skill](https://github.com/hdl-tools/digital-chip-design-agents/blob/38736b15a8aa2cf72b8aef98b0f1047145143441/plugins/pd/skills/physical-design/SKILL.md), [STA skill](https://github.com/hdl-tools/digital-chip-design-agents/blob/38736b15a8aa2cf72b8aef98b0f1047145143441/plugins/sta/skills/sta/SKILL.md)
- Default branch when inspected: `master`

## Dr. RTL

- Repository: https://github.com/hkust-zhiyao/DR_RTL
- Inspected commit: [`62b95a5`](https://github.com/hkust-zhiyao/DR_RTL/commit/62b95a57223e8fb187d8b8ec1dcb3d193ef20c6b)
- Referenced files: [RTL optimization skill library](https://github.com/hkust-zhiyao/DR_RTL/blob/62b95a57223e8fb187d8b8ec1dcb3d193ef20c6b/.claude/skill/rtl-opt/skill.md)
- Default branch when inspected: `main`

## Paper references

- AstroTune, ISPD 2026: [paper PDF](https://jpan.me/files/ISPD26_AstroTune.pdf), [DOI](https://doi.org/10.1145/3764386.3779579). Consult sections 5–6 for the method and the DC/Innovus evaluation context.
- Dr. RTL, 2026: [arXiv:2604.14989v2](https://arxiv.org/abs/2604.14989v2). Its RTL optimization and tool-feedback loop provide background for retained experience; RTL rewriting is outside this repository's current scope.
- Full bibliographic entries and the source-to-feature mapping are in the [repository README](../../../README.md#方法与来源).

## What is reused conceptually

- HiPilot: checkpoint/report/compare workflow. Its MCP/session APIs are not available merely by installing a skill. A session checkpoint must not be assumed to include a restorable EDA design database.
- digital-chip-design-agents: stage boundaries, evidence requirements and retained experience. Generic PVT defaults and fixed multicycle hold recipes are not adopted; scenarios and timing edges must come from the actual project.
- Dr. RTL: report-guided hypothesis and evidence-based experience retention. RTL rewriting is outside this first edition. A signed WNS/TNS baseline-normalized score is not adopted; compare absolute signed deltas and feasibility.
- AstroTune paper: https://jpan.me/files/ISPD26_AstroTune.pdf . DC + Innovus, 45 nm library, 33 parameters across seven stages; final metrics after route optimization. Multi-candidate propagation and context-aware warm starts motivate the experiment workflow. There is no claim that the paper's PPA gains transfer to N7/ICC2.

No Bayesian optimizer or AST retrieval implementation is included. Public repository availability, methodology claims and local behavioral validation are separate kinds of evidence. The local tests validate report handling and comparison invariants; they do not demonstrate an achieved PPA improvement.

## Attribution maintenance

When adding a source, record the exact referenced paper/version or repository commit and the concrete decision it informs. Distinguish conceptual inspiration from implemented algorithms or imported code. Any future code import must retain applicable upstream attribution/license notices and document local modifications. Upstream benchmark gains are not evidence of gains from these candidate skills.
