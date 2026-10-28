# ReMem-SkillOpt 实验进度与 DeepSeek harness 接手说明

更新时间：2026-10-28 17:53，北京时间（Asia/Shanghai）。

本文供接手执行、开发和实验的 DeepSeek harness 阅读，依据现有配置、只读 SQLite 账本、transport 元数据、队列与实际进程核验编写。**接手工具换成 DeepSeek harness，不等于将实验 target/optimizer 改成 DeepSeek 模型。** 当前实验角色仍是 qwen / glm。

## 1. 先看结论

- 环境、数据、R/M 两模块、对照实现及开发实验框架已经搭好。
- 当前是七方法、seed42、三步训练的准备阶段诊断；正式实验和最终测试均未开始。
- 最近一版中，R-only、R+M 已完成三步；CAM 第一轮完成、第二轮分析因服务端错误退出；M-only 尚未启动。
- 更早版本的 core_00 与 AtomSearch 已分别完成相应诊断/预算停止；SkillOpt 的特定分析请求持续失败。它们属于不同冻结版本，不能拼成完整七方法效果排名。
- 当前没有该 study 的实验 Python 进程在运行；队列已保护停止，没有在后台继续训练。
- 阻塞是 glm 返回 `data_inspection_failed`。2026-10-28 17:41 已确认真实分析请求直连内网地址，仍复现同一错误。单纯绕过 Clash 未解除这个阻塞。
- 最新 freeze 校验通过，但结果是 `formal_ready=false`，不能据此启动正式实验。

## 2. 目录、分支与运行环境

| 用途 | 路径 / 状态 |
|---|---|
| 主运行仓库 | `E:\Programs\codex\ReMem-Skillopt` |
| 主运行分支 | `codex/remem-foundation` |
| 当前冻结提交 | `8ea5e4afd2df93f7cb62038773e94080cd7e8964` |
| 隔离报告仓库 | `C:\Users\18207\.codex\worktrees\remem-code-timeout\ReMem-Skillopt` |
| 报告分支 | `codex/remem-response-audit` |
| 本交接前报告提交 | `38741650b814f3a64cba484cad4b0ffee380f429`；本交接文档会在其后提交 |
| 当前运行指针 | 主目录 `.remem-local/current_diagnostic.json` |
| 当前 study | 主目录 `outputs/remem/intranet-pending-arms-20261028-v1` |
| 当前阶段 | `upstream_data_inspection_hold` |
| 队列状态 | `stopped_provider_contract_failure`，停止格 `cam_reference_42` |
| Python 入口 | 主目录 `.venv\Scripts\python.exe`，使用 `scripts/remem/python.ps1` 固定 UTF-8 |
| 实际基础解释器 | `E:\MiniConda\envs\skillopt\python.exe`；venv 启动器与该解释器的父子关系正常 |
| 凭据文件 | 主目录 `.env.intranet.local`，已受 Git 忽略；本文不包含任何密钥 |
| CAM 参考仓库 | `E:\Programs\CAM\CAM-SkillOpt`，只读 |

注意：`outputs/`、`.remem-local/`、本地凭据及大量原始工件没有进入 Git。仅克隆远端报告分支无法获得完整运行现场；换机器接手时须另行安全迁移必要工件和配置，不能把报告当作原始证据。

主目录当前保持原冻结源码。报告分支的后续提交主要是安全汇总和交接文档，**不要直接把报告分支合入主目录再要求旧 freeze 对新目录通过**。freeze 会检查源文件清单，新增文档也可能造成不一致。历史上唯一新增说明文件已完整保存到隔离报告目录 `docs/remem/REMEM_IMPROVEMENTS.md`，不要移回旧冻结目录。

## 3. 已确定的方法与实现

用户已选择共享 trainer 的方案 2，R/M 划分已确定，不需要重新讨论：

