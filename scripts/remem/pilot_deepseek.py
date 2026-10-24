"""One real SpreadsheetBench training task through the project's adapter."""
from __future__ import annotations

import json
import os
from pathlib import Path

from skillopt.config import flatten_config, load_config
from skillopt.model import configure_azure_openai, set_backend, set_target_deployment
from skillopt.remem.transport_audit import summarize


def main() -> None:
    secret_path = Path(".env.deepseek.local")
    entries = dict(line.split("=", 1) for line in secret_path.read_text(encoding="utf-8").splitlines()
                   if line and not line.startswith("#") and "=" in line)
    key = entries.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("Local DeepSeek API key missing")
    out = Path("outputs/remem/pilot-deepseek-v41-1017")
    if out.exists():
        raise FileExistsError("Pilot output exists; use a new named run")
    out.mkdir(parents=True)
    audit = out / "transport.jsonl"
    os.environ["REMEM_TRANSPORT_AUDIT_PATH"] = str(audit.resolve())
    set_backend("openai_chat")
    configure_azure_openai(endpoint="https://api.deepseek.com", api_key=key, auth_mode="openai_compatible")
    set_target_deployment("deepseek-flash")
    cfg = flatten_config(load_config("configs/remem/core.yaml"))
    cfg.update(out_root=str(out.resolve()), data_root=str(Path(cfg["data_root"]).resolve()),
               split_dir=str(Path(cfg["split_dir"]).resolve()), target_model="deepseek-flash",
               optimizer_model="deepseek-flash", model_backend="openai_chat",
               target_backend="openai_chat", optimizer_backend="openai_chat", workers=1,
               max_completion_tokens=8192)
    # This pilot uses the adapter directly, not the six-step optimizer study.
    from scripts.train import get_adapter
    adapter = get_adapter(cfg)
    adapter.setup(cfg)
    task = adapter.dataloader.train_items[0]
    skill = Path(cfg["skill_init"]).read_text(encoding="utf-8")
    try:
        result = adapter.rollout([task], skill, str(out / "train"))[0]
        metadata = {"scope": "one_training_task_pilot", "requested_model": "deepseek-flash",
                    "task_id": str(task["id"]), "hard": result.get("hard"),
                    "fail_reason_type": str(result.get("fail_reason", "")).split(":", 1)[0],
                    "transport": summarize(audit) if audit.exists() else None}
    except Exception as exc:
        metadata = {"scope": "one_training_task_pilot", "requested_model": "deepseek-flash",
                    "task_id": str(task["id"]), "error_type": type(exc).__name__,
                    "transport": summarize(audit) if audit.exists() else None}
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
