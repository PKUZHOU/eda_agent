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

本仓库的自动测试只覆盖第一项的部分行为。安装应在用户明确提出后单独执行。

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

[profiles/local.example.json](profiles/local.example.json) 是机器配置字段示例。实际配置可保存在被 Git 忽略的 `profiles/machine.local.json`。技能不会自动连接这些地址或执行配置。

真实 RTL、PDK、标准单元库、license、工具数据库和工程报告应保留在各自工程中。仓库内测试使用人工构造的数据，便于在没有商业工具的环境中运行。

## 方法与来源

参考了 AstroTune 的跨阶段候选保留、HiPilot 的 checkpoint/QoR 工作流和 digital-chip-design-agents 的阶段组织。Dr. RTL 的报告反馈与经验记录方法作为补充；本版范围固定 RTL。具体版本及适配边界见 [sources.md](skills/eda-qor-experiments/references/sources.md)。

当前不包含贝叶斯优化器、AST 检索服务或已经证明有效的调参配置。新增规则应附适用条件、证据和反例；方法说明、流程运行成功与 PPA 改善分别记录。