- **R：有证据的局部修复与编辑约束。** 提案必须关联实际训练任务、skill 版本及轨迹引文，校验编辑来源与锚点。
- **M：独立失败记录与修改历史。** 有效训练失败先保存，之后才生成提案、评估和门控；格式失败、无修改或不采用都不能跳过失败记录。
- **配对门控是公共评估基础。** 使用验证集逐题配对结果控制采用，不作为第三个创新模块。

主要调用链：固定训练批次 → target 执行 → 失败分类/持久化 → M 上下文 → optimizer 提案 → 证据与编辑约束 → 候选执行 → 配对选择门控 → 修改尝试记录 → 事务检查点。

主要代码位于主仓库：

| 文件 | 职责 |
|---|---|
| `skillopt/engine/trainer.py` | 共享训练、候选评估、采用与输出流程 |
| `skillopt/remem/runtime.py` | R/M 策略组合、失败先保存、预算、缓存与检查点 |
| `skillopt/remem/context.py` | M 开关、同任务历史检索和上下文上限 |
| `skillopt/remem/evidence.py`、`proposals.py`、`budget.py` | 引用、提案结构和编辑预算约束 |
| `skillopt/remem/evaluation.py` | 配对 bootstrap 门控 |
| `skillopt/remem/native_control.py` | SkillOpt 原生对照与 CAM 移植机制 |
| `skillopt/remem/atomsearch.py` | AtomSearch 独立、预算受限复现 |
| `skillopt/remem/provider_contract.py` | 安全错误分类和已知不可重试错误 |
| `skillopt/remem/transport_audit.py`、`call_policy.py` | 实际 HTTP、逻辑调用、重试、用量与耗时账本 |
| `skillopt/remem/study.py` | prepare / verify / run / report、冻结与凭据绑定 |

M 当前是**同任务历史检索**，跨任务语义检索与冷却调度尚未实现，不能在报告中写成已实现。R0 的自由编辑消融也不等于原生 SkillOpt 全流程，因此保留独立 SkillOpt 对照。AtomSearch 是按论文独立复现的预算受限对照，不冒充官方原代码运行；边界见 `docs/remem/12_ATOMSEARCH.md`。

## 4. 冻结诊断协议

| 项目 | 当前约定 |
|---|---|
| 方法框架 | core_00、R-only、M-only、R+M、SkillOpt、CAM、AtomSearch |
| 当前版实际选择顺序 | repair_only_42 → remem_full_42 → cam_reference_42 → memory_only_42 |
| seed / 训练步数 | 42 / 3 |
| 数据 | 已准备 Verified 400 数据；当前诊断划分 40 个唯一训练任务、20 个验证任务、空测试集 |
| 每步训练 | 20 + 20 + 20；第三步复访既定训练任务 |
| target / optimizer | qwen / glm |
| SDK base URL | `https://hub.zgci.org/v1` |
| 实际聊天接口 | `https://hub.zgci.org/v1/chat/completions` |
| 已观察正常响应模型标识 | qwen → Qwen3.6-35B-A3B；glm → glm-5.3-private-19428658 |
| 每格任务执行 / 优化器逻辑调用上限 | 160 / 40 |
| 输出 token 上限 | 16384 |
| HTTP 超时 / 最多尝试 | 240 秒 / 3 次；已知不可重试错误首次停止 |
| 生成代码 exec 上限 | 120 秒，不能与 HTTP 超时混同 |
| 当前版每个选定格 | 最多一次新执行，失败现场不能清除后重跑 |
| 最终测试 | 关闭，执行数 0 |

正常响应的模型标识不能补给缺失标识的错误响应；接口别名与返回名称也不能证明后端权重版本完全固定。

## 5. 已有结果及其解释

下表是**跨版本进度索引，不是同协议的性能比较表**。

