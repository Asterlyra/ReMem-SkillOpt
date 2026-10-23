# 相关研究与借鉴边界

核查日期：2026-10-23。以下均链接论文原文；这是方法导读与比较地图，不复制论文全文，也不把预印本自动当作已同行评审结果。题名、首次提交日期按 arXiv 核对。

## 1. SkillOpt（2026-05-22）

[SkillOpt: Executive Strategy for Self-Evolving Agent Skills](https://arxiv.org/abs/2605.23904)，[代码](https://github.com/microsoft/SkillOpt)。

将 skill 当成冻结模型的外部可优化状态，通过轨迹反思提出有界文本编辑，用验证反馈选择版本，辅以拒绝编辑缓冲和慢/元更新。它已有编辑语法与预算，所以不能把 ReMem 描述成首次规范 skill 编辑。复用其执行环境与训练框架；补充的是证据到具体修复操作的约束和独立的持续失败生命周期。实验需注明关闭 slow/meta 的预算匹配版本与原论文全配置的差异。

## 2. SkillMorph（2026-10-08）

[Trajectory-Guided Fault Localization for Agent Skill Evolution](https://arxiv.org/abs/2610.11858)。

方法名 SkillMorph。通过多次任务执行中的成功/失败证据定位可疑行为，再定位 skill 编辑位置。对 R 的启发是把“执行证据→可疑动作→目标规则”显式化。它已经处理轨迹定位问题，不能声称仅增加 rule_id 和 evidence_refs 就构成独有贡献。ReMem 的目标还包括未解决问题跨修复尝试的维护，效果需要单独验证。

## 3. SkillHEX（2026-08-06）

[SkillHEX: Improving Agent Skills via Hypothesis-Driven Autonomous Exploration and Exploitation](https://arxiv.org/abs/2608.05628)。

把失败解释变成可证伪假设和可执行检查，并借助持久修订分支搜索处理稀疏结果反馈。可借鉴“假设不是事实”和诊断证据；第一版不搬入完整树搜索。论文的 test-time、有限反馈设定与本项目 train/selection/test 划分不同，不能直接混合成绩或声称诊断检查没有成本。

## 4. ContractSkill（2026-03-20；4 月更新）

[ContractSkill: Repairable Contract-Based Skills for Multimodal Web Agents](https://arxiv.org/abs/2603.20340)。

将隐式 web skill 转成显式可执行结构，使检查、定位与局部修复更可操作。借鉴前置条件、步骤和结果检查的思想。它面向多模态网页环境，不证明同一契约形式能直接泛化到自由文本表格 skill；ReMem 采用轻量规则锚点和修复类型，不全面重写执行器。

## 5. SkillRevise（2026-05-31；2026-09-03 v4）

[SkillRevise: Improving LLM-Authored Agent Skills via Trace-Conditioned Skill Revision](https://arxiv.org/abs/2606.01139)。

利用执行证据诊断初始 skill 缺陷，检索修复原则并作有执行依据的修改。说明“轨迹诊断+记忆+修复”已有近邻工作。本项目的实例化失败记录与修复尝试历史不同于一般修复原则库，但这种区别需在流程与消融中体现，不能只靠换名。

## 6. AtomSearch（2026-10-14，最近邻优先）

[AtomSearch: Evidence-Grounded Tree Search for Agent Skill Optimization](https://arxiv.org/abs/2610.19951)，[方法与预算附录](https://arxiv.org/html/2610.19951v1)。

将单条编辑关联失败/成功证据、行为假设和适用范围；在完整 skill 状态上树搜索，保留有价值的后续组合；用结果记忆提供修复与退化反馈。它已经覆盖原子编辑、结构验证和修改记忆，正面限制了 ReMem 的新颖性主张。

因此主实验纳入同执行预算对照。ReMem 候选研究点是门控独立的未解决失败维护与线性有界修复在小预算下的效果，不声称首次 evidence-grounded editing。官方代码可获得性和版本需要在实施阶段核验；自行实现时标为 reproduction，不能冒充官方结果。

## 7. COBRA-Skills（2026-09-10）

[COBRA-Skills: Contextual Bandit-Guided Evolution for Agent Skill Optimization](https://arxiv.org/abs/2609.11682)。

把技能演化作为预算约束的序贯优化，按候选潜力和信息价值分配执行评估。对预算公平性和效率曲线有启发。第一轮不引入 bandit，以保持 R/M 机制清晰；若未来主张优化成本优势，需要进一步考虑与该类方法比较。

## 比较时应明确

| 机制 | 已有近邻 | 本项目要验证的内容 |
|---|---|---|
| 文本编辑优化 | SkillOpt | 证据约束是否改善修改 |
| 轨迹定位 | SkillMorph、SkillRevise | 与持续失败记录结合后的作用 |
| 可验证修复 | ContractSkill、SkillHEX | 轻量文本规则中是否足够有效 |
| 原子编辑与结果记忆 | AtomSearch | 有限预算下的实例失败生命周期与效果 |
| 评估预算分配 | COBRA-Skills | 首轮不作为独立贡献 |

引用条目见 [references.bib](../../research/remem/references.bib)。文献相关性不等于可发表性结论；方法重叠和负结果必须在论文中保留。
