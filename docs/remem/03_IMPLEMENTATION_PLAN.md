# 上游检查与分阶段修改计划

状态：计划；下面的新文件尚未实现。上游固定提交见 provenance.json，不追随移动的 main 开展正式实验。

## 1. 当前实现与角色

| 文件 | 当前职责 | 计划接入点 |
|---|---|---|
| skillopt/engine/trainer.py | rollout→reflect→aggregate→rank→update→evaluate 的主循环；step_buffer 和早退分支 | 执行结果分类后立即写失败事件；显式向提案器传上下文；评估后登记 attempt |
| skillopt/gradient/reflect.py | 成功/失败 minibatch 反思 | R schema、证据引用；M 上下文注入 |
| skillopt/gradient/aggregate.py | 合并多个编辑建议 | 保持 proposal/case/evidence ID 来源；禁止把批大小当单条支持数 |
| skillopt/optimizer/clip.py | 排序、限制编辑 | 接受经过验证的候选；保留审计原因 |
| skillopt/optimizer/skill.py | 应用 patch | 锚点/版本校验，冲突分离、幂等及失败归类 |
| skillopt/evaluation/gate.py | 选择门控 | 复用评估接口；按协议增加配对证据适配 |
| skillopt/envs/spreadsheetbench/prompts/analyst_error.md | 表格失败分析提示词 | 保留通用失败分类，增加结构化修复契约 |
| skillopt/model/azure_openai.py | 历史 openai_chat 兼容路径 | 检查当前返回值、空内容、重试、超时与角色配置 |

已检查的上游存在 skip_no_patches/skip_no_rewrite 分支，step_buffer 在 epoch 内维护。新代码不能仅在原 buffer 写入位置追加错题本，否则仍会漏掉早退。

上游已包含 `openai_compatible_backend.py`，可与历史 openai_chat 兼容模式比较；第一轮优先采用有历史任务证据的兼容模式，准备阶段再选择并冻结，不同时更换后端与研究机制。

## 2. 建议新文件结构

```text
skillopt/remem/                # 计划新增
  types.py                    # FailureEvent / FailureCase / RepairProposal / Attempt
  store.py                    # 原子写入、幂等事件、状态视图与重启恢复
  evidence.py                 # 来源、规则锚点、版本、训练 split 核验
  repair.py                   # 修复契约与操作到现有 patch 的编译
  budget.py                   # 去重、冲突与有界选择
  retrieval.py                # 任务/规则/类型检索和上下文预算
  context.py                  # 只允许的字段进入模型
  evaluation.py               # 逐题对齐、门控适配与缓存契约
configs/remem/                # 完成配置校验之后再生成可运行配置
scripts/remem/                # prepare/verify/run/report；现在只有交接检查
tests/remem/                  # 行为与集成验证
```

不要复制 CAM 的整个 trainer.py 覆盖新版上游。采用明确 hook/小函数，并尽量让默认开关关闭时保持上游行为。

## 3. 阶段与验收

### P0：项目与规范（本轮）

克隆、记录来源、文档、凭据空模板、机器可读协议和离线交接检查。没有性能结果。

### P1：存储与证据契约

实现事件落盘、版本绑定、去重、恢复、来源验证。用合成任务覆盖：无补丁仍保存；零提升仍保存；拒绝候选不关闭问题；task ID 不存在拒绝；test/val 证据不能作为训练来源；同一次事件重试不翻倍。

### P2：R 与 M 独立实现

R 的 prompt/schema/操作编译以及 M 的检索/上下文分别实现。冲突方案保留可诊断原因而非悄悄丢弃。明确区分 valid no_change、invalid output、服务异常。

### P3：trainer 集成与离线消融检查

运行真实 trainer 控制流配合 fake backend，覆盖正常、空补丁、无 rewrite、JSON 错误、候选拒绝、未确定、断点恢复。四个开关组合检查输入上下文；不能只测 helper。验证多个编辑的观测只归于组合。

### P4：准备环境和冻结

核查模型/费用/后端标识、标准库与表格依赖、数据文件、所有测试暴露 ID。准备与联调数据不进入最终测试。所有配置键必须通过解析器校验；不能假设未知键会生效。校准实际阶段耗时后冻结 18 或 21 次运行版本。

### P5：正式运行和报告

按冻结矩阵和种子顺序运行；基础设施失败按统一重试/中断规则处理，不填假零分；所有 final skill 固定后一次性进入最终测试。完成结果、代价、机制、局限说明。没有相应证据不得标 complete。

## 4. 实现优先级

先保证记录不丢和来源不伪造，再优化 prompt 与检索。第一轮不引入学习式检索器、embedding 服务、复杂树搜索或新的自动改写通道。阶段完成不等于论文有效；最终收益需要正式对照。
