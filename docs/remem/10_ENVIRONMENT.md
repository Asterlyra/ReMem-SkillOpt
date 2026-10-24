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

`data/spreadsheetbench_split` 是完整数据的上游划分，不是已冻结的 ReMem 划分。
280 题 test 仅是候选池；历史测试暴露、来源/模板跨集合泄漏尚须审计，
不能声明已经获得 120 道未暴露最终测试题。

环境验证只执行合成表格程序与评分器，不调用模型、不读取测试成绩。
模型凭据、后端身份、吞吐、费用与正式协议仍须后续联调和冻结。

后续命令使用 `scripts/remem/python.ps1`，它为当前进程启用 UTF-8，避免上游部分
未指定编码的文件读写受 Windows 系统代码页影响；退出后恢复原环境变量。
