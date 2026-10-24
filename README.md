# ReMem-SkillOpt

**Evidence-Guided Repair with Persistent Failure Memory for Agent Skill Optimization**

在 Microsoft SkillOpt 上研究两个相互配合的模块：**R：证据驱动的受控修复**与 **M：持续失败与修复记忆**。模型权重保持冻结，优化对象为可复用的 skill 文本。

> **当前状态：独立环境、数据准备、R/M 策略与 trainer 离线集成已建立；正式实验尚未运行。** 开发版框架支持固定核心任务计划、冻结校验和只读报告。本仓库不提供 ReMem 性能结论。

## 从这里开始

- **[START_HERE.md](START_HERE.md)**：新 Codex 项目的阅读入口。
- **[HANDOFF.md](HANDOFF.md)**：已经确定的方向、下一步和可直接使用的接续提示词。
- [研究背景](docs/remem/01_BACKGROUND.md) · [方法与数据契约](docs/remem/02_METHOD.md) · [修改计划](docs/remem/03_IMPLEMENTATION_PLAN.md)
- [实验协议](docs/remem/04_EXPERIMENT_PROTOCOL.md) · [指标定义](docs/remem/05_METRICS.md)
- [模型接入档案](docs/remem/06_MODEL_REGISTRY.md) · [相关文献](docs/remem/07_RELATED_WORK.md)
- [CAM 复用地图](docs/remem/08_CAM_REUSE.md) · [复现要求](docs/remem/09_REPRODUCIBILITY.md)
- [环境配置](docs/remem/10_ENVIRONMENT.md) · [框架实现与验收](docs/remem/11_FRAMEWORK.md)

## 方法范围

| 模块 | 内部机制 | 目标 |
|---|---|---|
| R | 证据与修复操作关联；来源核验、去重、冲突处理和编辑预算 | 每次修改有明确依据，修改规模可控 |
| M | 独立失败事件与问题状态；关联修复尝试及其结果 | 无提升、无补丁或候选拒绝时仍保留未解决问题 |

配对评估门控负责是否采用候选，不决定错误是否记录。问题状态绑定采用的 skill 版本，候选中解决不等于当前版本已解决。

## 实验设计草案

核心 2×2：R0M0、R1M0、R0M1、R1M1，各 3 个 seeds，共 12 次优化。加 SkillOpt、CAM 与 AtomSearch 的预算匹配对照，推荐 21 次；准备阶段可冻结为 18 次版本。SpreadsheetBench、80 训练/40 选择/120 测试，6 步包含固定题目重现；历史测试暴露必须先核查。

正式运行目标 48–72 小时，包含最终测试和报告，不含实施、环境搭建与联调。时间来自历史观测外推，需在准备阶段校准；不是完成时限保证。完整协议以文档和未来 freeze 为准。

[study_design.json](research/remem/study_design.json) 是机器可读研究规格，**不能直接传给 train.py**。

## 上游与参考

- 代码基础：[microsoft/SkillOpt](https://github.com/microsoft/SkillOpt)，固定提交 `1a44050fc53aa4938a7a3927b6cca550491bfe51`。
- 原说明：[UPSTREAM_README.md](UPSTREAM_README.md)。保留 SkillOpt 包名、CLI、原代码和许可证。
- 参考工程：[Lutra11/CAM-SkillOpt](https://github.com/Lutra11/CAM-SkillOpt)。仅有选择地迁移，不整仓覆盖。
- [来源与文件哈希](research/remem/provenance.json) · [文献 BibTeX](research/remem/references.bib)。

## 离线交接检查

```powershell
python scripts/remem/validate_handoff.py
```

该命令只检查文档、链接、研究矩阵、来源和空凭据模板，不训练、不调用模型。后续安装与原框架使用参见上游说明；ReMem runner 尚未实现。

## 模型与凭据

历史主组合为 `qwen` 执行、`glm` 修改，经 OpenAI-compatible 网关调用；模型标识、参数与限制见模型档案，当前未重新探活。使用 [空密钥模板](research/remem/model.env.example)，将真实凭据放在受忽略的本地 `.env`，不要上传。

## 许可证

[MIT](LICENSE)。保留 Microsoft SkillOpt 原版权声明；后续复用 CAM 代码时记录来源并保留适用条款。
