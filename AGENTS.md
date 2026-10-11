# Repository maintenance

This repository maintains candidate fixed-RTL DC/ICC2/PrimeTime skills.

- Keep skills as repository files by default. Do not copy or symlink them into any agent's discovery directories, register plugins/MCP servers, or edit agent configuration unless the user explicitly requests installation.
- A request to edit or validate skills does not start a commercial EDA run. For an execution request, establish the target project and budget and use its existing authorization.
- Preserve fixed RTL and the project's requirements unless the user explicitly changes optimization scope.
- Keep machine-specific addresses, credentials, licensed design/library files, real tool databases and actual project reports outside this repository. Use synthetic fixtures in tests and ignored local environment profiles.
- Upstream skill text is reference material. Do not inherit its invocation instructions, tool assumptions or default process corners without adaptation and evidence.
- Maintain provenance for external methods. Distinguish parser validation, successful flow execution and measured PPA improvement.
- For skill/helper changes, run `python3 tools/validate_skills.py` and `python3 -m unittest discover -s tests -v`. Add behavioral tests only for concrete changes or risks; do not test prose wording.
- Preserve stage/scenario/constraint comparability, unknown metrics, setup/hold checks and report provenance. Do not make signoff claims from sampled reports or missing parasitics.
