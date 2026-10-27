# 2026-10-27 16:52 glm失败请求复查

用户要求再次检查。只读核对当前队列和进程后，单独重建了SkillOpt第二步未完成的第一个失败minibatch：训练结果使用相同seed43分组、原skill、原native step_buffer和原analyst提示，输出上限16384、HTTP超时240秒。重建请求正文93,388字节，与此前三次异常请求的记录大小一致；旧请求未存消息哈希，不能宣称逐字节同一请求。所用任务均校验属于训练注册表，未加入测试内容。

本次只发送一次独立检查请求，0重试、0新增任务执行；不修改原失败格，也不采用此次结果。约15.406秒后再次得到HTTP200错误封套，无model、choices、正文、usage。这次在内存中提取到可安全记录的错误码 `data_inspection_failed`、类型 `upstream_error`，没有保存或提交原始网关封套、错误消息、请求正文或凭据。记录见 `GLM_CONTENT_INSPECTION_RECHECK.json`。本次token和缓存用量均未知，不能将known-sum=0当实际免费调用。

阿里云Model Studio的[官方错误码说明](https://help.aliyun.com/en/model-studio/error-code)将 `DataInspectionFailed/data_inspection_failed` 定义为输入或输出可能触发内容安全检查。本项目使用的是hub网关及glm别名，类型又被包装为upstream_error，因此只能说本次错误码指向数据/内容检查环节：不能据此确认底层供应商、哪段内容被命中、输入还是输出被拦截，也不能断言是误报。HTTP200不足以表示模型成功。

这一证据比此前“响应异常/等待服务恢复”更具体：应请网关服务方核对该请求的内容检查结果与兼容封套，而不是仅确认内网或短OK请求可达。当前仍保持 `stopped_malformed_provider_response`，后续四组未启动，不对相同失败内容循环重试，不擅自删训练任务、删轨迹证据或更换模型来绕过检查。若合规复核后恢复，再评估同冻结版本仅接续未启动四格；任何数据/提示/模型变更均须独立协议和新冻结版本。

本轮未修改执行源码，当前freeze再次verify通过。实际运行源码仍为3f6d7de，报告只提交隔离分支；正式实验及最终测试继续关闭。
