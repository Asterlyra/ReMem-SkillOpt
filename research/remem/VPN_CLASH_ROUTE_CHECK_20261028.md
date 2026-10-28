# VPN与Clash路径核查

2026-10-28 17:37，北京时间。用户提出内网VPN与聊天用Clash冲突的可能性。本轮仅检查本机配置、路由和两次无鉴权GET；没有模型推理、实验任务、失败分析请求重放或系统设置变更。

## 已观察到的路径差异

进程HTTP_PROXY/HTTPS_PROXY指向127.0.0.1:7890，本地监听进程为FlClashCore。系统代理同样开启，但例外列表已有hub.zgci.org和gateway.zgci.org。WinHTTP为直连。环境变量中的显式代理与Windows系统例外列表不能混为一谈。

hub.zgci.org的DNS别名为gateway.zgci.org，解析为10.1.132.25；Windows为该地址选择Sangfor aTrust VNIC的10.1.0.0/16路由。Clash的Wintun网卡当前未连接，内网aTrust网卡已连接。

同一HTTPS地址/v1/models，TLS验证开启、无鉴权、各一次GET：

| 方式 | 观察 |
|---|---|
| 显式使用127.0.0.1:7890的Clash代理 | ConnectError，约10.391秒 |
| 不使用HTTP代理，沿操作系统VPN路由直连 | 建立TLSv1.3，到达10.1.132.25:443，收到JSON类型HTTP401，约0.203秒 |

401符合本次故意不发送密钥的检查方式，证明直连可到达服务，不能解释为实验密钥失效，也不能作为模型分析请求恢复的证明。没有读取或发送密钥。

原始诊断元数据：主目录outputs/remem/vpn-clash-check-20261028T093734Z/metadata.json。直连收到HTTP401后，辅助证书摘要采集对None计算哈希产生TypeError，因此该条记录并非完整正文检查；socket地址、TLS版本及HTTP状态在辅助错误前已取得，仍是有效的连接证据。已修正忽略目录诊断工具的None检查，没有修改实验源码，也没有为此重复网络请求。辅助错误已明确保留，不能冒充网络连接失败或隐去。

## 当前实验是否仍走Clash

忽略的.env.intranet.local已包含NO_PROXY=hub.zgci.org，两角色端点均为https://hub.zgci.org/v1。冻结实现skillopt/remem/study.py的execute_config在创建客户端前，将该主机加入本次进程的NO_PROXY及no_proxy，退出时恢复原环境。不会修改聊天进程或全局代理。

本轮无网络地复用相同环境加载逻辑，检查HTTPX为目标URL选择的transport，确认选中直接transport，未选择代理transport。HTTPX官方文档说明[NO_PROXY对指定URL禁用代理](https://www.python-httpx.org/environment_variables/)。本地配置、运行代码及当前选择相符，无需关闭Clash或修改系统全局代理。

结论：通过Clash连接内网站点当前确实失败，实验已有的进程内直连配置是合适的处理。但旧实验transport没有记录socket路径，不能追溯证明当时的操作系统VPN状态；当前对照也不能证明旧data_inspection_failed由代理导致。旧错误是服务端实际返回的明确错误封套，仍须保留其分类。此次未重放旧内容，未把普通连接成功当成内容检查问题已解决，原队列保持停止。

安全后续：实验继续使用已生效的主机级直连配置；若其他工具访问内网失败，应为那些工具单独应用相同的主机级代理例外。当前没有证据支持修改数据、关闭内容检查、替换模型或直接resume原保护停止队列。
