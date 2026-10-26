# 旧 CAM 预算事件缺少 step 的兼容修正

2026-10-27 01:52 巡检确认 v2 的 CAM 在第二步 analyst 服务错误后终止；其后只读报告器把旧 cam_budget 载荷中的 step 当作必有字段，引发 KeyError。调度器按 r2 的显式错误路径记为 stopped_reporting_failure 并退出，未继续派发 M-only；原事件、错误和输出保留。

报告修正使用可空的 step，旧记录继续标缺失，不补写或猜测为 0。未来版本的 NativeControlRuntime 将明确保存 CAM 预算事件的 step；该实验源码改动仍待 v2 终止后合入。回归覆盖混合空模型身份/用量、旧预算载荷缺字段以及新 trainer 产生的预算事件确有步骤号。

运行控制与报告辅助脚本以 orchestration-r3 另存哈希清单，v2 模型执行源码、提示词、配置及主 freeze 不变。确认全部旧进程终止并 verify 后，仅接续尚未启动的 M-only。已完成或失败的六格保持原结果，不因报告修正重跑。服务失败格的独立恢复仍按既有后续计划进行。
