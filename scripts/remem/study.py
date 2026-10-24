"""CLI for the ReMem development study lifecycle (no model calls by default)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from skillopt.remem import study


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("study_id")
    prepare.add_argument("--config", type=Path)
    prepare.add_argument("--data-manifest", type=Path)
    prepare.add_argument("--include-skillopt-controlled", action="store_true")
    for name in ("verify", "report", "run"):
        command = sub.add_parser(name)
        command.add_argument("directory", type=Path)
        if name == "run":
            command.add_argument("--name", required=True)
            command.add_argument("--execute", action="store_true", help="Make real model calls for a development run")
            command.add_argument("--key-file", type=Path, help="Git-ignored DeepSeek key file for explicit execution")
    args = parser.parse_args()
    if args.command == "prepare":
        result = {"directory": str(study.prepare(args.study_id, config_path=args.config,
                                                 data_manifest_path=args.data_manifest,
                                                 include_skillopt_controlled=args.include_skillopt_controlled)), "model_calls": 0}
    elif args.command == "verify":
        result = study.verify(args.directory.resolve())
    elif args.command == "report":
        result = study.report(args.directory.resolve())
    else:
        result = study.run(args.directory.resolve(), args.name, execute=args.execute, key_file=args.key_file)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
