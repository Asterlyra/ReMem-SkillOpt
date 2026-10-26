# ReMem-SkillOpt 工作交接

更新日期：2026-10-26。阶段：**多步真实联调已完成；内网 qwen/glm 最小探活成功，七方法中等诊断准备中，正式实验未运行**。

当前实现、命令与局限以 [框架文档](docs/remem/11_FRAMEWORK.md) 和
[实施报告](research/remem/FOUNDATION_REPORT.md) 为准。以下初始路线仍用于检查尚未完成的正式实验要求。

## 用户已经确定的事项

- 在 `E:\Programs\codex\ReMem-Skillopt` 建立独立项目，以新拉取的 SkillOpt 为基础开发。
- CAM-SkillOpt 仅作有选择的参考和复用，不复制整个旧工程、不重启旧实验。
- 采用 R（证据驱动受控修复，A+D）和 M（持续失败与修复记忆，B+C）两个主模块。
- 中等规模，正式实验目标两至三天；不含环境搭建、实现与联调，包含最终测试与分析。
- 准备背景、文献、模型档案、实现计划和实验协议，并上传新的 GitHub 仓库。
- 本轮明确选择方案 2：有限范围的策略接口重构，共用 trainer；授权安装依赖、下载数据、开发模块及保存 Git。

## 当前工作边界

初始 bootstrap 的“不实施、不安装”边界已由本轮用户请求更新。本轮完成环境与框架，未复制旧凭据；后续已按授权完成 DeepSeek 小样本探活。后续先做模型与数据审计、补齐正式实验要求，再按用户要求推进实验；不自动恢复旧 CAM 队列。

两个模块的分组是沿用最近讨论的推荐结构。具体超参数与 21-run 矩阵是本交接的可审查默认草案，尚未冻结，不是既有结果。

## 当前路线与后续工作

1. 阅读 START_HERE、METHOD、IMPLEMENTATION_PLAN、EXPERIMENT_PROTOCOL；检查当前 Git 状态与适用 AGENTS。
2. 已实现离线数据契约、失败落盘和证据验证；继续保持失败先记录的约束。
3. 已接入 R 和 M 独立开关，并验证无补丁、评估拒绝与中断分支的失败保全。M 跨任务检索及冷却调度仍未实现。
4. 只迁移 CAM 中有明确用途、来源可核验的函数，并为行为变化建立有意义的离线检查。
5. 数据/模型联调属于准备阶段。确认真实后端标识、响应契约、JSON、超时、费用与吞吐，不依赖历史探针的结论。
6. 已实现开发版 runner 的 prepare/verify/run/report 分离与冻结；DeepSeek 小样本、旧结果暴露审计、OpenAI-compatible 逐请求用量审计和原生 SkillOpt 离线对照已完成。CAM/AtomSearch 已有开发实现，真实联调、其他后端用量覆盖与最终测试发布仍待完成，详见 `research/remem/PREFLIGHT_REPORT.md`。
7. 环境和方法验收后，用当时用户授权与实际耗时确定冻结的 18 或 21 次运行协议，再执行完整种子组。

## 完成标准

- 有效训练失败先记录，再尝试反思；0→0、无修改、候选被拒绝都不会丢错题。
- 修复操作可以追溯到真实训练任务和轨迹证据；不能用 JSON 合法代替诊断正确。
- M 的错题状态和修复历史内部独立，按 skill 版本解释状态。
- R0M0、R1M0、R0M1、R1M1 共享其余协议，关闭模块后不能通过旧 step_buffer 泄漏被消融的信息。
- 训练、选择、测试划分与测试暴露历史有清单；全体候选冻结前不开放最终测试结果。
- 完成的每格有完整状态、指标、版本、成本与失败分类，不把服务故障记为正常错题。

## 旧工程参考

本地：`E:\Programs\CAM\CAM-SkillOpt`；远端：https://github.com/Lutra11/CAM-SkillOpt 。只读参考，不在旧目录修文件。旧本地有未提交改动，引用具体文件以 `research/remem/provenance.json` 的 SHA-256 为准，不能用旧 HEAD 代表全部本地文件。

