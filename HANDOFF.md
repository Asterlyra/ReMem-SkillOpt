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

11:20 更新：用户通知内网恢复，两角色最小鉴权与身份检查通过、原版本 verify 通过，已接续尚未启动的 R+M、CAM、M-only，当前先运行 R+M。原成功/失败格不重放；使用原冻结源码与参数，测试仍关闭。队列历史 network_hold 字段保留，最新 scheduler_invocations 和运行指针才表示当前阶段。报告分支继续独立保存，不在运行中合入主目录。

11:54 更新：R+M/CAM的target基线调用超时终止，M-only运行中。已在隔离分支修复target HTTP超时配置传递遗漏；原恢复版实际target仍为120秒，不能继续声称两个角色实际均240秒。见 [修复说明](research/remem/TARGET_TIMEOUT_PROPAGATION_FIX.md)。主目录暂不合入，待所有当前进程终止后建立新版本；实际待办以主目录 `.remem-local/current_diagnostic.json` 指向的pending修复清单为准。

12:24更新：恢复版六格全部终止，仅AtomSearch正常预算停止；其余五格失败，详见恢复报告及 `RECOVERY_20261027_TERMINAL_USAGE.json`。主目录合入修复前已验证原freeze、归档源码完整、实际进程全部退出；下一轮仅在新 `intranet-target-timeout-fix-20261027-v1` 中做一次配置传递实现修复验证，限定五个失败格，原任务/预算不变，不重跑core_00和AtomSearch。实际运行位置仍以忽略目录指针为准。

13:24更新：新版本SkillOpt在第二轮analyst连续三次收到缺少model/choices/usage的glm错误封套，保护队列已停止，后续四格未启动。已保存40条训练观察和完整元数据，未完成三步；等待glm网关响应问题恢复，不循环探活或重跑。见 [glm服务中止说明](research/remem/GLM_PROVIDER_HOLD_REPORT.md)。本报告分支不在主目录运行冻结中合入。

16:52更新：用户要求再次检查，单独重建失败训练minibatch请求（正文大小与旧失败记录一致）发送1次、无重试，复现 `data_inspection_failed` / `upstream_error`。应核对网关内容检查环节，不再仅按内网未恢复解释；无法判断输入/输出及具体命中内容。见 [复查记录](research/remem/GLM_CONTENT_INSPECTION_RECHECK.md)。原实验保持停止，后续四格未启动，不循环重试相同内容，不擅自删数据或改模型。

20:55离线排查：失败批次8题与历史15个任务ID均来自训练，未发现验证ID/本地角色密钥字面匹配。存在95,051字节的成功analyst请求，大于失败请求93,388字节，不能只归因于长度。用真实SDK+MockTransport离线复现：HTTP200数据检查错误因未识别而触发TypeError，随后重试两次；真实网络/模型调用0。见 [离线审计报告](research/remem/GLM_OFFLINE_AUDIT_REPORT.md)。运行时代码未改、主目录freeze不变、定时巡检仍删除；下一步可修客户端明确分类与停止无效重试，上游命中原因仍需网关复核。

后续离线修复：用户要求继续，隔离分支已增加安全provider错误分类、已知不可重试错误首次即停、账本类别保留，以及有效数值用量/上游错误响应计数。197项相关测试通过，离线fixture从3次请求降为1次，真实网络/模型调用0。详见 [修复报告](research/remem/PROVIDER_CONTRACT_FIX_REPORT.md)。主目录仍冻结3f6d7de，旧study未覆盖，网关检查问题未解除，定时巡检保持删除。实际应用必须另建冻结版本，不能直接接旧格混用源代码。

2026-10-28离线续查：用户选择完整补齐非HTTP200错误分类与暂停恢复边界。相同数据检查错误在HTTP200/400/403/429/500下均一次即停，安全类别与响应ID落盘；provider contract或畸形响应暂停禁止原队列resume，其他显式恢复仍受原检查约束。241项相关测试通过，网络/真实模型/实验子进程0，见 [离线边界修复报告](research/remem/RECOVERY_BOUNDARY_FIX_REPORT.md)。隔离工具已校验源码来源，主目录freeze及原账本未变，修复仍待新冻结版本应用；网关处置未确认、实验暂停、定时仍删除。

2026-10-28 11:14用户要求实际请求、若正常则继续。对同一重建失败批次只发送1次，15.375秒后仍返回HTTP200的data_inspection_failed/upstream_error，无model/choices/usage；与前次重建消息哈希一致。恢复条件未满足，未启动试跑或新study。见 [本次在线验证](research/remem/GLM_RECHECK_20261028.md)。原冻结与账本不变，定时继续关闭，不自动重试相同内容。

2026-10-28 13:24用户要求核对完整接口、指定密钥及glm模型ID。本地密钥比对一致，SDK base_url和实际chat路径正确；最小普通glm请求返回OK，20输入/40输出token。模型目录读取成功，返回15个服务ID，见 [配置核对](research/remem/HUB_CONFIGURATION_CHECK_20261028.md)。这证明基础调用可用，不能替代11:14失败的真实分析请求；本轮未重发被拦内容，原研究仍暂停，定时仍关闭。