| 方法 | 所属版本 | 已达到的阶段 | 结果与局限 |
|---|---|---|---|
| core_00 / R0M0 | intranet-medium-20261026-v2 | 三步完成 | 保留原格，不重跑；不能与后续版本直接拼表 |
| AtomSearch | intranet-recovery-20261027-v1 | 按 160 任务预算正常停止 | 最终推荐与 best-validation 分开保存，不重跑；不是无限预算完整搜索 |
| SkillOpt | intranet-target-timeout-fix-20261027-v1 | 第二轮分析受阻 | 特定训练分析请求 data_inspection_failed，原失败格保留 |
| R-only | intranet-pending-arms-20261028-v1 | 三步完成，14:25结束 | 最终仍为初始 skill；验证分 7/20=0.35 |
| R+M | 同上 | 三步完成，15:22结束 | 最终仍为初始 skill；验证分 11/20=0.55 |
| CAM | 同上 | 第一步完成，第二步分析失败，16:01退出 | 初始 12/20；第一步候选 8/20，最终 result_action=reject，group_guard=blocked |
| M-only | 同上 | 未启动 | 没有本版本成绩，不填零 |

### R-only

保存60条训练观察，三步均先保存20条观察再调用优化器。前两步GLM返回完整Markdown代码围栏，被冻结的严格JSON契约记为invalid_json；第三步一条引用证据不匹配，另一条形成候选。

候选9/20=0.45，相比初始7/20，配对差值+0.10，95%区间[-0.10,0.30]，门控inconclusive，未采用。**不能把候选0.45写成最终效果，也不能据此证明改进。** M关闭，三步history_groups均0。

### R+M

保存60条训练观察，三步均符合先保存后提案。前两步候选均9/20=0.45，对本格初始11/20，配对差值-0.10、95%区间[-0.35,0.15]，均inconclusive未采用。第三步唯一提案因引用文字不在记录轨迹中被拒绝。另有一条不可见上下文证据引用被拒绝。

history_groups为0、0、3。第三步确实读到3组同任务历史失败及每组1条既往修改尝试，总上下文10769字符，低于12000上限，轨迹按既定逻辑截断。只读审计核对了训练来源、早于当前步、同任务及验证ID无交集。**这证明跨步记忆检索链运行过，不证明记忆带来性能收益。** 不同格初始结果有生成随机性，不能用0.55对0.35证明R+M优于R-only。

### CAM

已保存两步各20条训练观察，共40条；第二步reflect的analyst调用返回服务错误，未完成第二步。必须读 `cam_gate.audit.result_action`，不能用初步门控动作替代最终动作。当前只看到第一步最终reject，未采用候选，current/best保持初始0.60。

## 6. 最近三格用量

| 格 | 任务执行 | 优化器逻辑调用 | HTTP / 重试 | 已知输入 / 输出token | 用量完整性 | trainer墙钟秒 |
|---|---:|---:|---:|---|---|---:|
| R-only | 100 | 3 | 105 / 2 | 299040 / 702905 | 103份数值usage；2次尝试缺响应/用量，总量与缓存未知 | 3077.953 |
| R+M | 120 | 3 | 123 / 0 | 335154 / 837743 | 完整；缓存输入46464 | 3428.907 |
| CAM | 80 | 8，其中7完成1错误 | 88 / 0 | 216716 / 563443 | 87份数值usage；1份错误响应缺用量，总量与缓存未知 | 2320.375 |

诊断探针、历史失败格和独立复查另行计费，不包含在此表；此表不是账户账单。HTTP耗时累计是并发调用之和，不能冒充墙钟。缺失用量必须为unknown/null；known-sum=0不等于实际免费。

## 7. 阻塞与VPN/Clash排查

### 已确认

1. 本机聊天用Clash HTTP代理127.0.0.1:7890，内网使用Sangfor aTrust VPN。
2. hub.zgci.org解析到gateway.zgci.org，再到10.1.132.25；该地址有内网VPN路由。
3. 显式经过Clash的无鉴权GET连接失败；绕过Clash直连收到预期HTTP401。这只证明连接可达，不能证明模型分析成功。
4. 忽略的本地配置已有 `NO_PROXY=hub.zgci.org`；执行器在创建HTTPX客户端前应用NO_PROXY/no_proxy，只影响实验进程，不修改聊天或全局代理。
5. 17:41用户授权单次真实分析验证，socket peer确认为10.1.132.25:443，仍约15.485秒后返回HTTP200、data_inspection_failed/upstream_error，缺model/choices/正文/usage；1次HTTP、0重试。

