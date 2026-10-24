# 可用模型与接入档案

**旧网关证据日期 2026-10-16 至 2026-10-19；本项目整理日期 2026-10-23。旧网关未在新项目重新探测。** 可用性、费用、路由和限制都可能改变，以下旧网关记录不是当前在线保证。

## 2026-10-24 DeepSeek 临时开发接入

旧网关本轮不可用，使用 DeepSeek 官方 `https://api.deepseek.com` 做准备阶段的独立探针。
官方[调用文档](https://api-docs.deepseek.com/)把请求别名
`deepseek-flash` 对应到 DeepSeek-V4.1-Flash-1017；实际 `/models` 返回该别名，
Chat Completions 响应也只返回该别名，不能仅凭响应字段证明内部权重版本。

一次最小聊天、一次真实 SpreadsheetBench **训练**任务、一次使用 R 提案提示词的
优化器空证据调用都成功。训练任务通过评分，优化器返回有效 `no_change`；
这只是接口/执行链探活，不是方法效果。真实训练任务 1 次 HTTP 请求、
1,056 输入 token、8,079 输出 token；优化器 1 次请求、1,810 输入 token、
100 输出 token。请求、用量和失败状态已保存为受忽略的元数据，不保存原始网关响应。
官方[价格页](https://api-docs.deepseek.com/quick_start/pricing/)会变化，正式运行
前应按当时账单再核对费用。两角色共用同一模型的结果不能与历史 glm/qwen 实验混称。

本地密钥位于 Git 忽略的 `.env.deepseek.local`，配置模板
`configs/remem/deepseek-development.yaml` 不含密钥。开发运行使用
`openai_chat` 的 `openai_compatible` 认证路径；当前模型别名和价格页均已联网核对。

以下章节仅描述旧网关档案。

来源：旧项目 `docs/experiments/ZGCI_MODEL_HUB_API.md`、`CAM_SKILLOPT_ZGCI_EXPERIMENT_PLAN.md`、`configs/experiments/zgci_cam_matrix.yaml`、v3 实际运行记录。旧文档的“仅某模型能 JSON”“全部免费”等断言改为有日期的观察，不推广成模型本身永久能力限制。

## 1. 文本模型

| 网关别名 | 历史响应中的 model 标识/映射 | 建议角色 | 限制 |
|---|---|---|---|
| glm | glm-5.3-private-19428658 | 主 optimizer；可作后续 target | 历史结构化编辑测试与真实优化运行成功；不保证每次 JSON 有效 |
| glm-anthropic | 同上 | 备用接口，不作独立模型样本 | 与 glm 可能同后端，接口与延迟不同 |
| qwen | Qwen3.6-35B-A3B | 主 target | 低输出预算曾导致 reasoning 占满而正文为空 |
| minimax | 历史返回同一 Qwen 标识 | 不作为第二个独立模型 | 别名不等于 MiniMax 官方模型身份，必须重核对 |
| gemma4:26b | gemma4:26b | 后续迁移 target 候选 | 历史小探针输出曾截断，未作为本轮主 optimizer 验证 |
| smart-router | 历史标识/自报不稳定 | 不用于主实验 | 路由可能变化，难以固定身份 |
| smart-router-v2 | 历史有 GLM 标识，另有路由记录 | 不用于主实验 | 不能据别名把它视作独立、固定模型 |

历史别名约对应三个可区分的文本后端系列，不能把七个别名算七个独立模型；具体参数量、上下文上限与后端真实版本未由本项目独立验证，不作为论文确定事实。

## 2. 其他历史可见服务

| 类别 | 别名 | 本轮用途 |
|---|---|---|
| 向量 | bge-m3、qwen3-embedding:4b | 不需要；第一版检索采用可审计匹配 |
| 重排 | bge-reranker-v2-m3 | 不需要 |
| 语音 | cosy-voice、qwen-asr | 不使用 |
| 图像/视频 | qwen-image、minimax-h3 | 不使用 |
| 视觉服务 | face-detect、face-embed | 不使用 |

旧档案说模型列表有 17 项，但列出的文本 7 项与其他 8 项合计 15 项，文档内部计数不一致；不补造剩余名称。后续实际 `/models` 响应再保存经过脱敏的清单。

## 3. 接口和凭据

- 历史 Base URL：`https://hub.zgci.org/v1`。
- 历史协议：OpenAI-compatible Chat Completions；普通 Bearer API key。
- 历史训练使用 `optimizer_backend=target_backend=openai_chat`，角色 auth_mode 为 `openai_compatible`；这里不代表调用 OpenAI 官方服务。
- 角色模型必须在配置中显式 optimizer=glm、target=qwen；上游初始化的角色 model 可能覆盖环境变量设置。
- 研究路径的密钥变量名：`OPTIMIZER_AZURE_OPENAI_API_KEY`、`TARGET_AZURE_OPENAI_API_KEY`，具体以新上游初始化代码验证。
- 模板：[model.env.example](../../research/remem/model.env.example)。只写本地 `.env` 或进程环境，不把凭据写入 YAML、报告、Git URL 或命令行参数。

新上游另有 `openai_compatible` 后端及 `*_OPENAI_COMPATIBLE_*` 环境变量；这与历史 Azure 命名兼容路径是两套配置入口，不要混用。选择一种完成真实任务联调再冻结。

## 4. 参数与运行经验

- 只能使用服务公开的别名；旧探针调用某些带版本号名字收到 model_not_found。不要把响应 model ID 直接当请求别名。
- qwen 的输出预算参考 16,384。历史 256 上限出现正文为空；2,048 在简单探针可行，但不足以证明复杂表格任务也够用。
- reasoning_effort 在不同别名上行为不同。历史 qwen 的 `none` 可关闭思考；glm 的类似探针表现不稳定。主实验建议不改变思考策略，起始采用历史实际运行中的默认/省略，所有方法一致。
- “服务接受参数”不等于参数生效；`seed` 也不保证确定性。响应 schema、finish_reason、正文、tool calls 和 usage 分别检查。
- 历史复杂任务曾需要较长超时；实际 HTTP 超时与代码执行超时是两回事。不要只改 exec_timeout 就假定模型 HTTP 等待也延长。
- 初始 workers=8 是历史配置参考，准备阶段校准共享吞吐；并发不应超过服务限制。
- 旧服务曾报告价格倍率 0；本项目没有查验当前价格或可用额度，不承诺免费。
- 旧环境中 Hugging Face 直连失败、镜像可用是有日期的网络观察；当前需验证来源和 revision，不盲目改下载域名。

## 5. 新项目准备时必须记录

每角色的请求 alias、响应 model、endpoint host、backend implementation、采样与思考参数、上下文/输出限额、超时/重试、并发、JSON 解析结果、usage 覆盖、费用与时间。模型版本变化应暂停并标记，不混到同一正式矩阵。

准备阶段的小样本探针不混入正式指标；原始响应可能含任务内容，脱敏后仅提交必要元数据。服务故障不可作为错题本中的技能错误。
