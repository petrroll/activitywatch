#!/usr/bin/env python3
"""Start a packaged ActivityWatch server and verify the v2 API capability contract."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

REQUIRED_CAPABILITIES = {
    "query.query_bucket_optional_raw.v1",
    "query.query_period.v1",
    "query.flood_v2.v1",
    "query.categorize_v2.v1",
    "query.categorize_v2_explain.v1",
    "query.active_periods_v2.v1",
    "settings.rules_v2.v1",
}


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail unless a packaged server advertises every flexible-rules v2 capability"
    )
    parser.add_argument("--label", default="server artifact")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="command to start; use {port} where the allocated port belongs",
    )
    args = parser.parse_args()
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a server command is required after --")

    port = available_port()
    command = [part.replace("{port}", str(port)) for part in command]
    executable = Path(command[0])
    if not executable.is_file() and shutil.which(command[0]) is None:
        print(f"ERROR: {args.label}: executable not found: {executable}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="aw-capability-smoke-") as temp_dir:
        env = os.environ.copy()
        # Keep the smoke isolated from a user's real settings/database. These variables
        # cover the platformdirs locations used by the Python and Rust servers.
        env.update(
            {
                "HOME": temp_dir,
                "XDG_CONFIG_HOME": str(Path(temp_dir) / "config"),
                "XDG_CACHE_HOME": str(Path(temp_dir) / "cache"),
                "XDG_DATA_HOME": str(Path(temp_dir) / "data"),
                "APPDATA": str(Path(temp_dir) / "appdata"),
                "LOCALAPPDATA": str(Path(temp_dir) / "localappdata"),
            }
        )
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        deadline = time.monotonic() + args.timeout
        info = None
        last_error: Optional[Exception] = None
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/0/info", timeout=1
                    ) as response:
                        info = json.load(response)
                        break
                except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
                    last_error = error
                    time.sleep(0.2)

            if info is None:
                output = b""
                if process.stdout is not None:
                    stop_process(process)
                    output = process.stdout.read()
                print(
                    f"ERROR: {args.label} did not expose /api/0/info on port {port}: "
                    f"{last_error or 'process exited'}\n{output.decode(errors='replace')}",
                    file=sys.stderr,
                )
                return 1

            advertised = set(info.get("capabilities", []))
            missing = sorted(REQUIRED_CAPABILITIES - advertised)
            if missing:
                print(
                    f"ERROR: {args.label} is incompatible with the bundled rules v2 UI; "
                    f"missing capabilities: {', '.join(missing)}",
                    file=sys.stderr,
                )
                return 1
            print(
                f"OK: {args.label} advertises all {len(REQUIRED_CAPABILITIES)} "
                "required flexible-rules v2 capabilities"
            )
            return 0
        finally:
            stop_process(process)


if __name__ == "__main__":
    raise SystemExit(main())
