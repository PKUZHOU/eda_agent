# Research provenance and adaptation boundaries

These skills and the QoR helper are newly authored for fixed-RTL DC/ICC2/PrimeTime work. Upstream files were inspected as reference material; no upstream runtime, MCP service, orchestrator, or tuning algorithm is installed.

## hipilot

- Repository: https://github.com/qfliuyang/hipilot
- Inspected commit: `3c641fc56abc949eed269df82af9a3596c92f376`
- Default branch when inspected: `dev/environment-setup-7005`

## digital-chip-design-agents

- Repository: https://github.com/hdl-tools/digital-chip-design-agents
- Inspected commit: `38736b15a8aa2cf72b8aef98b0f1047145143441`
- Default branch when inspected: `master`

## DR_RTL

- Repository: https://github.com/hkust-zhiyao/DR_RTL
- Inspected commit: `62b95a57223e8fb187d8b8ec1dcb3d193ef20c6b`
- Default branch when inspected: `main`

## What is reused conceptually

- HiPilot: checkpoint/report/compare workflow. Its MCP/session APIs are not available merely by installing a skill. A session checkpoint must not be assumed to include a restorable EDA design database.
- digital-chip-design-agents: stage boundaries, evidence requirements and retained experience. Generic PVT defaults and fixed multicycle hold recipes are not adopted; scenarios and timing edges must come from the actual project.
- Dr. RTL: report-guided hypothesis and evidence-based experience retention. RTL rewriting is outside this first edition. A signed WNS/TNS baseline-normalized score is not adopted; compare absolute signed deltas and feasibility.
- AstroTune paper: https://jpan.me/files/ISPD26_AstroTune.pdf . DC + Innovus, 45 nm library, 33 parameters across seven stages; final metrics after route optimization. Multi-candidate propagation and context-aware warm starts motivate the experiment workflow. There is no claim that the paper's PPA gains transfer to N7/ICC2.

No Bayesian optimizer or AST retrieval implementation is included. Public repository availability, methodology claims and local behavioral validation are separate kinds of evidence. The local tests validate report handling and comparison invariants; they do not demonstrate an achieved PPA improvement.
