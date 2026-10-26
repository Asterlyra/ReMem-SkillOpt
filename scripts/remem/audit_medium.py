"""Read-only operational audit of the user-selected medium diagnostic."""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from skillopt.remem.study import report
from skillopt.remem.transport_audit import summarize


def load_records(path):
    if not path.exists():
        return []
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        return [(kind, json.loads(body)) for kind, body in db.execute("SELECT kind,payload FROM records ORDER BY seq")]


def audit(directory):
    freeze = json.loads((directory / "freeze.json").read_text())
    rows = report(directory)
    for row in rows["runs"]:
        folder = directory / "runs" / row["run"]
        events = load_records(folder / "remem/ledger.sqlite3")
        calls = load_records(folder / "remem/calls/ledger.sqlite3")
        row["event_counts"] = dict(Counter(k for k, _ in events))
        row["training_by_step"] = dict(Counter(p["step"] for k, p in events if k == "observation"))
        row["training_failure_by_step"] = dict(
            Counter(p["step"] for k, p in events if k == "observation" and p["outcome"] == "failure")
        )
        row["context_history_groups"] = [
            dict(step=p["step"], groups=p["history_groups"]) for k, p in events if k == "context"
        ]
        row["attempt_actions"] = [
            dict(step=p["step"], action=p["gate_action"], adopted=p["adopted"]) for k, p in events if k == "attempt"
        ]
        row["cam_final_actions"] = [
            dict(step=p["step"], action=p["audit"]["result_action"], group_guard=p["audit"]["group_guard"]["status"])
            for k, p in events
            if k == "cam_gate"
        ]
        row["cam_retrieval"] = [
            dict(step=p["step"], hit_count=p["hit_count"], status=p["status"]) for k, p in events if k == "cam_context"
        ]
        row["cam_budget_reasons"] = [
            dict(step=p["step"], reason=p.get("reason"), budget=p["budget"]) for k, p in events if k == "cam_budget"
        ]
        row["optimizer_call_errors"] = dict(
            Counter(p.get("error_type", "unspecified") for k, p in calls if k == "error")
        )
        row["optimizer_format_errors"] = sum(k == "format_error" for k, p in calls)
        row["limits_reached"] = sum(k == "limit" for k, p in calls)
        row["test_executions"] = sum(p["tasks"] for k, p in events if k == "rollout_started" and p["phase"] == "test")
        row["memory_validation_id_matches"] = []
        ledger = folder / "remem/ledger.sqlite3"
        split_dir = Path(__file__).resolve().parents[2] / freeze["split_dir"]
        validation = {str(r["id"]) for r in json.loads((split_dir / "val/items.json").read_text())}
        if ledger.exists():
            with sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True) as db:
                for kind, payload in events:
                    if kind not in ("context", "cam_context", "optimizer_started") or "artifact_hash" not in payload:
                        continue
                    saved = db.execute(
                        "SELECT body FROM artifacts WHERE hash=?", (payload["artifact_hash"],)
                    ).fetchone()
                    artifact = json.loads(saved[0])
                    memory = artifact.get("history", artifact.get("context", artifact.get("outcome_memory", {})))
                    text = memory if isinstance(memory, str) else json.dumps(memory, ensure_ascii=False)
                    matches = [identity for identity in validation if json.dumps(identity) in text]
                    if matches:
                        row["memory_validation_id_matches"].append({"step": payload.get("step"), "count": len(matches)})
        transport = folder / "remem/transport.jsonl"
        if transport.exists():
            raw = [json.loads(x) for x in transport.read_text().splitlines() if x]
            usage = [x for x in raw if x["kind"] == "usage"]
            row["transport"] = summarize(transport)
            row["response_models_by_role"] = {
                role: sorted(
                    {
                        x["response_model"]
                        for x in usage
                        if x["role"] == role
                        and isinstance(x.get("response_model"), str)
                        and x["response_model"].strip()
                    }
                )
                for role in ("target", "optimizer")
            }
            row["response_model_missing_by_role"] = {
                role: sum(
                    x["role"] == role
                    and (not isinstance(x.get("response_model"), str) or not x["response_model"].strip())
                    for x in usage
                )
                for role in ("target", "optimizer")
            }
            row["finish_reasons"] = dict(Counter(str(x["finish_reason"]) for x in usage))
    rows.update(study_id=freeze["study_id"], source_git_head=freeze["git_head"], test_released=False)
    (directory / "operational_audit.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# 内网中等规模诊断：运行证据",
        "",
        "这是准备阶段诊断；最终测试未开放。七个方法的失败尝试和缺失用量均保留。",
        "",
        "| 方法 | 状态 | 已启动任务 | 已记录训练观察 | 无更新 | 非法提案记录 | 基础设施失败记录 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    issues = []
    for row in rows["runs"]:
        observations = row.get("event_counts", {}).get("observation", 0)
        lines.append(
            f"| {row['run']} | {row['status']} | {row['task_executions']} | {observations} | {row.get('no_change')} | {row.get('proposal_invalid')} | {row.get('infra_failures')} |"
        )
        if row.get("proposal_invalid"):
            issues.append(
                f"{row['run']}：存在 {row['proposal_invalid']} 条非法提案记录，须区分输出 schema 与证据引用错误。"
            )
        if row.get("infra_failures") or row.get("optimizer_call_errors"):
            issues.append(f"{row['run']}：存在基础设施/服务错误，不能当成 skill 错误或正常完成。")
        if row.get("memory_validation_id_matches"):
            issues.append(f"{row['run']}：模型可见记忆出现验证 ID 字面匹配，需要检查来源；本检查不是完整语义泄漏证明。")
        if row["run"].startswith(("core_00_", "repair_only_")) and any(
            r["groups"] for r in row["context_history_groups"]
        ):
            issues.append(f"{row['run']}：关闭 M 后仍有历史组，违反消融隔离。")
        if row.get("transport") and not row["transport"]["usage_complete"]:
            issues.append(f"{row['run']}：用量尚不完整，不能把已知 token 当总用量。")
        if row.get("finish_reasons", {}).get("length"):
            issues.append(f"{row['run']}：有输出长度截断，需核查空正文/格式错误及输出上限。")
        if any(len(v) > 1 for v in row.get("response_models_by_role", {}).values()):
            issues.append(f"{row['run']}：同角色返回多个模型标识，需核查身份漂移。")
        if any(row.get("response_model_missing_by_role", {}).values()):
            issues.append(f"{row['run']}：有响应缺少模型标识；缺失与有效身份分别记录，不能证明身份完整。")
        if row.get("task_executions") and row["task_executions"] > 160:
            issues.append(f"{row['run']}：任务执行数超过共同 160 上限。")
    lines += ["", "## 当前需要核查的事项", ""] + ["- " + issue for issue in issues]
    if not issues:
        lines.append("当前自动检查尚未发现上述运行异常；仍须等待全部运行结束并审查真实提案语义。")
    lines += [
        "",
        "## 结论边界",
        "",
        "单 seed 和准备阶段验证集不足以证明方法优劣；需区分结构合法与诊断成立。公式任务中“写入计算值以避免缓存为空”的修复需要对照原任务语义审查。",
        "CAM 使用 result_action 作为最终动作。AtomSearch 的最终推荐和 best-validation 分别保留，不根据测试结果改选。",
        "同模型生成的不确定性、验证起点差异、记忆检索覆盖、预算停止与调用缺失均应在人工审查中解释。",
        "实际运行参数、模型身份、源码和任务顺序见 freeze.json；详细状态见 operational_audit.json、queue.json。",
        "",
    ]
    (directory / "DIAGNOSTIC_REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "study_id": freeze["study_id"],
                "runs": [{"run": r["run"], "status": r["status"], "tasks": r["task_executions"]} for r in rows["runs"]],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    audit(parser.parse_args().directory.resolve())
