# 执行器 v1 验收记录

日期：2026-10-11。skills 仍为 candidate，默认不安装；本次验收不包含调参搜索、PPA 改善或 signoff。

## 公共自动测试

27 项 unittest：原有 9 项 QoR 测试，以及 18 项执行器测试。所有工具调用均使用人工程序，CI 不需要商业 license、PDK 或用户设计。

已覆盖的具体行为：

- 后台执行、增量日志、声明输出收集及哈希校验。
- SSH 请求已抵达执行端但连接返回失败，任务仍继续；重复提交同一 ID 不重复启动。
- 单任务排队、排队取消、超时/预算/采样内存限制和子进程组回收。
- 非零退出、返回 0 的错误、缺失完成标记、缺失/旧输出、DRC/RC 问题均阻断后续阶段。
- checkpoint 原生探测的模拟、探测失败、新 attempt 恢复、历史 attempt 保留、输入/配置/checkpoint 变更拒绝。
- worker 意外结束被识别为 interrupted；残留工具组阻止同运行根目录的新重任务，须先取消。
- 输出快照不受后续工作文件覆盖影响；QoR manifest 必须对应真实证据哈希。

另执行了文档中的完整模拟 CLI 示例，包括预检、提交、状态和收集；执行器及辅助代码通过 Python 3.6 语法检查。

## 私有 VM 集成

验证了 Linux worker 和 Windows OpenSSH 传输适配；任务在 SSH 命令返回后独立完成。机器配置、连接地址和本地路径不在公开记录中。

使用已有 counter 工程的独立脚本副本，沿用固定 RTL、原有库和约束。实际环境路径、输入、原生数据库、配置和报告保存在私有运行目录，未加入 Git。原工程不作为运行 cwd。

| 验收项 | 结果与边界 |
|---|---|
| DC 综合 | 命令、声明输出和映射检查通过；DDC 在独立目录重新打开、link 和对象检查通过 |
| ICC2 placement / routing | 工具正常返回并生成结果；最终报告含非零 DRC 和无有效寄生参数/零互连延迟，结果标为 invalid，下游自动停止 |
| 恢复测试 | 在 DC 后注入一次明确的非零退出；第二 attempt 从经过验证的 DC checkpoint 继续，DC 记录仍指向第一 attempt，没有重复综合 |
| PrimeTime | 恢复测试继续执行综合后网表 STA，保存 session 并在独立目录恢复，通过；未当作布线后 extracted STA |
| 结果收集 | 通过 SSH 收集声明产物和运行记录，控制端校验文件清单与 SHA256；数据只保留在忽略目录 |

集成在预定预算内完成。恢复测试最初暴露了测试 adapter 没有创建报告目录的问题；修正 adapter 后使用新 run ID 重跑，旧失败记录保留，未用修改输入的方式继续旧任务。

最终恢复测试为 `completed`、`pipeline_complete: true`、声明条件的 `result_validity: valid`，但 `qor_comparable: false`：本次未提供完整场景和等价性证据的规范化 manifest。ICC2 的原生 checkpoint 恢复探测因前置物理验收失败而未执行，不能据此声称其恢复已通过。

## 下一步

先修复并验证项目的物理规则/RC 提取配置，建立可复跑的 routed baseline；随后接入完整场景、setup/hold、约束覆盖、等价性和匹配活动率的报告归一化。只有形成可比 baseline 后，才评估固定 RTL 下的受控 A/B 和分阶段搜索收益。
