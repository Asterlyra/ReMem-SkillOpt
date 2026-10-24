"""Run the actual ReMem optimizer prompt once with empty training evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path

from skillopt.model import chat_optimizer, configure_azure_openai, set_backend, set_optimizer_deployment
from skillopt.remem.proposals import JsonProposalStrategy
from skillopt.remem.transport_audit import summarize


def main() -> None:
    key_file = Path(".env.deepseek.local")
    entries = dict(line.split("=", 1) for line in key_file.read_text(encoding="utf-8").splitlines()
                   if line and not line.startswith("#") and "=" in line)
    key = entries.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("Local DeepSeek API key missing")
    out = Path("outputs/remem/optimizer-preflight-deepseek")
    if out.exists():
        raise FileExistsError("Preflight output exists; use a new named run")
    out.mkdir(parents=True)
    audit = out / "transport.jsonl"
    os.environ["REMEM_TRANSPORT_AUDIT_PATH"] = str(audit.resolve())
    set_backend("openai_chat")
    configure_azure_openai(endpoint="https://api.deepseek.com", api_key=key, auth_mode="openai_compatible")
    set_optimizer_deployment("deepseek-flash")

    def call(system: str, user: str) -> str:
        text, _ = chat_optimizer(system=system, user=user, max_completion_tokens=8192,
                                 retries=1, stage="remem_optimizer_preflight")
        return text

    skill = Path("skillopt/envs/spreadsheetbench/skills/initial.md").read_text(encoding="utf-8")
    try:
        result = JsonProposalStrategy(True, call, 4).propose(skill, [], [])
        metadata = {"status": result.status, "reason_present": bool(result.reason),
                    "proposal_count": len(result.proposals)}
    except Exception as exc:
        metadata = {"status": "infra_failure", "error_type": type(exc).__name__}
    metadata.update(scope="optimizer_prompt_preflight_no_task_data", requested_model="deepseek-flash",
                    transport=summarize(audit) if audit.exists() else None)
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
