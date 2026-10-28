# 非成功HTTP错误与暂停恢复边界：离线核查和修复

2026-10-28用户确认网关尚未处理或情况不明，要求继续离线检查；发现新边界遗漏后，用户选择方案1：统一处理非HTTP200错误，并禁止这类暂停直接恢复原队列。本轮所有模型响应、队列和进程均为本地合成/模拟，不读取真实密钥、不连接模型服务、不运行实验。

## 已复现的问题

在隔离分支c25b4f2上，使用真实OpenAI SDK与httpx.MockTransport，给相同合成 `data_inspection_failed` 错误设置不同HTTP状态：

| 情形 | 修复前 | 修复后 |
|---|---|---|
| HTTP200错误封套 | 一次请求、明确类别、停止派发 | 保持原行为 |
| HTTP400错误 | 一次请求但类别丢失，队列模拟派发第二组 | 一次请求、类别保留、停止派发 |
| HTTP429/500携带同一数据检查错误 | 三次请求，类别丢失，队列模拟派发第二组 | 一次请求、类别保留、停止派发 |
| `--resume-unstarted`恢复provider contract暂停 | 模拟派发未启动组 | 拒绝恢复，原queue字节不变，不写备份、不派发 |

基线见 [合成基线元数据](RECOVERY_BOUNDARY_BASELINE.json)。这不是当前网关已改HTTP状态的证据，也不是新增实验结果。真实故障记录仍是2026-10-27的HTTP200错误封套。

## 实现与调用链

`provider_contract.research_provider_errors`在SDK调用周围捕获APIStatusError，复用安全类别白名单，支持SDK的内层错误body与完整error封套。上下文位于HTTP审计身份仍生效的位置，先写安全元数据，再抛明确错误；不保存错误message、原始代码值或响应正文。

优化器普通/消息列表的Chat Completions与Responses四条路径，以及target重试函数均接入。已知不可重试类别优先于HTTP状态，首次退出；明确限流等暂态类别保留有界重试；未知类别只记unclassified并保留既有HTTP状态处理。非研究调用不转换SDK异常。错误审计写入失败会抛CallPolicyError并停止，不能转换成可重试错误。

非成功HTTP使用独立 `provider_error` 元数据事件，带响应ID、逻辑调用ID、角色、阶段、状态和安全类别，不伪造usage事件。汇总把该事件关联到原HTTP响应；缺失token和缓存仍未知。调度器先判断具体不可重试类别，再判断通用401/403，避免数据检查错误被误标成认证故障。

调度器拒绝恢复 `stopped_provider_contract_failure` 和 `stopped_malformed_provider_response` 两类队列，检查发生在备份或改写queue之前。恢复需新study/version并verify；认证恢复及其他原有显式恢复仍保留真实进程、冻结和终态检查，不复跑已尝试格。

## 验证与来源

- 241项相关测试通过，包含ReMem全部测试、Azure用量/兼容、OpenAI-compatible后端/配置及凭据脱敏。新增覆盖四条优化器路径、两条target路径、类别/ID关联、暂态重试、未知错误脱敏、辅助审计写入失败、两类暂停不可恢复，以及其他显式恢复能力。
- [修复后合成元数据](RECOVERY_BOUNDARY_FIXED.json)：HTTP200/400/403/429/500均一次请求，下一组未派发；两类暂停均拒绝恢复且原queue不变。真实模型调用、网络连接尝试和真实子进程均0。
- 可复核工具：`scripts/remem/offline_recovery_boundary_audit.py OUTPUT_DIRECTORY`。只能使用不存在的新输出目录；会屏蔽网络并断言结果。运行时使用项目解释器。
- 共用主目录venv直接执行隔离脚本时曾导入旧checkout，已为两个离线工具添加源码目录引导与backend位置校验。一次输出管道提前关闭也使工具失败。失败目录原样保留，不作为通过证据；最终有效证据是 `outputs/remem/offline-recovery-boundary-20261028-verified-final/metadata.json`，其中保存实际源码哈希。
- 修改的小模块、脚本和测试lint通过；两个旧大文件分别保留3项和12项历史告警，与HEAD比较无新增。交接结构与diff检查通过。

## 当前实验边界

主运行目录仍冻结3f6d7de，当前study仍为 `intranet-target-timeout-fix-20261027-v1`，暂停状态未变。只读SQLite复查确认40条训练观察、9次优化器逻辑调用（8完成、1错误）；HTTP仍91次、3条用量缺失，最终测试0。原账本、transport、queue及freeze等工件哈希未变，freeze验证通过。

修复只在隔离分支保存，未应用到冻结运行目录。网关问题尚未解除，不能据离线测试宣称真实恢复；不重发被拦请求、不删任务或修改提示规避检查、不重启定时任务、不启动新研究。后续采用修复必须登记新冻结版本，不能把旧失败格清除重试或混合版本成绩。