因此当前不能将错误仅解释成Clash冲突，也不能靠增加重试继续。错误类别指向网关/上游数据检查，但输入还是输出、具体命中内容、是否误判或检查服务内部异常，尚无服务端日志证明。

最近独立验证目录：主目录 `outputs/remem/glm-long-request-recheck-20261028T094104Z`。请求是旧SkillOpt失败训练批次的既有重建，正文93388字节，消息哈希与此前重建一致；只用于恢复验证，不写回旧实验。

CAM实际失败请求时间为10月28日15:59:44.328475 +08:00，正文82505字节，HTTP头返回约16.797秒，未重试。此前成功analyst请求包括116249字节，所以不能仅按长度解释。无可核验上游request_id；客户端本地审计ID不能当服务端请求号使用。

### 接手者优先处理

- 按已有排查单向网关管理员核对具体失败请求：错误发生层、输入/输出/检查服务异常类别、正式处理结论和服务端request_id。本文没有代用户联系任何人。
- 检查本地遗漏可以继续离线进行；不得为了让请求通过而删轨迹、删任务、换模型/接口或关闭检查。
- 若服务确已修复，在用户授权下做有界、单独计费的真实负载确认；不要周期性重放相同被拦内容。
- 恢复确认后再明确未完成范围和新冻结版本。**当前保护停止队列禁止 `--resume-unstarted`；不要删除停止字段、改旧freeze或绕过守卫直接执行未启动格。**

## 8. 已修复的问题与仍待完成项

已修复并有针对性回归证据：生成代码exec超时分类；target HTTP超时240秒实际传递；HTTP200及非2xx已知provider错误分类；不可重试错误首次停止；安全错误类别持久化；provider contract/畸形响应暂停禁止原队列resume；数值usage与缺失用量分开统计。相关修复测试已有241项通过记录，见 `RECOVERY_BOUNDARY_FIX_REPORT.md` 等。本文整理期间未重跑整套测试，也未改执行代码。

仍待完成：

- 解除glm真实分析负载阻塞，完成CAM/M-only尚缺诊断；SkillOpt重要对照仍不完整，不能悄悄删掉。
- 审查模型诊断与编辑是否语义成立，尤其“写入计算值避免读缓存为空”的规则，不能把JSON和引文校验通过当因果正确。
- 正式实验前的模型身份/费用/吞吐核对、失败请求用量对账、外部对照真实验证。
- 最终新测试来源、模板分组、数据质量与统一发布协议；测试结果不得用于挑协议或预算。
- 当前 `research/remem/study_design.json` 是草案；18/21次等正式矩阵不能未经确定就启动。

## 9. 接手后的安全操作顺序

1. 先读项目AGENTS、START_HERE、本交接和指针；主目录旧HANDOFF含历史状态，最新状态以本交接、隔离报告、指针及实际账本为准。
2. 确定工作目录和解释器。共享venv的独立脚本可能受.pth影响导入主目录代码，运行隔离分支测试/脚本时核对 `module.__file__`，不要误测另一分支。
3. 核对Git与真实进程；不能只根据queue里的旧PID宣称仍运行，也不要误杀其他项目进程。
4. 只读核查现有SQLite：`remem/ledger.sqlite3`及`remem/calls/ledger.sqlite3`，连接使用URI `mode=ro`；结合transport.jsonl、runtime_state和queue解读。
5. 先解决外部阻塞，或完成独立离线修复并测试；所有旧失败现场保留。
6. 若冻结源码、提示、配置或数据需变化，先保存旧工件及归档哈希，使用新study/version，提交干净源码后重新prepare/verify。不要把跨版本成绩混成同一比较。
7. 只执行明确选定且已获授权的未完成范围，逐格独立记账；完成格不盲目重跑。已开始未完成的阶段先核对实际调用，不能默认为免费重试。
8. 完成全部诊断与问题报告核验后再与用户确定正式实验。最终测试继续关闭。

