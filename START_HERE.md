# ReMem-SkillOpt：新项目入口

本项目从 Microsoft SkillOpt 重新克隆，**不是 CAM 工作目录的复制品**。当前完成的是研究方案、工程交接与实验规格；ReMem 的两个模块尚未实现，也没有开始模型实验。

工作标题：**ReMem-Skill: Evidence-Guided Repair with Persistent Failure Memory for Agent Skill Optimization**。

## 已确定的方向

1. **R：证据驱动的受控修复**，合并原 A（有依据的修复操作）和 D（证据约束的编辑预算）。
2. **M：持续失败与修复记忆**，合并原 B（独立错题本）和 C（修改历史记忆）。

配对评估门控是公共质量控制，不包装为第三个创新模块。仍使用冻结的执行模型与优化器模型，只优化 skill 文本。

## 新 Codex 项目的阅读顺序

1. [交接与下一步](HANDOFF.md)
2. [研究背景和问题定义](docs/remem/01_BACKGROUND.md)
3. [两模块方法与数据契约](docs/remem/02_METHOD.md)
4. [上游检查与修改路线](docs/remem/03_IMPLEMENTATION_PLAN.md)
5. [完整实验协议草案](docs/remem/04_EXPERIMENT_PROTOCOL.md)
6. [指标与分析口径](docs/remem/05_METRICS.md)
7. [可用模型及接入历史](docs/remem/06_MODEL_REGISTRY.md)
8. [近期文献及相似工作](docs/remem/07_RELATED_WORK.md)
9. [CAM 复用地图](docs/remem/08_CAM_REUSE.md)
10. [可靠性、数据与冻结要求](docs/remem/09_REPRODUCIBILITY.md)

机器可读规格：[研究设计 JSON](research/remem/study_design.json)。它是**未冻结的实验规格，不是 train.py 可直接加载的配置**。

## 基础仓库

- 上游：[microsoft/SkillOpt](https://github.com/microsoft/SkillOpt)，固定提交 `1a44050fc53aa4938a7a3927b6cca550491bfe51`。
- CAM 参考：[Lutra11/CAM-SkillOpt](https://github.com/Lutra11/CAM-SkillOpt)。本地参考代码与远端提交不完全一致，见复用地图与来源清单。
- [原版 SkillOpt README](UPSTREAM_README.md) 和原 MIT 许可证保留。
- Git `upstream` 指向 Microsoft；`cam-reference` 只作为参考远端；`origin` 指向新建的用户仓库。

## 当前能做什么

可以阅读方案，审查上游调用链，按阶段实现并做离线验证。不能把计划文件中的模块路径当成已实现，也不能直接用旧 CAM 训练命令启动本项目。

在仓库根目录执行 `python scripts/remem/validate_handoff.py` 可检查交接文件、研究矩阵和凭据模板；该检查不调用模型。

环境密钥模板位于 [research/remem/model.env.example](research/remem/model.env.example)，没有任何真实密钥。历史模型档案不代表当前网关已再次探活。

本轮交付与验证记录：[BOOTSTRAP_REPORT.md](research/remem/BOOTSTRAP_REPORT.md)。
