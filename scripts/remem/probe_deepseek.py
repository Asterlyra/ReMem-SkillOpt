"""Small metadata-only DeepSeek preflight using a Git-ignored local key file."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from openai import OpenAI


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-file", type=Path, default=Path(".env.deepseek.local"))
    args = parser.parse_args()
    entries = dict(line.split("=", 1) for line in args.key_file.read_text(encoding="utf-8").splitlines()
                   if line and not line.startswith("#") and "=" in line)
    key = entries.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("Local DeepSeek API key missing")
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com", max_retries=0, timeout=30)
    report: dict = {"endpoint_host": "api.deepseek.com", "requested_model": "deepseek-flash"}
    for stage in ("models", "chat"):
        started = time.monotonic()
        try:
            if stage == "models":
                models = client.models.list()
                report[stage] = {"status": "ok", "available": [m.id for m in models.data],
                                 "elapsed_s": round(time.monotonic() - started, 3), "http_attempts": 1}
            else:
                response = client.chat.completions.create(
                    model="deepseek-flash", messages=[{"role": "user", "content": "Reply with only: OK"}],
                    max_tokens=128,
                )
                message = response.choices[0].message
                usage = response.usage
                report[stage] = {
                    "status": "ok", "response_model": response.model,
                    "finish_reason": response.choices[0].finish_reason,
                    "nonempty_content": bool(message.content and message.content.strip()),
                    "content_is_ok": (message.content or "").strip() == "OK",
                    "usage": {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens,
                              "total_tokens": usage.total_tokens} if usage else None,
                    "elapsed_s": round(time.monotonic() - started, 3), "http_attempts": 1,
                }
        except Exception as exc:  # Only the type and HTTP status are safe to retain.
            report[stage] = {"status": "failed", "error_type": type(exc).__name__,
                             "http_status": getattr(exc, "status_code", None),
                             "elapsed_s": round(time.monotonic() - started, 3), "http_attempts": 1}
            break
    output = Path("outputs/remem/preflight/deepseek_metadata.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
