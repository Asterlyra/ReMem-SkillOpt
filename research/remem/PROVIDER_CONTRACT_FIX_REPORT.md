# 上游错误分类与停止重复重试修复

用户在离线审计后要求继续，本轮按建议修复客户端，不调用真实模型、不恢复定时任务。修改在隔离 `codex/remem-response-audit` 分支，主运行目录仍保留源码3f6d7de和原冻结工件。当前网关 `data_inspection_failed` 尚未解决，四个未启动格继续保持停止。

## 行为与范围

此前HTTP200的错误封套会记录成unclassified，然后读取缺失choices触发TypeError，最多重复三次。现在研究调用在解析正文之前识别上游错误：

- `data_inspection_failed` 与 `DataInspectionFailed` 统一记录成安全类别 `data_inspection_failed`；原有已知认证、额度、上下文等不可重试类别共享同一白名单。
- 已知不可重试错误首次响应后抛出 `NonRetryableProviderError`，调用账本保留错误类型和白名单类别，队列按provider contract错误停止，不发送下一格。
- 暂时性服务错误仍可按既有限额重试。未知错误使用unclassified，最多原三次，错误不转换成正常正文或空提案；上游错误与看似正常choices同时存在时也按错误处理。
- 适用于优化器的普通/消息列表接口、Chat Completions/Responses路径，以及SpreadsheetBench target的两种API路径。运行时行为仅在研究call policy激活时改变；既有上游非研究路径保持原行为。

统一分类代码位于 `skillopt/remem/provider_contract.py`，不读取或保存原始错误message、请求正文、凭据。审计先记录安全元数据，再检查错误并中止，缺失token仍为null；不能把首次停止误报为正常无修改。

## 用量字段

保留旧 `successful_http_responses`（HTTP状态）和 `reported_usage_responses`（usage事件数）语义兼容，新增按响应ID关联的：

- `responses_with_numeric_usage`：实际HTTP响应有非负整数输入/输出用量。
- `responses_without_numeric_usage`：实际HTTP响应缺少上述可关联数值用量。
- `provider_error_http_responses`：审计明确记录了provider_error的HTTP响应数；这是已识别计数，不证明旧缺元数据记录没有其他错误。

没有把known-sum=0改成实际总用量；`usage_complete`和总token的保守口径保持不变。

## 验证结果

197项相关测试通过，覆盖ReMem全部测试、Azure兼容/用量、OpenAI-compatible后端/配置和凭据脱敏；最终修改后的针对性27项再次通过。新增测试覆盖大小写别名、四种优化器调用路径、两种target路径、已知错误只一次请求、暂态错误重试后成功、未知错误三次有界退出、错误优先于正常外形、调用账本类别保留与隐私，以及队列不得派发下一格。

真实SDK配合MockTransport的离线对照：此前同形合成错误3次模拟HTTP、2次重试；修复后1次、0重试，错误明确为 `NonRetryableProviderError/data_inspection_failed`，缺失用量保持null。正常合成响应仍1次成功。网络连接尝试和真实模型调用均为0。安全输出见 [修复后fixture](PROVIDER_CONTRACT_FIXED_FIXTURE.json)，此前基线见 [原fixture](GLM_OFFLINE_PROVIDER_FIXTURE.json)。模拟token/耗时不计入真实实验。

新增模块、审计/队列/fixture脚本、回归测试lint通过，diff检查与handoff检查通过。旧Azure文件lint从4项降为3项、codegen文件保留原12项，与HEAD逐项比较无新增告警，未为无关历史风格问题扩展重构。

## 应用边界

修复能减少无效调用并保留具体错误，不会解除上游数据检查，也不能判断命中内容或是否误报。本轮没有删任务、裁剪证据、修改提示/评分、切模型、放宽检查、重跑任何实验或重新创建定时巡检。

若后续要实际采用此代码，必须先保存旧版本完整审计，按用户确定的后续方案建立新冻结版本再verify；不能把它直接覆盖到现有study中，也不能把不同版本成绩拼成正式性能比较。在网关复核完成前不启动新的模型验证周期。