2026-10-28 13:28用户明确要求继续。原SkillOpt分析批次单次验证仍被拦，保留该失败格、不重放；GLM普通调用及qwen身份已通过。准备按新冻结版本intranet-pending-arms-20261028-v1继续此前未启动的R-only、R+M、CAM、M-only，每格一次、原任务/模型/预算不变，任何已知数据检查错误继续触发全队列停止。见 [继续计划](research/remem/PENDING_ARMS_20261028_PLAN.md)。合入修复须先核验旧归档与实际进程，新旧成绩不能混合；实际启动以指针和真实进程为准。定时仍关闭，测试不开放。

13:34实际启动核验：旧study986文件哈希保留且核对未变；主目录已合入并冻结8ea5e4a，新版本新旧数据/任务/环境/规范化配置逐项一致，241测试通过、verify通过。队列实际PID35928、R-only实际PID24040，创建时间/解释器/命令已核对；R-only正在20题训练前基线，4个HTTP请求中已收到2份有效Qwen响应，其余在途。见 [启动记录](research/remem/PENDING_ARMS_20261028_LAUNCH.md)。接续顺序R+M、CAM、M-only，原SkillOpt失败格不重放。主目录运行中保持冻结，后续报告仅隔离分支保存；定时仍删除。

13:40用户重新要求半小时检查，已重建本对话heartbeat remem-30为ACTIVE、间隔30分钟，取代此前删除安排。主目录指针登记新授权，冻结源码和恢复计划不改。当前R-only基线18个请求收到17份有效Qwen回复，无重试/接口错误；CIM进程与freeze核对通过。正常无重要变化保持安静，异常定位修复仍受冻结/新版本及停止保护约束；四格全部终止并验收报告后删除巡检，不扩展实验。

14:09巡检、14:14复核：R-only已保存60条三轮训练观察，第三次优化进行中；前两次GLM回复因完整Markdown代码围栏被严格JSON契约拒绝，均未采用，不改当前冻结协议。主目录新增未跟踪REMEM_IMPROVEMENTS.md造成唯一source清单差异，已完整移至本隔离worktree同名路径并核对哈希，原冻结文件无变更，verify恢复通过。实际进程继续运行，见 [检查记录](research/remem/PENDING_ARMS_20261028_CHECKS.md)。不重复发同一发现通知；后续文档必须放隔离目录，不能运行中添加到主冻结源清单。

14:39巡检：R-only已于14:25完成三步，100任务、3优化器逻辑调用、105HTTP/2重试；60训练观察先于对应提案持久化，M关闭。前两步格式失败；第三步一条提案引用核验失败，另一个候选选择分9/20对比初始7/20，CI[-.10,.30]，门控inconclusive未采用，最终仍初始skill .35。R+M实际PID50320、创建14:25:15，正在第一轮训练；当前freeze/进程核验通过。见 [R-only终止审计](research/remem/R_ONLY_TERMINAL_20261028.json) 和检查记录；不复跑R-only，CAM/M-only等待原队列。

15:09巡检：R+M持续正常推进，检查期间完成第二步并进入第三步训练；前两轮候选均.45对本格初始.55，配对CI[-.35,.15]，均inconclusive未采用。40训练观察先保存，前两批无同题历史，history_groups均0；须等第三步反射再核验M。实际PID50320身份及freeze通过，无接口错误/重试，无额外探针或改动。见 [检查点](research/remem/REMEM_FULL_CHECKPOINT_20261028T070956Z.json)；正常中间状态保持安静，后续仍按原队列。

15:39巡检：R+M已于15:22完成三步，120任务/3优化器逻辑调用/123HTTP、0重试、用量完整；未采用修改，最终仍初始skill .55。第三步确实读到3组同任务历史失败及各1条修改尝试，训练来源/时序/字符上限核对通过，不代表记忆收益。CAM实际PID38092、创建15:22:28，已保存首轮20条训练观察，analyst在途，尚无最终result_action；M-only等待。freeze与真实进程核验通过，见 [R+M终止审计](research/remem/REMEM_FULL_TERMINAL_20261028.json) 和 [记忆检查](research/remem/REMEM_MEMORY_CONTEXT_20261028.json)。

16:09巡检：CAM于16:01在第二步analyst遇到data_inspection_failed，首次即停，队列stopped_provider_contract_failure；CIM确认调度器/CAM均已退出，M-only未启动。第一步候选8/20对初始12/20，最终result_action=reject，group_guard=blocked，仍初始skill .60；仅完成一步。40训练观察先保存，80任务/8优化器逻辑调用/88HTTP、0重试、1份错误响应缺用量，墙钟2320.375秒，测试0。见 [CAM停止审计](research/remem/CAM_HOLD_20261028.json)。指针更新upstream_data_inspection_hold；等待网关核查，不重发被拦请求、不resume原队列、不自动新建恢复版或跳到M-only。主目录freeze通过且干净。巡检保持授权，无变化静默，不重复故障通知。

17:41用户要求VPN配置好后继续，先单次验证原失败训练分析请求：实际socket为10.1.132.25:443，确认内网直连，仍在15.485秒后返回data_inspection_failed/upstream_error，0重试、缺模型/正文/用量。见 [直连真实负载复查](research/remem/GLM_DIRECT_RECHECK_20261028.md)。当前错误在绕过Clash后仍存在，不能据普通连接成功启动实验；未新建实验、未resume旧队列、未启动M-only。每半小时仅只读检查，禁止循环重发，等待网关处理的新证据。R-only/R+M结果和CAM失败现场保留，最终测试关闭。