### 可直接执行的只读检查

以下PowerShell命令不调用模型；其中verify已在本交接编写时通过。

```powershell
Set-Location -LiteralPath 'E:\Programs\codex\ReMem-Skillopt'
Get-Content -LiteralPath '.remem-local/current_diagnostic.json'
git status --short
git rev-parse HEAD
& .\scripts\remem\python.ps1 scripts/remem/study.py verify outputs/remem/intranet-pending-arms-20261028-v1
if ($LASTEXITCODE -ne 0) { throw 'Freeze verification failed' }
Get-Content -LiteralPath 'outputs/remem/intranet-pending-arms-20261028-v1/queue.json'
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match 'python' -and $_.CommandLine -like '*intranet-pending-arms-20261028-v1*' } |
    Select-Object ProcessId, ParentProcessId, CreationDate, ExecutablePath, CommandLine
```

需要刷新安全汇总时，可在主目录执行下列本地审计命令。它会更新报告工件，但不会调用模型或修改原始事件账本：

```powershell
& .\scripts\remem\python.ps1 scripts/remem/audit_medium.py outputs/remem/intranet-pending-arms-20261028-v1
```

不在本交接中提供可一键误启动的真实执行命令；接手者应先满足上述恢复条件，再按prepare/verify/run生命周期构造新版本的明确执行子集。

## 10. 证据索引与并行接手提醒

下列安全汇总位于隔离报告仓库的 `research/remem/`，已进入报告分支Git：

- `R_ONLY_TERMINAL_20261028.json`：R-only终止与门控。
- `REMEM_FULL_TERMINAL_20261028.json`、`REMEM_MEMORY_CONTEXT_20261028.json`：R+M终止与真实记忆检索。
- `CAM_HOLD_20261028.json`：CAM阶段、最终动作、用量与错误。
- `GLM_DIRECT_RECHECK_20261028.md/json`：17:41内网直连仍失败的真实负载证据。
- `VPN_CLASH_ROUTE_CHECK_20261028.md`：两条连接路径及已有NO_PROXY。
- `GLM_GATEWAY_REVIEW_BRIEF.md`：可交管理员的排查信息，无密钥/原始轨迹。
- `PENDING_ARMS_20261028_CHECKS.md`：最近检查历史。
- `MEDIUM_DIAGNOSTIC_V2_REPORT.md`、`RECOVERY_20261027_REPORT.md`：旧版本及完成格边界。
- `RECOVERY_BOUNDARY_FIX_REPORT.md`：客户端修复与241项测试记录。

主study内重点文件：freeze.json、recovery_plan.json、queue.json、operational_audit.json、DIAGNOSTIC_REPORT.md，以及 `runs/<arm>/` 下config、runtime_state、SQLite与transport。旧study以自己的归档源码/哈希核验，不要求旧freeze对当前新版源码验证通过。

截至本文编写，Codex的 `remem-30` 半小时巡检仍ACTIVE，已更新为当前暂停事实，只读检查、无变化静默，禁止自动重发或重建实验。**交接文档本身不会自动关闭巡检。** DeepSeek harness接手前应与用户明确单一执行者和巡检归属，避免同时修改指针、运行目录或报告；本次编写交接没有启动任何模型、实验或外部消息发送。

凭据仅保留在受忽略本地文件，不复制进交接、命令行参数或Git。原始模型回复、错误封套和个人聊天记录不提交。CAM参考仓库不修改。新的架构分歧按AGENTS先列不超过4项方案，既定R/M不反复选型。
