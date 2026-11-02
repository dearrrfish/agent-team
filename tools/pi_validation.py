"""Development-only, isolated Pi RPC smoke check (no prompts or plugins)."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import threading
import time
import uuid


class RpcError(RuntimeError):
    """Protocol, deadline, or child-process failure."""


class RpcClient:
    """Single-request-at-a-time driver; continuously drains both binary pipes.

    Call close() or use a context manager, including after errors. Limits apply
    to the entire session; excess output is discarded while pipes keep draining.
    """

    def __init__(self, argv, *, cwd, env, timeout=10.0, max_bytes=4 * 1024 * 1024,
                 max_records=10000, protocol=True):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_records = max_records
        self.protocol = protocol
        self.records = []
        self.stderr = bytearray()
        self.stdout = bytearray()
        self._starts = {}
        self._error = None
        self._done = False
        self._stop = threading.Event()
        self._condition = threading.Condition()
        self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        bufsize=0)
        os.set_blocking(self.process.stdin.fileno(), False)
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()
        self.shutdown = None

    def _fail(self, message):
        if self._error is None:
            self._error = message

    def _drain(self):
        pending = bytearray()
        total = 0
        try:
            with selectors.DefaultSelector() as selector:
                for stream in (self.process.stdout, self.process.stderr):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ)
                while selector.get_map() and not self._stop.is_set():
                    for key, _ in selector.select(0.05):
                        chunk = os.read(key.fd, 65536)
                        with self._condition:
                            if not chunk:
                                selector.unregister(key.fileobj)
                                if key.fileobj is self.process.stdout and pending:
                                    self._fail("stdout ended with an unterminated JSONL record")
                                self._condition.notify_all()
                                continue
                            total += len(chunk)
                            if total > self.max_bytes:
                                self._fail(f"output exceeded {self.max_bytes} byte session limit")
                                pending.clear()
                            elif key.fileobj is self.process.stderr:
                                self.stderr.extend(chunk)
                            elif not self.protocol:
                                self.stdout.extend(chunk)
                            elif self._error is None:
                                pending.extend(chunk)
                                while b"\n" in pending:
                                    line, _, rest = pending.partition(b"\n")
                                    pending = bytearray(rest)
                                    try:
                                        record = json.loads(line.rstrip(b"\r").decode("utf-8"))
                                        if not isinstance(record, dict) or not isinstance(record.get("type"), str):
                                            raise ValueError("expected object with string type")
                                        if len(self.records) >= self.max_records:
                                            raise ValueError("record limit exceeded")
                                        self.records.append(record)
                                    except (ValueError, UnicodeError) as error:
                                        self._fail(f"invalid stdout JSONL: {error}")
                                        pending.clear()
                                        break
                            self._condition.notify_all()
        except (OSError, ValueError) as error:
            with self._condition:
                self._fail(f"pipe read failed: {error}")
        finally:
            with self._condition:
                self._done = True
                self._condition.notify_all()

    def _wait(self, predicate, deadline, description):
        with self._condition:
            while True:
                if self._error:
                    raise RpcError(self._error)
                result = predicate()
                if result is not None:
                    return result
                if self._done:
                    code = self.process.poll()
                    raise RpcError(f"child exited/closed stdout before {description}; exit={code}; "
                                   f"stderr={self.stderr.decode('utf-8', errors='replace')!r}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RpcError(f"deadline exceeded waiting for {description}")
                self._condition.wait(min(remaining, 0.05))

    def request(self, command, *, timeout=None, **fields):
        if "id" in fields or "type" in fields:
            raise ValueError("id and type are assigned by the client")
        duration = self.timeout if timeout is None else timeout
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("timeout must be finite and positive")
        deadline = time.monotonic() + duration
        request_id = uuid.uuid4().hex
        payload = json.dumps({**fields, "type": command, "id": request_id},
                             ensure_ascii=False).encode("utf-8") + b"\n"
        if len(payload) > 65536:
            raise ValueError("request exceeds 65536 bytes")
        with self._condition:
            self._starts[request_id] = len(self.records)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdin, selectors.EVENT_WRITE)
                offset = 0
                while offset < len(payload):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(max(0, remaining)):
                        raise RpcError(f"deadline exceeded writing {command}")
                    try:
                        offset += os.write(self.process.stdin.fileno(), payload[offset:])
                    except BlockingIOError:
                        continue
        except (BrokenPipeError, ValueError) as error:
            raise RpcError(f"child stdin closed while writing {command}") from error

        def response():
            for record in self.records[self._starts[request_id]:]:
                if record.get("type") == "response":
                    if record.get("id") == request_id:
                        return record
                    raise RpcError(f"unexpected response id: {record.get('id')!r}")
            return None

        result = self._wait(response, deadline, f"{command} response ({request_id})")
        if result.get("command") != command or not isinstance(result.get("success"), bool):
            raise RpcError(f"malformed response for {command}: {result!r}")
        if not result["success"]:
            raise RpcError(f"{command} rejected: {result.get('error', 'no error supplied')}")
        return result

    def wait_settled(self, response, *, timeout=None):
        """Return agent_settled since this request, or None for handled prompts.

        Settled is a session event, not a per-request completion guarantee for
        concurrent prompts. This driver deliberately serializes requests.
        """
        if response.get("data", {}).get("disposition") == "handled":
            return None
        start = self._starts[response["id"]]
        duration = self.timeout if timeout is None else timeout
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("timeout must be finite and positive")
        deadline = time.monotonic() + duration
        return self._wait(lambda: next((r for r in self.records[start:]
                                       if r["type"] == "agent_settled"), None),
                          deadline, "agent_settled")

    def wait_exit(self):
        try:
            code = self.process.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired as error:
            raise RpcError("deadline exceeded waiting for process exit") from error
        self._reader.join(self.timeout)
        if self._reader.is_alive():
            raise RpcError("deadline exceeded draining process output")
        if self._error:
            raise RpcError(self._error)
        return code

    def close(self):
        if self.shutdown is not None:
            return
        action = "stdin-eof"
        self.process.stdin.close()
        try:
            self.process.wait(timeout=min(self.timeout, 0.5))
        except subprocess.TimeoutExpired:
            action = "terminate"
            self.process.terminate()
            try:
                self.process.wait(timeout=min(self.timeout, 0.5))
            except subprocess.TimeoutExpired:
                action = "kill"
                self.process.kill()
                try:
                    self.process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    self._fail("cleanup deadline exceeded reaping killed child")
        # Let the reader observe EOF and validate trailing protocol bytes.
        self._reader.join(timeout=self.timeout)
        if self._reader.is_alive():
            self._fail("cleanup deadline exceeded draining pipe output")
            self._stop.set()
            self._reader.join(timeout=self.timeout)
        if self._reader.is_alive():
            self._fail("cleanup deadline exceeded stopping pipe reader")
        self.process.stdout.close()
        self.process.stderr.close()
        self.shutdown = {"action": action, "exit_code": self.process.returncode,
                         "reaped": self.process.poll() is not None,
                         "reader_stopped": not self._reader.is_alive()}
        if not self.shutdown["reaped"] or not self.shutdown["reader_stopped"]:
            raise RpcError(self._error or "cleanup incomplete")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def isolated_environment(root):
    """Allowlist environment: never inherit auth, runtime hooks, or config."""
    home = root / "home"
    agent = root / "pi-agent"
    temporary = root / "tmp"
    for path in (home, agent, temporary):
        path.mkdir()
    return {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(home),
            "PI_CODING_AGENT_DIR": str(agent), "TMPDIR": str(temporary),
            "LANG": "C.UTF-8", "TERM": "dumb"}


def smoke(pi, timeout):
    report = {"producer": "tools/pi_validation.py", "status": "blocked",
              "pi": pi, "version": None, "checks": [],
              "skipped": {name: "not authorized in this stage" for name in
                          ("plugin_install", "plugin_discovery", "model_prompt",
                           "delegation", "child_worktree")}}
    with tempfile.TemporaryDirectory(prefix="pi-validation-", dir=os.environ["TMPDIR"]) as directory:
        root = Path(directory)
        env = isolated_environment(root)
        cwd = root / "project"
        cwd.mkdir()
        report["cwd"] = str(cwd)
        report["environment_keys"] = sorted(env)
        version_argv = [pi, "--version"]
        report["version_command"] = version_argv
        try:
            with RpcClient(version_argv, cwd=cwd, env=env, timeout=timeout,
                           protocol=False) as version:
                report["version_exit_code"] = version.wait_exit()
                report["version"] = version.stdout.decode("utf-8", errors="replace").strip()
                report["version_stderr"] = version.stderr.decode("utf-8", errors="replace")
                if report["version_exit_code"] != 0:
                    raise RpcError("pi --version failed")
            argv = [pi, "--mode", "rpc", "--no-session", "--no-extensions", "--no-mcp",
                    "--no-context-files", "--no-skills", "--no-prompt-templates",
                    "--no-themes", "--no-tools"]
            report["command"] = argv
            client = RpcClient(argv, cwd=cwd, env=env, timeout=timeout)
            try:
                for command in ("get_state", "get_commands", "get_available_models",
                                "get_available_thinking_levels"):
                    response = client.request(command)
                    data = response.get("data")
                    if not isinstance(data, dict):
                        raise RpcError(f"{command} returned non-object data")
                    if command == "get_state":
                        if data.get("isStreaming") is not False or data.get("messageCount") != 0:
                            raise RpcError("get_state did not report an idle empty session")
                    else:
                        key = {"get_commands": "commands", "get_available_models": "models",
                               "get_available_thinking_levels": "levels"}[command]
                        if not isinstance(data.get(key), list):
                            raise RpcError(f"{command} missing {key} list")
                        if key == "levels" and (not data[key] or
                                                not all(isinstance(level, str) for level in data[key])):
                            raise RpcError("get_available_thinking_levels returned invalid levels")
                    report["checks"].append({"command": command, "status": "passed",
                                             "response": response})
                report["status"] = "passed"
            finally:
                client.close()
                report["records"] = client.records
                report["stderr"] = client.stderr.decode("utf-8", errors="replace")
                report["shutdown"] = client.shutdown
                if client._error:
                    raise RpcError(client._error)
                if client.shutdown["exit_code"] != 0 or client.shutdown["action"] != "stdin-eof":
                    raise RpcError(f"RPC did not shut down cleanly: {client.shutdown}")
        except (OSError, RpcError) as error:
            report["status"] = "blocked"
            report["error"] = str(error)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi", default="pi", help="Pi executable (default: PATH pi)")
    parser.add_argument("--output", type=Path, required=True, help="new JSON report; never overwritten")
    parser.add_argument("--timeout", type=float, default=10.0, help="per-command deadline in seconds")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    pi = shutil.which(args.pi)
    # Reserve the destination before starting any child, and never replace evidence.
    with args.output.open("x", encoding="utf-8") as output:
        report = smoke(pi, args.timeout) if pi else {
            "status": "blocked", "error": f"Pi executable not found: {args.pi}"}
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(f"{report['status']}: {args.output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
