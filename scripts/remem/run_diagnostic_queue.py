"""Execute the frozen diagnostic once; preserve every terminal arm, including errors."""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from skillopt.remem.study import report, verify


def now():
    return datetime.now(timezone.utc).isoformat()


def active_study_processes(directory):
    command = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
        "Select-Object ProcessId,ParentProcessId,CreationDate,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, text=True, check=True
    )
    processes = json.loads(result.stdout) if result.stdout.strip() else []
    processes = processes if isinstance(processes, list) else [processes]
    found = []
    for process in processes:
        if process["ProcessId"] in (os.getpid(), os.getppid()):
            continue
        command_line = process.get("CommandLine") or ""
        if directory.name in command_line and any(
            name in command_line for name in ("study.py", "run_medium_queue.py", "run_diagnostic_queue.py")
        ):
            found.append(
                {
                    "pid": process["ProcessId"],
                    "created": process["CreationDate"],
                    "executable": process["ExecutablePath"],
                }
            )
    return found


def main(directory, key_file, resume_unstarted=False, reporter=Path(__file__).with_name("audit_medium.py"), only=None):
    verify(directory)
    if active_study_processes(directory):
        raise RuntimeError("A verified study process is still live; do not start a duplicate queue")
    progress_path = directory / "queue.json"
    if progress_path.exists():
        if not resume_unstarted:
            raise FileExistsError("Queue exists; inspect terminal and live processes before any explicit resume")
        previous = json.loads(progress_path.read_text())
        if any(r["status"] not in ("finished", "failed") for r in previous["runs"]):
            raise RuntimeError("Prior arm lacks an explicit terminal status; reconcile its ledger first")
        backup = directory / (
            "queue.before_resume_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
        )
        backup.write_bytes(progress_path.read_bytes())
    elif resume_unstarted:
        raise FileNotFoundError("Explicit resume needs an existing queue")
    freeze = json.loads((directory / "freeze.json").read_text())
    selected = (
        list(only)
        if only is not None
        else (previous.get("selected_run_order", freeze["run_order"]) if resume_unstarted else freeze["run_order"])
    )
    if not selected or len(selected) != len(set(selected)) or not set(selected) <= set(freeze["run_order"]):
        raise ValueError("Selected recovery runs must be unique members of the frozen matrix")
    if resume_unstarted and selected != previous.get("selected_run_order", freeze["run_order"]):
        raise ValueError("Recovery selection cannot change while resuming a queue")
    progress = {
        "study_id": freeze["study_id"],
        "status": "running",
        "pid": os.getpid(),
        "started_at_utc": now(),
        "runs": [],
        "final_test_released": False,
        "selected_run_order": selected,
    }
    if resume_unstarted:
        progress = previous
        terminal = {key: progress.pop(key) for key in ("finished_at_utc", "stop_run") if key in progress}
        progress.setdefault("scheduler_invocations", []).append(
            {
                "previous_pid": previous["pid"],
                "new_pid": os.getpid(),
                "resumed_at_utc": now(),
                "mode": "unstarted_only",
                "previous_termination": terminal,
            }
        )
        progress.update(status="running", pid=os.getpid(), selected_run_order=selected)
    attempted = {r["run"] for r in progress["runs"]}

    def save():
        temporary = directory / "queue.json.tmp"
        temporary.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
        temporary.replace(progress_path)

    save()
    for name in selected:
        if name in attempted:
            continue
        started = time.monotonic()
        entry = {"run": name, "status": "running", "started_at_utc": now()}
        progress["runs"].append(entry)
        log = directory / (name + ".log")
        with log.open("x", encoding="utf-8") as output:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "scripts/remem/study.py",
                    "run",
                    str(directory),
                    "--name",
                    name,
                    "--execute",
                    "--key-file",
                    str(key_file),
                ],
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            entry["pid"] = child.pid
            save()
            print("Starting " + name, flush=True)
            code = child.wait()
        entry.update(
            status="finished" if code == 0 else "failed",
            exit_code=code,
            elapsed_s=time.monotonic() - started,
            finished_at_utc=now(),
        )
        save()
        print("Finished " + name + " exit=" + str(code), flush=True)
        audit = subprocess.run([sys.executable, "-X", "utf8", str(reporter), str(directory)], check=False)
        if audit.returncode:
            progress.update(status="stopped_reporting_failure", stop_run=name)
            progress.setdefault("reporting_errors", []).append(
                {"run": name, "exit_code": audit.returncode, "time_utc": now()}
            )
            save()
            break
        row = next(r for r in report(directory)["runs"] if r["run"] == name)
        if code and row["status"] == "not_started":
            progress.update(status="stopped_pre_execution_failure", stop_run=name)
            break
        transport = directory / "runs" / name / "remem/transport.jsonl"
        if code and transport.exists():
            raw = [json.loads(x) for x in transport.read_text().splitlines() if x]
            if any(x["kind"] == "response" and x["status"] in (401, 403) for x in raw):
                progress.update(status="stopped_authentication_failure", stop_run=name)
                break
            permanent = {
                "context_length_exceeded",
                "invalid_request_error",
                "invalid_argument",
                "insufficient_quota",
                "insufficient_balance",
                "invalid_api_key",
                "model_not_found",
                "content_filter",
            }
            codes = {x.get("response_contract", {}).get("provider_error_category") for x in raw if x["kind"] == "usage"}
            if codes & permanent:
                progress.update(
                    status="stopped_provider_contract_failure",
                    stop_run=name,
                    provider_error_categories=sorted(codes & permanent),
                )
                break
    else:
        progress["status"] = "completed_with_failures" if any(r["exit_code"] for r in progress["runs"]) else "completed"
    progress["finished_at_utc"] = now()
    save()
    print(
        json.dumps({"status": progress["status"], "attempted_arms": len(progress["runs"]), "test_executions": 0}),
        flush=True,
    )
    return 1 if progress["status"].startswith("stopped_") else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--resume-unstarted", action="store_true")
    parser.add_argument("--reporter", type=Path, default=Path(__file__).with_name("audit_medium.py"))
    parser.add_argument(
        "--only", nargs="+", help="Explicit failed-arm recovery subset; never replay completed arms implicitly"
    )
    args = parser.parse_args()
    raise SystemExit(
        main(args.directory.resolve(), args.key_file.resolve(), args.resume_unstarted, args.reporter, args.only)
    )
