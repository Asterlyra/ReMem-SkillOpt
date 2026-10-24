# 本地环境与数据准备

2026-10-23：在独立 `.venv` 中使用 Python 3.12；没有更改已有 Conda 环境。
版本快照在 `research/remem/environment-windows-py312.txt`。安装步骤：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r research/remem/environment-windows-py312.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-remem.txt
.\scripts\remem\python.ps1 scripts/remem/prepare_data.py
.\scripts\remem\python.ps1 scripts/remem/verify_environment.py
```

`prepare_data.py` 固定 Hugging Face revision
`ab0b742b0fc95b946f212d80ac7771b5531272e4`，先验证压缩包 SHA-256，
再解压、检查工作簿可读性、任务配对和 80/40/280 划分。
已有文件不一致时报错，不覆盖实验工件。`--offline` 可用已下载压缩包重做验证。

源数据遵循 CC-BY-SA-4.0，来源为
https://huggingface.co/datasets/KAKA22/SpreadsheetBench 。
压缩包 SHA-256：`10ef893dd29cb13ab97143ea787e68cdc9574a13873ab9a54e50b31dc03fc949`。

原始文件保存在忽略目录 `data/spreadsheetbench_verified_400`。
运行副本位于 `data/spreadsheetbench_remem_400`：任务 42930 的原文件名
`1_43930_golden.xlsx` 在副本中增加 `1_42930_golden.xlsx` 别名，内容字节不变。
完整映射、原始及运行文件哈希保存在 `data/remem_data_manifest.json`。
五题使用的裸 `initial.xlsx/golden.xlsx` 格式由上游加载器原生支持。

`data/spreadsheetbench_split` 是完整数据的上游划分。历史 CAM 的 483 个
`results.jsonl` 中，当前 280 题 test 池全部出现，不能再从中抽取未执行最终测试。
只按任务 ID 与文件哈希完成的审计见 `research/remem/exposure_audit.json`，未读旧成绩。

另从同 revision 的原始 912 题包中取出 Verified 400 之外的 512 题；旧运行结果
没有这些 ID。固定种子抽取 120 题，形成新的 80/40/120 运行副本，
保存在 `data/spreadsheetbench_fresh_240_runtime` 与
`data/spreadsheetbench_fresh_split`，清单为 `data/remem_fresh_test_manifest.json`。
输入/答案工作簿可读且配对完整；跨集合无完全相同的输入工作簿、题目文本或
Jaccard≥0.8 的题目文本。原始 512 题未经 Verified 人工校验，来源模板分组未得到证明；
这批 120 题是候选 holdout，正式结论必须报告质量和历史暴露范围限制。

复核候选数据的命令：

```powershell
.\scripts\remem\python.ps1 scripts/remem/audit_exposure.py
.\scripts\remem\python.ps1 scripts/remem/prepare_fresh_test.py
.\scripts\remem\python.ps1 scripts/remem/audit_templates.py --runtime data/spreadsheetbench_fresh_240_runtime --split-dir data/spreadsheetbench_fresh_split --output research/remem/fresh_template_audit.json
```

准备脚本拒绝覆盖已有运行副本；复核已生成数据使用 study `verify`。

环境验证只执行合成表格程序与评分器，不读取测试成绩。DeepSeek 小样本探活
及调用用量见模型档案和准备报告；正式协议、外部对照和测试发布仍未冻结。

后续命令使用 `scripts/remem/python.ps1`，它为当前进程启用 UTF-8，避免上游部分
未指定编码的文件读写受 Windows 系统代码页影响；退出后恢复原环境变量。
