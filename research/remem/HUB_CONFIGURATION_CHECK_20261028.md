# 2026-10-28网关配置、模型目录与最小GLM调用核对

用户提供完整Chat Completions地址、密钥和glm模型ID，要求核对配置。北京时间13:24完成检查；密钥只在本机以SHA-256等值比较，没有输出、改写配置或提交密钥。

## 配置结果

| 项目 | 实际核对结果 |
|---|---|
| OpenAI SDK base_url | `https://hub.zgci.org/v1` |
| 实际Chat请求路径 | `/v1/chat/completions`，无重复拼接 |
| 完整REST地址 | `https://hub.zgci.org/v1/chat/completions` |
| 请求模型ID | `glm` |
| 鉴权 | 本地optimizer/target密钥均与用户给定值一致；最小调用成功 |
| 认证模式 | 当前模板使用openai_chat后端、openai_compatible认证 |

SDK会在base_url后拼接chat/completions，因此不能把完整REST地址再填到SDK base_url。用户文字中的Markdown转义与行尾反斜杠不属于实际URL，项目实际配置未包含这些字符。

## 实测

一个不含实验任务的最小聊天请求，输出上限512，等待上限60秒，SDK自动重试关闭。约1.922秒返回HTTP200、正文OK、finish_reason=stop，响应model为 `glm-5.3-private-19428658`。记录输入20、输出40、缓存0 token。只有1次真实LLM调用，无重试，不修改原研究或采用模型生成内容。安全元数据见 [配置与聊天核对](HUB_CONFIGURATION_CHECK_20261028.json)。

网站首页及第一次直接GET模型目录出现ConnectError，网页浏览工具也未能访问首页；之后使用同一本地凭据通过SDK单独读取 `/v1/models` 成功。两个模型目录读取各最多一次，第二次是独立只读核对，不存在隐藏自动重试；GET模型列表不是LLM推理，不计入真实模型调用。安全模型目录见 [当前目录](HUB_MODELS_20261028.json)。

当前返回15个模型/服务ID：

- 文本或文本接口/路由别名：glm、glm-anthropic、qwen、gemma4:26b、smart-router、smart-router-v2。
- 其他服务ID：bge-m3、bge-reranker-v2-m3、cosy-voice、face-detect、face-embed、minimax-h3、qwen-asr、qwen-image、qwen3-embedding:4b。

目录可见不证明所有服务都完成调用验证，也不能把别名或路由当成独立固定模型。旧档案中的文本别名minimax未出现在本次目录，不能与minimax-h3混淆。此处其他服务用途分类沿用项目历史登记，本轮只验证glm普通聊天，未逐一调用其他服务。

## 实验边界

本次确认基础地址、凭据和glm模型ID正确，并证明普通聊天当前可用；不是原实验长请求的恢复证据。11:14用户授权的原失败分析请求仍返回data_inspection_failed/upstream_error，见 [长请求记录](GLM_RECHECK_20261028.md)。本轮没有再次重发该被拦内容，不能用最小OK响应解除实验暂停。

原study和冻结源码3f6d7de保持不变，修复仍在隔离分支等待新冻结版本应用。定时任务仍删除，正式实验和最终测试仍关闭。配置文档与安全汇总仅在隔离分支提交。
