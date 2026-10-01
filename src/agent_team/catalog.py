"""Read-only native and provider model catalog discovery."""

# VERIFY: Exercise Codex, Antigravity, and Claude discovery with authenticated
# clients to confirm current live response envelopes and effort metadata.

from __future__ import annotations

import json
import math
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_MAX_RESPONSE_BYTES = 1_048_576
_MAX_CATALOG_MODELS = 1_000
_MAX_CATALOG_PAGES = 100


@dataclass(frozen=True)
class CatalogResult:
    """A normalized discovery result suitable for text or JSON output."""

    target: str
    source: str
    status: str
    models: tuple[dict[str, Any], ...]
    message: str | None = None


def _status(target: str, source: str, status: str, message: str) -> CatalogResult:
    return CatalogResult(target, source, status, (), message)


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _efforts(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    efforts: list[str] = []
    for item in value:
        if isinstance(item, str):
            effort = item
        elif isinstance(item, Mapping):
            effort = _string(item.get("reasoningEffort"))
        else:
            return None
        if effort is None:
            return None
        efforts.append(effort)
    return list(dict.fromkeys(efforts))


def _first_efforts(item: Mapping[str, object]) -> list[str] | None:
    for key in ("supportedReasoningEfforts", "supported_reasoning_efforts", "effort_options", "efforts"):
        if key in item:
            return _efforts(item[key])
    return None


def _normalized_model(item: Mapping[str, object]) -> dict[str, Any] | None:
    model_id = _string(item.get("id")) or _string(item.get("model")) or _string(item.get("name"))
    if model_id is None:
        return None
    display_name = (
        _string(item.get("display_name"))
        or _string(item.get("displayName"))
        or _string(item.get("name"))
        or model_id
    )
    efforts = _first_efforts(item)
    result: dict[str, Any] = {"model_id": model_id, "display_name": display_name}
    if efforts is not None:
        result["effort_options"] = efforts
        result["effort_source"] = "catalog"
    else:
        result["effort_options"] = None
        result["effort_source"] = None
    return result


def _normalize_models(value: object) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        model = _normalized_model(item)
        if model is None:
            return None
        if not item.get("hidden", False):
            normalized.append(model)
    return normalized


def _models_from_payload(payload: object) -> list[dict[str, Any]] | None:
    """Parse the model-list response envelopes used by Codex and Claude."""
    if isinstance(payload, list):
        return _normalize_models(payload)
    if not isinstance(payload, Mapping):
        return None
    for key in ("models", "data", "items"):
        if key in payload:
            return _normalize_models(payload[key])
    return None


def _next_cursor(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    for key in ("nextCursor", "next_cursor", "next_page", "last_id"):
        value = _string(payload.get(key))
        if value:
            return value
    return None


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("catalog request timed out")
    return remaining


def _read_line(stream: Any, timeout: float) -> str | None:
    lines: queue.Queue[str | None] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            lines.put(stream.readline(_MAX_RESPONSE_BYTES + 1))
        except OSError:
            lines.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        line = lines.get(timeout=timeout)
    except queue.Empty:
        return None
    return line or None


def _jsonrpc_response(stream: Any, request_id: int, deadline: float) -> object:
    while True:
        line = _read_line(stream, _remaining(deadline))
        if line is None:
            raise TimeoutError("app-server response timed out")
        if len(line) > _MAX_RESPONSE_BYTES:
            raise RuntimeError("app-server response exceeds output limit")
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, Mapping) or message.get("id") != request_id:
            continue
        if "error" in message:
            raise RuntimeError("app-server returned an error")
        return message.get("result", {})


def _codex_catalog(timeout: float) -> CatalogResult:
    source = "codex-app-server"
    executable = shutil.which("codex")
    if executable is None:
        return _status("codex", source, "unavailable", "codex was not found")
    process: subprocess.Popen[str] | None = None
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(
            [executable, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if process.stdin is None or process.stdout is None:
            raise OSError("app-server streams are unavailable")

        def send(request_id: int, method: str, params: Mapping[str, object]) -> object:
            process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            return _jsonrpc_response(process.stdout, request_id, deadline)

        send(1, "initialize", {"clientInfo": {"name": "agent-team", "version": "1"}, "capabilities": {}})
        process.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
        process.stdin.flush()
        cursor: str | None = None
        models: list[dict[str, Any]] = []
        for request_id in range(2, _MAX_CATALOG_PAGES + 2):
            params: dict[str, object] = {} if cursor is None else {"cursor": cursor}
            payload = send(request_id, "model/list", params)
            page = _models_from_payload(payload)
            if page is None:
                raise RuntimeError("app-server returned an unsupported model/list envelope")
            models.extend(page)
            if len(models) > _MAX_CATALOG_MODELS:
                raise RuntimeError("app-server catalog exceeds model limit")
            cursor = _next_cursor(payload)
            if cursor is None:
                break
        else:
            raise RuntimeError("app-server catalog exceeded pagination limit")
        if not models:
            return _status("codex", source, "unavailable", "app-server returned no usable models")
        return CatalogResult("codex", source, "ok", tuple(models))
    except (OSError, TimeoutError, RuntimeError) as exc:
        return _status("codex", source, "error", str(exc))
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()


def _read_stream(stream: Any, deadline: float) -> str | None:
    chunks: queue.Queue[str | None] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            chunks.put(stream.read(_MAX_RESPONSE_BYTES + 1))
        except OSError:
            chunks.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        return chunks.get(timeout=_remaining(deadline))
    except queue.Empty:
        return None


def _antigravity_catalog(timeout: float) -> CatalogResult:
    source = "antigravity-cli"
    executable = shutil.which("agy")
    if executable is None:
        return _status("antigravity", source, "unavailable", "agy was not found")
    process: subprocess.Popen[str] | None = None
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(
            [executable, "--output-format", "json", "models"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if process.stdout is None:
            raise OSError("agy output stream is unavailable")
        output = _read_stream(process.stdout, deadline)
        if output is None:
            raise TimeoutError("agy models timed out")
        if len(output) > _MAX_RESPONSE_BYTES:
            raise RuntimeError("agy models output exceeds limit")
        returncode = process.wait(timeout=_remaining(deadline))
        if returncode != 0:
            raise RuntimeError(f"agy models exited {returncode}")
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError("agy models did not return JSON") from exc
        if not isinstance(payload, Mapping):
            raise TypeError("agy models returned an unsupported envelope")
        command = payload.get("command")
        if not isinstance(command, Mapping) or not isinstance(command.get("data"), Mapping):
            raise TypeError("agy models returned an unsupported envelope")
        models = _normalize_models(command["data"].get("models"))
        if models is None:
            raise TypeError("agy models returned an unsupported envelope")
        if len(models) > _MAX_CATALOG_MODELS:
            raise RuntimeError("agy catalog exceeds model limit")
        if not models:
            return _status("antigravity", source, "unavailable", "agy returned no usable models")
        return CatalogResult("antigravity", source, "ok", tuple(models))
    except (OSError, TimeoutError, RuntimeError, TypeError) as exc:
        return _status("antigravity", source, "error", str(exc))
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()


def _claude_catalog(timeout: float) -> CatalogResult:
    source = "anthropic-api-catalog"
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _status("claude", source, "unavailable", "ANTHROPIC_API_KEY is not set")
    models: list[dict[str, Any]] = []
    after_id: str | None = None
    deadline = time.monotonic() + timeout
    try:
        for _ in range(_MAX_CATALOG_PAGES):
            query: dict[str, str] = {"limit": "100"}
            if after_id is not None:
                query["after_id"] = after_id
            request = Request(
                "https://api.anthropic.com/v1/models?" + urlencode(query),
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            )
            with urlopen(request, timeout=_remaining(deadline)) as response:
                body = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise RuntimeError("Claude catalog response exceeds output limit")
            payload = json.loads(body.decode("utf-8"))
            page = (
                _normalize_models(payload["data"])
                if isinstance(payload, Mapping) and "data" in payload
                else None
            )
            if page is None:
                raise RuntimeError("Claude catalog returned an unsupported envelope")
            models.extend(page)
            if len(models) > _MAX_CATALOG_MODELS:
                raise RuntimeError("Claude catalog exceeds model limit")
            if not isinstance(payload, Mapping) or not payload.get("has_more"):
                break
            after_id = _next_cursor(payload)
            if after_id is None:
                raise RuntimeError("Claude catalog pagination response is incomplete")
        else:
            raise RuntimeError("Claude catalog exceeded pagination limit")
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
        return _status("claude", source, "error", f"Claude Models API request failed: {exc}")
    if not models:
        return _status("claude", source, "unavailable", "Claude Models API returned no usable models")
    return CatalogResult("claude", source, "ok", tuple(models))


def fetch_catalog(target: str, timeout: float) -> CatalogResult:
    """Fetch one live catalog without falling back to configured model values."""
    if timeout <= 0 or not math.isfinite(timeout):
        raise ValueError("timeout must be greater than zero")
    if target == "codex":
        return _codex_catalog(timeout)
    if target == "antigravity":
        return _antigravity_catalog(timeout)
    if target == "claude":
        return _claude_catalog(timeout)
    raise ValueError(f"unsupported target: {target}")
