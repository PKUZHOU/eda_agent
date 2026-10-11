# Project environment and tool access

Discover the target project's existing setup before proposing a command. Record the tool executable and actual version, library/technology/RC identities, flow entry points, working directory, available CPU/memory, license availability and competing jobs. Historical tool paths do not prove present availability.

The repository's `profiles/local.example.json` lists useful environment fields. Actual values belong in an ignored `profiles/*.local.json` file or in the user's project. Skills do not automatically load or execute profiles.

When working from this repository, use the optional [CLI executor](../../../docs/executor.md) for an authorized existing-flow run. It provides preflight, detached submission, status, incremental logs, collection, cancellation and checkpoint resume. The helper lives at repository `tools/eda.py`; an individually installed skill must first locate that checkout or use the project's existing runner. Do not assume the helper is installed with the skill.

After a transport failure, query the same run ID before retrying. Resume retains earlier attempts and rejects changed inputs/configuration. Inspect both execution status and result validity; `completed` can still mean a validation failure stopped the pipeline, and an accepted stage without a full normalized manifest is not a comparable QoR sample.

## Remote execution

Use the transport already working for the project. For Windows-hosted VMs accessed through WSL, Windows OpenSSH can be a fallback if direct WSL SSH is unreliable. Inspect existing wrappers, quote paths and arguments, and use unique task/run directories. Avoid embedding credentials in files or logs. A transport problem is separate from an EDA-tool failure.

Honor the user's VM/network policy. If the guest is intended to be offline, obtain public reference material on the host and transfer selected files; do not alter networking as a side effect of tool setup.

Identify the available Python version and tools before invoking helpers. The QoR helper requires only Python 3.6+ and the standard library. If `rg` is missing on a remote host, use available search tools without changing the host merely to perform an audit.

Start with a single heavy EDA process until peak memory and license requirements are measured. Choose a budget for the actual design instead of copying the concurrency or iteration count from a paper.

## Physical/timing prerequisites

Match timing libraries, physical cell/macro views, technology, metal stack and RC setup. Verify SRAM timing/physical views and intentional black boxes. Use qualified project corners; do not transplant a generic voltage/temperature default.

Treat previous smoke runs as connectivity/tool-flow evidence until reports establish the needed physical and timing validity. Extraction initialization failures, zero interconnect-delay fallback, unwaived DRCs and filtered timing reports require review before the run can be used as a final optimization baseline.
