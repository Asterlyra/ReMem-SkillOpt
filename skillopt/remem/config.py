"""Fail closed for unsupported ReMem controls instead of ignoring config keys."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

ENV_FIELDS = {"name", "skill_init", "out_root", "split_mode", "split_seed", "split_ratio", "split_dir",
              "data_path", "split_output_dir", "data_root", "mode", "workers", "max_turns", "exec_timeout",
              "max_completion_tokens"}


def validate_source_config(cfg: dict, mapping: dict, sections: frozenset) -> None:
    flat_allowed = set(mapping.values()) | ENV_FIELDS | {"remem"}
    for section, value in cfg.items():
        if section in sections and isinstance(value, dict):
            allowed = ENV_FIELDS if section == "env" else {k.split(".", 1)[1] for k in mapping if k.startswith(section + ".")}
            if set(value) - allowed:
                raise ValueError(f"Unknown ReMem configuration fields in {section}: {sorted(set(value)-allowed)}")
        elif section not in flat_allowed:
            raise ValueError(f"Unknown ReMem configuration field: {section}")


@dataclass(frozen=True)
class ReMemConfig:
    enabled: bool = True
    repair: bool = True
    memory: bool = True
    max_proposals: int = 4
    max_edits: int = 2
    top_k: int = 3
    max_attempts: int = 2
    memory_character_cap: int = 12000
    trace_character_cap: int = 12000
    bootstrap_samples: int = 10000
    confidence: float = .95
    optimizer_calls: int = 80
    optimizer_output_tokens: int = 16384
    task_executions: int = 400
    run_id: str = "remem-development"
    task_schedule: tuple = ()

    @classmethod
    def parse(cls, cfg: dict) -> ReMemConfig | None:
        raw = cfg.get("remem")
        if raw is None:
            return None
        if not isinstance(raw, dict) or set(raw) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown ReMem configuration keys")
        options = cls(**raw)
        for name in ("enabled", "repair", "memory"):
            if type(getattr(options, name)) is not bool:
                raise ValueError(f"remem.{name} must be boolean")
        if not options.enabled:
            return None
        for name in ("max_proposals", "max_edits", "top_k", "max_attempts", "memory_character_cap",
                     "trace_character_cap", "bootstrap_samples", "optimizer_calls", "optimizer_output_tokens", "task_executions"):
            if type(getattr(options, name)) is not int or getattr(options, name) <= 0:
                raise ValueError(f"remem.{name} must be a positive integer")
        if options.max_edits > options.max_proposals or not 0 < options.confidence < 1:
            raise ValueError("Invalid ReMem budget or confidence")
        for name in ("use_slow_update", "use_meta_skill", "use_skill_aware_reflection", "use_semantic_density", "eval_test"):
            if cfg.get(name, False):
                raise ValueError(f"ReMem optimization requires {name}=false")
        if cfg.get("skill_update_mode", "patch") != "patch" or cfg.get("lr_control_mode", "fixed") != "fixed":
            raise ValueError("ReMem currently supports fixed bounded patches only")
        if cfg.get("lr_scheduler", "constant") != "constant" or cfg.get("edit_budget", options.max_edits) != options.max_edits:
            raise ValueError("ReMem's fixed edit cap must match the trainer budget")
        if cfg.get("mode", "single") != "single":
            raise ValueError("Core ReMem currently supports single-mode task execution only")
        if cfg.get("num_epochs", 1) != 1 or cfg.get("accumulation", 1) != 1:
            raise ValueError("ReMem uses one fixed task schedule and accumulation=1")
        if cfg.get("use_gate", True) is not True or cfg.get("gate_metric", "hard") != "hard":
            raise ValueError("Core arms require the shared hard-score paired gate")
        if not isinstance(options.run_id, str) or not options.run_id:
            raise ValueError("run_id must be nonempty")
        if not isinstance(options.task_schedule, (list, tuple)):
            raise ValueError("task_schedule must be a list of task ID batches")
        return options

    def identity(self) -> dict:
        return asdict(self)
