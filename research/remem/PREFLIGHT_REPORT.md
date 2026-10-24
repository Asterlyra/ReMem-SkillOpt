# DeepSeek 开发预实验与正式实验前审计（2026-10-24）

状态：**开发预实验完成；正式实验未运行、协议未冻结**。本报告只给出可核对的准备阶段事实，不把单题通过当作 ReMem 的方法效果。

## 模型探活

DeepSeek 官方[API 文档](https://api-docs.deepseek.com/)列出 `deepseek-flash` 为 DeepSeek-V4.1-Flash-1017；实际 `/models` 和聊天响应只返回别名，不能由响应单独验证权重版本。官方[价格页](https://api-docs.deepseek.com/quick_start/pricing/)用于后续费用校准，价格会变化。

| 探针 | 实际结果 | HTTP | 输入 / 输出 token |
|---|---|---:|---:|
| 最小聊天 | 返回预期 `OK`，响应别名 `deepseek-flash` | 1 | 35 / 9 |
| 真实 SpreadsheetBench 训练题 32438 | 项目 adapter、执行器、评分器全链通过，hard=1 | 1 | 1,056 / 8,079 |
| R 提案提示词、空训练证据 | 合法 `no_change`，没有虚构编辑 | 1 | 1,810 / 100 |

合计 3 次聊天 HTTP 请求，已报告 2,901 输入、8,188 输出 token；另有 1 次 `/models` 请求。三次响应都给了 usage。训练题输出 8,079 token 接近 8,192 上限，正式配置前需校准输出上限、延迟、并发与成本。三个探针的脱敏元数据分别保存在受忽略的 `outputs/remem/preflight/deepseek_metadata.json`、`outputs/remem/pilot-deepseek-v41-1017/metadata.json`、`outputs/remem/optimizer-preflight-deepseek/metadata.json`。原始任务轨迹及模型内容不提交 Git。

密钥只在受 Git 忽略的 `.env.deepseek.local`，未写入配置、报告或源码。开发配置是 `configs/remem/deepseek-development.yaml`，target 与 optimizer 均请求同一别名；不能与历史 qwen/glm 结果混算。

## 数据暴露和候选测试池

`scripts/remem/audit_exposure.py` 扫描本地旧 CAM 快照的 483 个 `results.jsonl`，只读取任务 ID，不读取分数。旧 Verified400 中的 280 道 test 题全部在旧结果里出现，因而没有可从该池中挑选的“未使用”120 题。审计范围不包括私人运行、外部预训练数据或所有历史 prompt。文件索引和涉及旧 test 的结果文件哈希在 `exposure_audit.json`。

从固定 Hugging Face revision `ab0b742b0fc95b946f212d80ac7771b5531272e4` 的原始 912 题中，排除 Verified400 后有 512 题；它们没有出现在上述旧结果文件。`scripts/remem/prepare_fresh_test.py` 按预设种子 20261024、题型分层选出 120 题（cell 67、sheet 53），与 train80/val40 构成新开发划分。120 题共有 359 组输入/答案工作簿，文件可读。原始下载归档 SHA-256 是 `9cf7228b54f1edcdd4b372eb736774adf29cb4f804c9920229bac6c154833399`；完整逐文件哈希和 ID 在受忽略的 `data/remem_fresh_test_manifest.json`，数据许可为 CC-BY-SA-4.0。

`scripts/remem/audit_templates.py` 的精确检查发现跨划分相同输入工作簿 0、相同题目文本 0；测试题与 train/val 文本的最大 token Jaccard 为 0.3333。这不能排除经过改写的同源工作簿或模板，来源分组仍是 **unknown**。额外 512 题不属于人工 Verified400，候选测试质量尚未获得同等级验证。完整检查数值在 `fresh_template_audit.json`，旧划分的对照审计在 `template_audit.json`。我们尚未用 DeepSeek 读取或评分这 120 道候选 test。

## 调用用量与外部对照

`skillopt/remem/transport_audit.py` 为 OpenAI-compatible 运行留存每次 HTTP 请求/响应、角色、阶段、逻辑调用 ID、重试、状态、响应别名、finish reason 与 usage。请求体、响应体、认证头不进入审计日志；SDK 隐式重试被关闭，外层重试逐次计数。成功响应按请求 ID 与 usage 对齐；响应缺失、失败请求或缺失 usage 时，总 token 保持 `null` 并单列已知用量。HTTP 时间是到响应头的累计时间，不等于端到端运行时长。其他模型后端和失败请求的服务端计费尚无法完整核对，不能声称全提供商完整计费。

`skillopt/remem/controls.py` 实现原生 SkillOpt 开发对照：按同 seed 六批、80 首见 +40 固定重现训练题，调用原生编辑/历史/门控，并在 400 次优化 task execution 上限前记账。其含 3 个 seed 的冻结配置可离线生成、验证，尚未完整调用模型。`core_00` 采用共同 ReMem 门控，不等于原生 SkillOpt；对照单列。

CAM v3 精确对照需对本地快照和公开上游逐文件核对来源、许可与差异后再移植。AtomSearch 目前找到[论文](https://arxiv.org/abs/2610.19951)，未找到可核验的官方代码发布；不能以自由编辑冒充原方法。两者保持 planned，正式 18/21 格矩阵不应据此报告为完成。

## 下一步与冻结边界

当前可生成 12 核心组 +3 原生 SkillOpt 对照的 **development-only** 冻结包；完整运行还需要预算/吞吐校准、候选测试质量审查、外部对照选择及最终测试发布程序。若源码、prompt、配置、任务序列、环境或模型身份变化，必须使用新 study ID。最终测试只能在全部 final skill 固定后统一执行，测试反馈绝不能进入优化器或记忆。

离线验证：`scripts/remem/python.ps1 -m pytest tests/remem tests/test_openai_compatible_backend.py tests/test_openai_compatible_config.py tests/test_azure_openai_compat.py tests/test_azure_usage_accounting.py -q`，本次 110 passed。完整优化、候选最终测试、CAM/AtomSearch 对照均未执行。
