# 执行器 v1

`tools/eda.py` 提供 CLI + JSON 接口，调用项目现有的 Tcl 流程。控制端和 Linux worker 都只用 Python 3.6+ 标准库；无需安装 Python 包、MCP 或 skills。读取仓库和运行测试不会启动商业工具。

长任务可另外启动 `python3 tools/eda.py dashboard --profile profiles/machine.local.json`，在本机浏览器监控。这个命令持续提供 HTTP 页面并输出访问地址，遵循 [dashboard.md](dashboard.md)；下文 JSON 请求/退出码约定适用于执行器的其他命令。

## 先运行合成示例

从仓库根目录执行以下配置生成命令。示例只读写人工构造的 checkpoint，不调用 EDA 工具，也不产生 PPA 数据。

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = json.loads(Path('profiles/local.example.json').read_text())
p['project_root'] = str(Path('examples/minimal-flow').resolve())
p['run_root'] = str(Path('runs/demo').resolve())
p['resources']['threads_per_job'] = 1
Path('profiles/demo.local.json').write_text(json.dumps(p, indent=2))
PY
python3 tools/eda.py preflight --profile profiles/demo.local.json --flow flows/minimal.json
python3 tools/eda.py submit --profile profiles/demo.local.json --flow flows/minimal.json --run-id demo-001
python3 tools/eda.py status --profile profiles/demo.local.json --run-id demo-001
python3 tools/eda.py logs --profile profiles/demo.local.json --run-id demo-001 --stage prepare
python3 tools/eda.py collect --profile profiles/demo.local.json --run-id demo-001 --out artifacts/demo-001
```

`submit` 完成输入检查和快照后返回，不等待工具退出。`status` 显示终态后才能 `collect`。省略 `--run-id` 时自动生成 ID；重复提交相同 ID 和配置会返回已有任务。已有失败任务必须显式 `resume`，重复 `submit` 不会重跑。

## 命令约定

每个成功解析的请求输出一个 JSON 对象：`ok`、`command`，以及 `result` 或 `error`。退出码 0 表示请求成功；2 表示配置/请求/预检失败；3 表示通信失败，远端任务状态未知。成功读取一个失败任务的 `status` 仍返回 0，应检查其状态字段。参数用法错误由 argparse 输出帮助到 stderr。

| 命令 | 行为 |
|---|---|
| `preflight --profile P --flow F` | 检查配置、可执行文件、输入指纹、CPU、可用内存和目录；不启动商业工具，不证明 license 可签出 |
| `submit --profile P --flow F [--run-id ID]` | 保存输入和执行器快照，启动脱离 SSH 会话的 worker，返回 ID |
| `status --profile P --run-id ID` | 读取执行状态；worker 丢失时标记 `interrupted` |
| `logs --profile P --run-id ID [--stage S] [--attempt N] [--offset B] [--limit B]` | 增量读取指定阶段日志；返回下一次的字节偏移和当前 EOF。EOF 不代表任务结束 |
| `cancel --profile P --run-id ID` | 请求停止当前 attempt；应随后查询终态。校验 PID、启动时间、boot ID、UID 后清理所属进程组 |
| `resume --profile P --run-id ID [--flow F]` | 在新 attempt 中恢复最后一个已通过原生打开验证的 checkpoint；没有可用 checkpoint 时从第一阶段重跑 |
| `collect --profile P --run-id ID --out DIR [--checkpoints] [--max-bytes N]` | 收集终态任务的配置、状态、日志、已声明输出；默认不下载 checkpoint，默认上限 64 MiB |

控制端超时或断线后，先查询返回的 `run_id`。不要通过生成新 ID 来猜测提交是否成功。`resume` 要求原任务和所属工具进程都已停止；改变输入或配置应提交新任务。传输类型/连接设置不影响执行配置指纹，可换连接路径查询和恢复同一任务。

## 配置与路径

profile 和 flow 均要求 `version: 1`。示例见 [本地 profile](../profiles/local.example.json)、[SSH profile](../profiles/ssh.example.json) 和 [商业流程适配清单](../flows/dc-icc2-pt.example.json)。后者是一份待接入项目 Tcl 的字段示例，不能直接替代项目 flow。

### Profile

- `project_root` / `run_root`：执行主机上的绝对路径。profile 文件本身由控制端读取。所有运行使用同一 `run_root` 才共享并发限制。
- `transport.type`：`local`、`ssh`、`windows_ssh`。远端执行主机必须是 Linux；SSH 沿用用户现有密钥和 known_hosts。
- `transport.host`：`user@host`；可设 `port`、`identity_file`、`python`、`request_timeout_seconds`。默认请求超时 120 秒；输入指纹计算超过此时间时可显式增大，最大 3600 秒。
- `transport.ssh_command`：可覆盖 SSH 程序的 argv 前缀。`windows_ssh` 在 WSL 下默认调用 Windows OpenSSH；`identity_file` 此时使用 Windows 客户端能够识别的路径。WSL 互通本身须正常，执行器不会修改路由、防火墙或虚拟机网络。
- `tools`：`dc_shell`、`icc2_shell`、`pt_shell` 对应已安装可执行文件的绝对路径。许可证环境可由项目 launcher 初始化。
- `env`：显式字符串环境变量，覆盖 worker 继承的登录环境。此配置被写入私有运行记录，避免在这里放密码或访问令牌。
- `resources.max_concurrent_heavy_jobs`：v1 固定支持 1；`threads_per_job` 默认 4，通过 `EDA_THREADS` 传给项目 adapter。
- `min_free_memory_gib`：提交和取得运行槽时检查；`memory_limit_gib` 可选，按约 0.1 秒间隔采样所属进程组 RSS，超限停止。RSS 求和会重复计算共享页，不是 cgroup 硬限制，也不是整机峰值。

### Flow

- `isolation: "reviewed_run_directory"`：表示项目 adapter 已检查过输出路径。运行目录本身不能约束 Tcl 中的绝对写路径；这是受信任项目代码的执行器，没有文件系统沙箱。
- `inputs`：`source` 是相对 `project_root` 或绝对的执行端路径；`destination` 是工作目录中的相对路径。输入复制并计算 SHA256；不接受符号链接、特殊文件和重叠目标。原始工程不会被作为 cwd。
- `external_inputs`：需要固定身份的只读库、技术文件、RC 表等路径。只计算指纹，不复制；提交和开始/恢复时检查。优先列出实际使用的文件，避免每次遍历整个 PDK。未声明的外部依赖不在完整性检查范围内；此字段不强制操作系统只读权限。
- `budget_seconds`：每个 attempt 的墙钟执行预算，包含工作目录准备、阶段、验证和恢复探测，不包含排队和提交时的输入快照。运行中通过 deadline 截断工具；文件拷贝/哈希不是可抢占操作，可能超出 deadline 后才返回。恢复是新的 attempt，重置这个预算。
- `stages`：按顺序执行；每项包括 `id`、`tool`、`argv`、`timeout_seconds`、`success_pattern`、`outputs`。`tool` 为 `command` 或三个商业工具名。
- `argv` 直接执行，不经 shell 拼接。完整参数 `{tool:dc_shell}` 等替换成已配置工具；`{python}` 和 `{run_dir}` 可用于参数内替换。若需 csh 环境，可声明 `[/bin/csh, -f, scripts/launch.csh, {tool:dc_shell}, scripts/synthesis.tcl]`。
- `minimum_start_seconds` 可声明阶段启动所需的最少剩余预算；不足时不启动。默认 0.1 秒，实际工程应按历史耗时设置，并保留报告/恢复验证余量。
- `cwd` 默认工作目录，可指定其中的相对子目录；输出路径始终相对工作目录根。
- `success_pattern` 是多行模式的正则；`error_patterns` 可添加项目错误模式。默认识别常见 `Error:`、`Fatal:`、VCS/UVM 错误和 Python traceback。未知格式需项目补充，不能只依赖进程返回 0。
- `outputs` 中的 `kind` 为 `report`、`checkpoint`、`artifact`。所有声明输出必须存在、新鲜且默认非空；`nonempty: false` 可允许明确合法的空文件。每阶段保存独立输出快照，后续阶段覆盖工作文件不会改写历史结果。
- `checkpoint.paths`：恢复下一阶段所需的全部文件/目录。不要只列数据库而遗漏后续所需网表、SDC 或 SPEF。路径不得重叠。`restore_probe` 使用独立工作副本，要求原生工具成功重新打开数据库并输出指定 marker；仅文件存在不算验证。
- `qor_manifest`：可选，必须也是本阶段声明的新鲜输出。按 [run-contract](../skills/eda-qor-experiments/references/run-contract.md) 编写；`evidence.path` 相对工作目录，SHA256 要匹配实际证据。适配器负责产生完整、准确的数据，执行器不从有限 timing report 猜测 WNS/TNS。

## DC / ICC2 / PrimeTime 接入

沿用项目确认可用的 Tcl，在私有副本中把输出写到当前运行目录。工具入口、库、约束和 RC 设置都来自项目。下面是 adapter 的职责，具体命令以安装版本的 help 和项目 flow 为准：

| 阶段 | 主流程输出 | 原生恢复探测 |
|---|---|---|
| DC | 映射 DDC、网表、SDC、面积与 setup/hold/设计检查报告 | `read_ddc` 后选择顶层、link，检查设计对象存在 |
| ICC2 | 保存的 NDM/block、路由网表与 SDC、匹配 RC 的 SPEF、物理和时序报告 | `open_lib` / `open_block`，核对顶层与设计对象 |
| PrimeTime | 按项目场景生成 setup/hold 与覆盖报告，保存 session | `restore_session`，核对设计、场景和约束 |

适配器需应用 `EDA_THREADS`，例如项目已支持的 `set_host_options -max_cores $env(EDA_THREADS)`。不要把示例 marker 加在失败也会经过的无条件尾部；先检查本阶段必要条件，再打印 marker。工具版本以本次日志或项目版本记录为准，可执行文件存在不证明版本/授权可用。

跨主机恢复原生数据库的能力取决于工具版本、库和数据库中的路径。本版验证同一执行主机、相同输入配置下的恢复。工具自行 daemonize 到新 session 的后代不属于当前进程组；项目 launcher 不应这样启动 EDA 工具。

## 状态和证据

| 字段 | 含义 |
|---|---|
| `status` | `queued`、`running`、`completed`、`failed`、`timed_out`、`cancelled`、`interrupted`；`completed` 表示已运行命令正常退出，也可能因验证问题停止后续阶段 |
| `pipeline_complete` | 所有声明阶段和恢复探测是否通过；验证阻断时为 false |
| `result_validity` | `valid` 只表示声明的阶段验收条件通过；`invalid` 表示证据明确失败；`insufficient` 表示证据不足或任务未完整执行 |
| `stages[].execution` | 实际 argv/cwd、退出码、耗时、所属进程组采样峰值和日志位置 |
| `stages[].validation` | 新鲜输出指纹、报告观察、具体阻断原因和 QoR manifest 检查结果 |
| `qor_comparable` | 最终阶段有通过结构/证据检查的规范化 manifest 才为 true；两次实验仍须由 `qor.py compare` 检查上下文一致性 |

非零退出、错误日志、缺失/旧输出、已识别的非零 DRC/opens、寄生参数失败会阻断下游。有限路径报告会记录限制，不能证明完整 WNS/TNS。缺少 normalized manifest 时，声明的流程检查可以通过，但 `qor_comparable` 保持 false。任何一项都不能自动证明 signoff 或 PPA 改善。

运行目录保留 `request.json`、原始输入快照、`events.jsonl`、顶层 `state.json` 和各 attempt 的状态、工具日志、独立工作目录、输出快照、checkpoint 及恢复探测日志。文件状态通过同目录临时文件 + fsync + replace 更新；本版不提供数据库级断电事务。

`collect` 只打包声明输出和运行元数据，检查路径、文件类型、大小及 SHA256；控制端不执行 tar 中的链接，拒绝已有目标目录。失败阶段的声明报告也作为诊断材料收集，但不标记为有效结果。配置、实际报告和数据库都是私有产物，不应提交到公开仓库。

## 验收与后续工作

公共测试使用人工工具覆盖断线后的后台继续执行、重复提交、单任务排队、非零/伪成功退出、旧报告、超时/取消及进程组回收、checkpoint 探测与恢复、配置/输入变更拒绝、worker 丢失和收集完整性。运行方式：

```bash
python3 tools/validate_skills.py
python3 -m unittest discover -s tests -v
```

真实工具验收的范围和限制见 [validation.md](validation.md)。后续先补齐项目 RC/物理有效性和场景报告归一化，再做固定输入的受控 A/B；搜索器、调参空间和经验检索尚未实现。
