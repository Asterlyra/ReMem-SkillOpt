# CAM-SkillOpt 参考与复用地图

- 公开仓库：https://github.com/Lutra11/CAM-SkillOpt
- 本地只读参考：`E:\Programs\CAM\CAM-SkillOpt`
- 本地 Git HEAD：`016e7efbcec168b25b0e3032c125e6e3a3f8a284`
- 当前本地工作树不干净，包含更新/新增/删除；远端 HEAD 不能代表本地 v3/v3r1 全部内容。关键文件哈希在 [provenance.json](../../research/remem/provenance.json)。

本次只保存参考与来源，不复制整个 CAM 源码，不修改旧目录。若本地文件缺失，先比较公开版本，不能默认为同一实现。

## 可复用部分

| CAM 文件 | 价值 | 迁移时必须调整 |
|---|---|---|
| skillopt/cam/bootstrap_gate.py | 逐题配对的三路门控 | 接入新上游评分与缓存；区分不确定和失败；不控制错题入库 |
| skillopt/cam/selection_guard.py | 任务 ID、版本与证据一致性 | 路径/字段适配，不能静默退回标量证据 |
| skillopt/cam/adaptive_budget.py | 去重、明确目标冲突、独立任务来源 | 只迁移 evidence_v3 思路；单例可核验缺陷不能被误删；允许少于下限 |
| skillopt/cam/rejected_memory.py | accepted/rejected/inconclusive、版本哈希、组合归因 | 转成 RepairAttempt；另建独立 FailureCase/Event，不再让入库依赖 edits |
| skillopt/cam/memory_context.py | 过去步骤、任务范围和上下文检索 | 来源限于训练；分别检索问题与修复，避免零分差历史被压低 |
| model/azure_openai.py 的本地修复 | 空响应、异常响应、重试类型化经验 | 与新上游 diff 后迁移，避免退化其新后端能力 |
| tests/test_cam_v3_* 与 response_contract/integrity 测试 | 有意义的边界场景 | 转写到 ReMem 契约，不机械复制旧阈值或全部测试 |

## 不直接迁移

- 整个 trainer.py、旧 freeze/queue、运行 PID、自动化/巡检任务、旧结果目录和密钥。
- 早期“失败分布越集中→编辑更多”的预算公式。
- 用绝对 score_delta 作为历史价值的唯一权重。
- 把分数发生变化的验证 ID 当成支持训练修复的因果证据。
- 慢更新/元更新的所有支路；首轮先统一关闭以减少混淆。

## 历史结果与可靠性经验

旧 v3 四格：baseline42=68/120、CAM42=64/120；baseline43=65/120、CAM43=70/120。平均差约 +0.42pp，方向相反。旧报告明确七次辅助生成缺失和 prompt 冻结遗漏，不能从中声称稳定优势或干净机制归因。

旧诊断 8/8 步来源未知回退；这支持新 R 保留来源链的工程必要性，但不是 R 会提高准确率的证据。

时间依据：baseline42 训练 5763.4s+测试903.5s；CAM42 5860.1s+900.4s；CAM43 4799.0s+931.5s；baseline43 4710.4s+798.0s。每格四步，训练 batch20、选择40、测试120。新六步估时只能作外推。

来源文件：`reports/continuous_adaptation_v3/FINAL_SUMMARY.md`、`report.md`、`reports/cam_v3r1_runtime_diagnostics/DIAGNOSIS.md`、`REPAIR_REPORT.md`。关键事实已汇总到新项目，不要求新工作区依赖旧报告才能理解方案。

## 复用记录要求

每次迁移记录源路径、源 SHA-256、公开提交（若存在）、目的路径、行为差异和验证。保留 Microsoft/CAM 适用版权与 MIT 条款；当前仅文档引用不冒充已经迁移算法。
