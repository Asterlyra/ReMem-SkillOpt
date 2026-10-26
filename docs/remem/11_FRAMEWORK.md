# ReMem 核心框架实现与边界

更新：2026-10-26。用户选择方案 2：有限范围的策略接口重构，继续共用上游 trainer。
本阶段完成环境、离线开发基础和 DeepSeek 小样本探活，不声明方法效果或正式实验就绪。

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

逻辑优化器调用、计划执行次数、缓存与耗时已记录。OpenAI-compatible 路径现在
逐请求记录 HTTP 尝试、状态、调用关联、响应模型标识和 usage；失败请求或缺失用量
使总 token 保持 null，同时保留已知部分。其他后端尚未获得同等覆盖，不能用上游
token 汇总替代正式成本审计。当前 runner 不提供正式运行模式。

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

以上命令不调用模型。`run` 默认只验证和显示 not_started；显式指定 `--execute`
才调用模型，且仍只是 development run。密钥仅存在受 Git 忽略的本地文件，
三个小样本探活已经运行，完整优化矩阵未执行。

prepare 生成四个核心方法×三个种子的配置。每 seed 的前四步覆盖 80 题，后两步固定
重现 40 题；方法间共享完全相同的任务顺序。冻结包包含全部研究源码、prompt、解析后
配置、任务计划、数据哈希与实际环境版本，拒绝覆盖已有 study；verify 拒绝源文件、
文件清单、prompt、配置、环境或数据变化。修改代码后需要新的 study ID。

report 只读已有工件，不重新评估、不调用模型，也不把缺失指标填成零。
源码快照和数据只存忽略目录，Git 提交代码、配置模板、依赖快照与说明。

2026-10-24 增加 `deepseek-development.yaml`、候选新测试池及原生 SkillOpt 对照。
DeepSeek 的 12 核心组加 3 对照配置可通过 `prepare --config
configs/remem/deepseek-development.yaml --data-manifest data/remem_fresh_test_manifest.json
--include-skillopt-controlled` 创建。只有 `run --execute --key-file
.env.deepseek.local` 会真正调用模型；prepare/verify/默认 run/report 仍不调用。
OpenAI-compatible HTTP 路径的请求、重试、响应、token 与缓存信息按运行单独留档；
缺失或失败请求的总用量仍标缺失。原生对照继承固定六步训练序列与 400 次
任务执行预算，CAM 与 AtomSearch 已完成两步真实联调，完整矩阵仍是开发配置。

## 正式实验前仍需完成

1. 在 DeepSeek 小样本探活基础上，校准并发、超时、输出上限、费用及完整工作负载的响应身份。
2. OpenAI-compatible 路径已有 HTTP/用量审计；其余后端的同等覆盖、失败请求可能产生的账单及中断对账仍须验证。
3. 旧 280 题全暴露；新候选 120 题的来源模板分组及未人工验证质量仍须审查。
4. 三类外部对照已实现并完成两步真实联调；仍需内网中等诊断、复现偏差审查和完整任务预算验收。
5. 依校准冻结正式 18/21 格协议；全部最终 skill 固定后的统一测试发布和正式统计报告。

已选择性迁移六个 CAM 机制模块；来源哈希与许可证见 research/remem/cam_port_provenance.json。CAM 参考目录保持只读。

中等诊断入口：prepare --diagnostic --include-skillopt-controlled --include-cam-reference --include-atomsearch。它生成七方法、单 seed、三步、空测试集；内网配置为 configs/remem/intranet-development.yaml。角色凭据文件须绑定冻结 endpoint，NO_PROXY 仅能列这些 endpoint 的主机，运行结束恢复原进程环境。
