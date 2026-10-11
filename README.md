# eda_agent

用于固定 RTL 的商业 EDA 优化候选 skills，面向 **Design Compiler → ICC2 → PrimeTime**。

当前状态：**候选、默认不安装，尚未验证真实设计上的 PPA 收益。** 克隆仓库、运行测试或 CI 都不会安装 skills、修改代理配置或启动 EDA 工具。

## Skills

| Skill | 作用 |
|---|---|
| [eda-qor-experiments](skills/eda-qor-experiments/SKILL.md) | 实验计划、checkpoint、报告审计、QoR 比较和经验记录 |
| [dc-synthesis-opt](skills/dc-synthesis-opt/SKILL.md) | 固定 RTL 的综合设置、映射、层次结构和面积/时序优化 |
| [icc2-physical-opt](skills/icc2-physical-opt/SKILL.md) | placement、CTS、routing、拥塞和物理优化 |
| [primetime-signoff](skills/primetime-signoff/SKILL.md) | 约束、寄生参数、MCMM 时序有效性与 ECO 复核 |

技能说明与报告工具可独立检查。它们不依赖上游项目的 MCP 服务或多代理框架；真正执行 EDA 时需要用户自己的工具、工程、库和受支持的 Tcl 流程。

## 在安装前验证

在一个独立实验目录中，明确让助手读取所需 `SKILL.md`，针对指定工程执行一次有预算的对照实验即可。无需先安装到全局目录。

建议依次检查：

1. **报告与脚本行为**：缺失值保持未知，有限路径报告不冒充完整 WNS/TNS，不同约束/工艺角不混比。
2. **真实流程可运行性**：使用匹配的工具版本、库、约束、物理视图和 RC 数据；checkpoint 能恢复。
3. **优化收益**：在固定口径下比较候选，经过等价检查和必要的完整 P&R/PrimeTime 复核，并保存失败实验。

自动测试覆盖报告检查和执行器的故障/恢复行为；真实工具验收范围见 [validation.md](docs/validation.md)。安装应在用户明确提出后单独执行。

## 执行现有工程

新增 [CLI 执行器](docs/executor.md)：`preflight / submit / status / logs / collect / cancel / resume`，支持 Linux 本地、SSH、WSL 调用 Windows OpenSSH。后台 worker 在 SSH 断线后继续运行；每个运行根目录同一时间只执行一个重任务，保存输入指纹、阶段输出和经过原生恢复探测的 checkpoint。

先用 [纯模拟示例](flows/minimal.json) 验证接口；商业流程按 [DC → ICC2 → PrimeTime 清单](flows/dc-icc2-pt.example.json) 接入已有 Tcl。工作目录隔离需要检查项目脚本的输出路径。执行状态、报告有效性和 QoR 可比性分别记录，失败阶段会阻断下游。

## 本地检查

Python 3.6+，只使用标准库：

```bash
python3 tools/validate_skills.py
python3 -m unittest discover -s tests -v
```

报告审计：

```bash
python3 skills/eda-qor-experiments/scripts/qor.py audit /path/to/reports --out /path/to/run/audit.json
```

审计结果是带文件和行号的观察记录，不能自动证明时序覆盖完整或设计达到 signoff。日志中的中间阶段错误还需结合最终阶段报告判断。

QoR 对比：按 [run-contract.md](skills/eda-qor-experiments/references/run-contract.md) 准备来自真实报告的两个 manifest，然后执行：

```bash
python3 skills/eda-qor-experiments/scripts/qor.py compare baseline.json candidate.json --out comparison.json
```

脚本输出差值和 Pareto 关系；它不会自动确认报告内容、预算合规或 signoff。跨阶段变化可以作为进度记录，受控调参对照需要匹配阶段和分析口径。

## 环境与数据

[profiles/local.example.json](profiles/local.example.json) 和 [SSH 配置](profiles/ssh.example.json) 是执行器 v1 的字段示例，需要填写实际执行端路径。真实配置保存在被 Git 忽略的 `profiles/machine.local.json`。只有显式调用执行器才会读取配置并连接。

真实 RTL、PDK、标准单元库、license、工具数据库和工程报告应保留在各自工程中。仓库内测试使用人工构造的数据，便于在没有商业工具的环境中运行。

## 方法与来源

感谢以下项目和论文提供的方法与工作流参考。这里按具体借鉴内容说明来源；各项目的实验结果属于各自的工具、工艺和设计条件，本仓库的优化效果需要独立验证。

| 参考来源 | 借鉴内容 | 本仓库中的体现与当前状态 |
|---|---|---|
| **[AstroTune](https://jpan.me/files/ISPD26_AstroTune.pdf)**，ISPD 2026 | 从相似设计经验形成起点；分阶段保留、向后传递并淘汰多个候选 | 写入 `eda-qor-experiments` 的实验设计与候选筛选指导；AST 检索和贝叶斯优化器尚未实现。论文使用 DC＋Innovus，其参数需要针对 ICC2 重新核实。 |
| **[HiPilot](https://github.com/qfliuyang/hipilot)** | 工具执行、checkpoint、报告收集和 QoR 对比的工作流 | 用于组织实验记录、恢复点和指标比较；本仓库的辅助脚本独立编写，上游 MCP 服务与执行器未集成。 |
| **[digital-chip-design-agents](https://github.com/hdl-tools/digital-chip-design-agents)** | 综合、物理设计和 STA 的阶段组织、检查项与经验记录 | 参考其职责划分，形成 DC、ICC2、PrimeTime 三个阶段技能；工艺角、约束和 Tcl 命令要求以实际工程为准。 |
| **[Dr. RTL](https://github.com/hkust-zhiyao/DR_RTL)** | 根据时序报告提出优化假设，用工具验证结果，并从实验中提炼经验 | 用于报告反馈与经验记录指导；本版固定 RTL，RTL 重写及其搜索流程不在当前实现范围内。 |

### 论文引用

1. Runzhi Wang, Jingyu Pan, Yiran Chen, Jiang Hu. **AstroTune: AST-Assisted LLM Retrieval for Cross-Stage Design Flow Parameter Tuner.** ISPD 2026. [论文 PDF](https://jpan.me/files/ISPD26_AstroTune.pdf) · [DOI: 10.1145/3764386.3779579](https://doi.org/10.1145/3764386.3779579)。
2. Wenji Fang et al. **Dr. RTL: Autonomous Agentic RTL Optimization through Tool-Grounded Self-Improvement.** 2026. [arXiv:2604.14989v2](https://arxiv.org/abs/2604.14989v2)。

### 版本与适配记录

参考仓库固定到核查时的提交，具体 skill 文件、提交链接和适配边界见 [sources.md](skills/eda-qor-experiments/references/sources.md)。后续若新增参考或实际移植代码，应同时记录对应来源、版本和改动；移植代码需保留适用的原始署名与许可信息。

当前实现包括候选技能、现有 Tcl 流程执行器、报告审计和可比条件下的 QoR 差值计算。跨阶段搜索、经验学习等内容目前属于流程指导，尚未通过真实设计证明 PPA 收益。新增规则应附适用条件、证据和反例；方法说明、流程运行成功与 PPA 改善分别记录。
