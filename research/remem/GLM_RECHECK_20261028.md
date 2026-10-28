# 2026-10-28用户授权的单次GLM请求验证

用户要求“请你请求，如果没问题继续实验”。北京时间2026-10-28 11:14:17发起独立验证，约11:14:33结束；结果未通过，因此没有继续试跑、合入运行修复或建立新study，定时任务仍保持删除。

## 请求与结果

只读重建此前SkillOpt第二轮失败训练minibatch，沿用原skill、失败轨迹、历史摘要与analyst提示。请求别名glm，输出上限16384，HTTP等待240秒；只发送1次请求，SDK隐藏重试关闭，没有应用层重试，没有新增任务执行或测试内容。

请求正文93,388字节，消息SHA-256为 `7a3fbe725d7c6d94b6b209e78176f2406a21ca46ff5474a82a7cedca537bb9a5`，与2026-10-27独立复查的重建消息哈希一致。旧实验原请求没有保存消息哈希，仍不能声称与原始失败请求逐字节相同。

15.375秒后返回HTTP200错误封套：`error.code=data_inspection_failed`、`error.type=upstream_error`。model、choices、正文、usage均缺失。HTTP200不代表成功，不能证明当前GLM实验负载已恢复；输入还是输出检查、具体命中内容及是否误报仍无法确认。

本次1个逻辑调用、1次实际HTTP、0重试，token和缓存未知；known-sum=0不能作为实际零消耗或免费的证据。安全元数据见 [本次验证](GLM_RECHECK_20261028.json)，本地完整transport元数据位于 `outputs/remem/glm-long-request-recheck-20261028T031417Z/transport.jsonl`。未保存原始错误封套、错误message、请求正文或凭据，也未产生有效模型回答。

## 后续处置

原研究仍保持 `stopped_malformed_provider_response`，四个未启动格保持未启动。复查前后主目录freeze验证通过，原账本、transport、queue和冻结文件未变。客户端修复仍在隔离分支，不能解除上游检查；不重复发送相同被拦内容、不通过删任务/裁剪轨迹/切换模型规避检查。

本次用户授权的“若成功则继续”条件未满足，未启动新的验证或恢复周期。网关管理员可按上述北京时间、模型别名、正文规模和错误码复核，参见 [网关排查单](GLM_GATEWAY_REVIEW_BRIEF.md)。没有新的可核验request_id，不补造请求号。
