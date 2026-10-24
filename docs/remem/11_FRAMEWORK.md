# ReMem 核心框架实现与边界

更新：2026-10-24。用户选择方案 2：有限范围的策略接口重构，继续共用上游 trainer。
本阶段完成环境和离线开发基础，不声明模型效果或正式实验就绪。

## 结构与调用链

| 文件 | 职责 |
|---|---|
| `skillopt/remem/types.py` | FailureEvent、FailureCase、RepairAttempt；提案/记忆/门控协议 |
| `store.py` | SQLite 不可变事件、内容寻址工件、幂等写入和可重建版本状态 |
| `evidence.py` | 训练来源、可见事件、精确引文、版本与规则 sidecar 校验 |
| `proposals.py`、`prompts/` | R1 结构化修复与 R0 有界自由编辑策略，明确 no_change/格式错误 |
| `budget.py` | 去重、重叠锚点冲突分离、编辑上限及审计原因 |
| `context.py` | M0 空历史策略；M1 同任务未解决问题与实际历史编辑检索 |
| `evaluation.py` | 对齐逐题 ID 的配对 bootstrap 三路门控 |
| `runtime.py` | 策略组合、失败先落盘、缓存/预算/恢复/尝试生命周期 |
| `study.py` | 开发版 prepare/verify/run/report 生命周期 |
| `skillopt/engine/trainer.py` | 保留共享执行、候选评估、采用与输出流程，通过策略调用替换相关阶段 |

调用顺序为：固定任务批次 → 执行 → 有效性分类与训练事件持久化 → M 上下文 →
提案策略 → 来源校验/去重/冲突处理 → 候选 → 选择集配对门控 → RepairAttempt → 事务检查点。

关闭整个 ReMem 时继续使用原反思、合并、排序、应用和门控函数。核心四组启用同一
ReMem 基础设施，仅切换 `repair` 和 `memory`。M0 的审计记录仍然存在，但历史策略
不读它们；上游 step_buffer 不进入核心组提案输入。

R0 使用上游 append/insert_after/replace/delete 词汇的统一自由编辑提示词，
不是原版 SkillOpt 的全部多阶段反思流程。外部 `skillopt_controlled` 仍须独立完成。
R1 依赖真实失败事件及精确轨迹引文，但通过校验仅证明来源与结构一致；诊断语义始终
标为 unverified。组合评估只归因到 update_bundle。

M1 当前只检索同任务历史，按重现次数和最近观测排序；不进行跨任务语义检索。
每组保留最多两次修复的具体编辑和采用结果，历史上下文上限 12,000 字符。
长轨迹会截断并标记，缺少可用引文则返回空，不填充无关内容。
状态按当前 skill 哈希重建：未观测的新版本不会继承“已解决”；只有采用版本的
实际训练成功能标记 resolved_observed。冷却/deferred 调度尚未实施。

## 持久化与失败处理

运行目录下 `remem/ledger.sqlite3` 保存事件和工件。相同 event ID 的同内容写入幂等；
同 ID 不同内容报错。所有有效训练失败在生成提案前提交；混合批次中出现基础设施
故障时，也先保存其他有效失败再停止。

完整阶段结果缓存绑定运行配置指纹、skill、任务、阶段与 draw。已有结果可恢复；
已开始但未完成的执行必须先核对实际调用，不自动重跑并当成免费调用。
ReMem 的事务检查点保存当前/best skill、分数与历史，恢复不依赖可能半写的 JSON 文件。

逻辑优化器调用、计划执行次数、缓存与耗时已记录；HTTP 实际尝试次数及完整 target
usage 尚未接入，缺失记 null。不能用现有上游 token 汇总替代正式成本审计。
模型重试与后端响应身份核查属于下一阶段。当前 runner 不提供正式运行模式。

## 使用命令

在仓库根目录执行，PowerShell 包装器固定 `.venv` 与 UTF-8，不修改全局环境：

```powershell
.\scripts\remem\python.ps1 scripts/remem/verify_environment.py
.\scripts\remem\python.ps1 -m pytest tests/remem -q
.\scripts\remem\python.ps1 scripts/remem/study.py prepare foundation-v1
.\scripts\remem\python.ps1 scripts/remem/study.py verify outputs/remem/foundation-v1
.\scripts\remem\python.ps1 scripts/remem/study.py run outputs/remem/foundation-v1 --name core_00_42
.\scripts\remem\python.ps1 scripts/remem/study.py report outputs/remem/foundation-v1
```

以上命令不调用模型。`run` 默认只验证和显示 not_started；将来显式增加 `--execute`
才调用模型，且仍只是 development run。当前没有配置真实凭据，也没有执行此选项。

prepare 生成四个核心方法×三个种子的配置。每 seed 的前四步覆盖 80 题，后两步固定
重现 40 题；方法间共享完全相同的任务顺序。冻结包包含全部研究源码、prompt、解析后
配置、任务计划、数据哈希与实际环境版本，拒绝覆盖已有 study；verify 拒绝源文件、
文件清单、prompt、配置、环境或数据变化。修改代码后需要新的 study ID。

report 只读已有工件，不重新评估、不调用模型，也不把缺失指标填成零。
源码快照和数据只存忽略目录，Git 提交代码、配置模板、依赖快照与说明。

## 正式实验前仍需完成

1. 训练数据准备样例上的模型探活：身份、接口契约、空响应、超时、费用、吞吐与输出上限。
2. 实际 HTTP 尝试/重试/缓存与 target token 的统一审计，确定完整恢复与限流政策。
3. 旧测试暴露 ID 并集及来源/模板跨集合审计；不能把上游 280 题池直接称为干净最终测试集。
4. SkillOpt controlled、CAM、AtomSearch 对照实现及预算适配；目前显式标为 planned。
5. 依校准冻结正式 18/21 格协议；全部最终 skill 固定后的统一测试发布和正式统计报告。

没有迁移 CAM 源代码；现阶段配对门控等代码为本项目新实现。CAM 参考目录保持只读。