旧 CAM 的“只做离线修复/暂停巡检/指定子 agent”属于旧任务边界，不自动继承为新项目的执行计划。旧实验结果不能写成 ReMem 的结果。

## 推荐交给新 Codex 的首条消息

> 请先阅读 START_HERE.md、HANDOFF.md 和 docs/remem/ 下的研究文档，在当前重新克隆的 SkillOpt 上实施 ReMem-SkillOpt。方法固定为 R（证据驱动受控修复）和 M（持续失败与修复记忆）。先完成数据契约、离线验证、集成及实验冻结工具，再准备正式实验；保留模型与测试暴露核查，不复用旧实验结果，不自行扩展搜索规模。实现前给出阶段计划，避免重新讨论已经确定的两个模块。

## 2026-10-24 对照决策

用户明确保留 AtomSearch，并选择按论文独立复现。不得再把来源选择列为待确认。实现与限制见 `docs/remem/12_ATOMSEARCH.md`；CAM 来源见 `research/remem/cam_port_provenance.json`。统一调用限额和小规模预实验入口已接入，正式实验仍未授权立即启动或宣称完成。

## 2026-10-26 内网与中等诊断

用户确认按既有文档使用 qwen target、glm optimizer，并选择七方法、单 seed、三步诊断。网关需要仅对 hub.zgci.org 绕过本机代理；本地角色凭据放在忽略的 .env.intranet.local，必须绑定配置 endpoint，不打印或提交值。DeepSeek 四方法完成两步联调，全部失败尝试保留；见 [多步联调报告](research/remem/LOOP_CONTROL_REPORT.md)。CAM 审计的 result_action 才是最终动作。中等诊断不开放测试集，后续按实际状态继续，不复跑旧工件。

## 中等诊断巡检续接

2026-10-26 21:22 巡检已确认 v1 两个已启动格均终止，其余五格未派发；原记录保留。公共执行超时分类修复已合入，AtomSearch 的 JSON 提示已澄清字段位置，严格解析不变。新诊断使用 intranet-medium-20261026-v2，见 [巡检与修复记录](research/remem/MEDIUM_DIAGNOSTIC_PROGRESS.md)。每 30 分钟的本对话巡检 remem-30 已获用户授权，可修复、测试、保存 Git 并在新冻结版本继续；禁止覆盖旧工件或自动启动正式实验。当前运行位置以 .remem-local/current_diagnostic.json 和实际进程核验为准。

## 2026-10-27 v2 结束与失败格恢复

v2 七个方法全部已终止：core_00 完成三步，其余六格在优化器服务/响应阶段失败。详见 [v2 结束报告](research/remem/MEDIUM_DIAGNOSTIC_V2_REPORT.md) 与 [机器用量记录](research/remem/MEDIUM_DIAGNOSTIC_V2_USAGE.json)。终止后已把独立诊断分支快进合入主分支，151 项测试通过。下一阶段 intranet-recovery-20261027-v1 使用共同 240 秒 HTTP 超时，其余执行与调用上限保持不变；只运行六个失败格，不复跑 core_00，记录为独立恢复版本，不能拼接成 v2 的完整性能表。若恢复遇到明确的上下文、额度、认证等不可自动重试问题，调度器将停止派发。模型与原始响应只留本地忽略目录；继续每30分钟巡检。实际状态以 .remem-local/current_diagnostic.json 和真实进程核验为准。

04:06 更新：恢复版 AtomSearch 已按 160 任务预算正常结束；随后网关 TLS 连接失败，SkillOpt/R-only 终止，后续三格未派发，调度器已停止，等待连接恢复。见 [恢复与网络中止记录](research/remem/RECOVERY_20261027_REPORT.md)。此报告在独立诊断分支保存，暂不合入主运行目录，以保持其冻结源文件清单不变。不得重复执行已完成格或清除失败后伪装首次尝试。
