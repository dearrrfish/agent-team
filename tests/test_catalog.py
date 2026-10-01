import io
import json
import os
import unittest
from typing import Self
from unittest.mock import patch

from agent_team.catalog import fetch_catalog


class _FakeProcess:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("".join(json.dumps(item) + "\n" for item in responses))
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> None:
        return None

    def kill(self) -> None:
        self.killed = True


class _FakeCommand:
    def __init__(self, output: str, returncode: int = 0) -> None:
        self.stdout = io.StringIO(output)
        self.returncode = returncode
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float) -> int:
        return self.returncode

    def kill(self) -> None:
        return None


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return json.dumps(self.payload).encode("utf-8")[:size]


class CatalogTests(unittest.TestCase):
    def test_codex_catalog_initializes_and_follows_pagination(self) -> None:
        process = _FakeProcess([
            {"id": 1, "result": {}},
            {"id": 2, "result": {"data": [
                {"id": "gpt-a", "displayName": "GPT A", "supportedReasoningEfforts": [
                    {"reasoningEffort": "low", "description": "Low"},
                    {"reasoningEffort": "high", "description": "High"},
                ]},
                {"id": "hidden", "hidden": True},
            ], "nextCursor": "next"}},
            {"id": 3, "result": {"data": [{"id": "gpt-b"}]}},
        ])
        with patch("agent_team.catalog.shutil.which", return_value="/bin/codex"), patch(
            "agent_team.catalog.subprocess.Popen", return_value=process
        ):
            result = fetch_catalog("codex", 1)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.source, "codex-app-server")
        self.assertEqual(result.models, (
            {"model_id": "gpt-a", "display_name": "GPT A", "effort_options": ["low", "high"], "effort_source": "catalog"},
            {"model_id": "gpt-b", "display_name": "gpt-b", "effort_options": None, "effort_source": None},
        ))
        requests = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
        self.assertEqual(requests[0]["method"], "initialize")
        self.assertEqual(requests[1]["method"], "initialized")
        self.assertEqual(requests[2]["method"], "model/list")
        self.assertEqual(requests[3]["params"], {"cursor": "next"})
        self.assertTrue(process.terminated)

    def test_antigravity_catalog_uses_documented_command_envelope(self) -> None:
        successful = _FakeCommand(json.dumps({
            "command": {"data": {"models": [{"id": "flash", "name": "Flash"}]}},
        }))
        with patch("agent_team.catalog.shutil.which", return_value="/bin/agy"), patch(
            "agent_team.catalog.subprocess.Popen", return_value=successful
        ) as popen:
            result = fetch_catalog("antigravity", 1)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.models[0]["model_id"], "flash")
        self.assertIsNone(result.models[0]["effort_options"])
        self.assertEqual(popen.call_args.args[0], ["/bin/agy", "--output-format", "json", "models"])

        malformed = _FakeCommand(json.dumps({"data": {"models": []}}))
        with patch("agent_team.catalog.shutil.which", return_value="/bin/agy"), patch(
            "agent_team.catalog.subprocess.Popen", return_value=malformed
        ):
            failed = fetch_catalog("antigravity", 1)
        self.assertEqual(failed.status, "error")

        empty = _FakeCommand(json.dumps({"command": {"data": {"models": []}}}))
        with patch("agent_team.catalog.shutil.which", return_value="/bin/agy"), patch(
            "agent_team.catalog.subprocess.Popen", return_value=empty
        ):
            empty_result = fetch_catalog("antigravity", 1)
        self.assertEqual(empty_result.status, "unavailable")
        self.assertEqual(empty_result.models, ())

    def test_empty_codex_and_claude_catalogs_are_unavailable(self) -> None:
        codex = _FakeProcess([
            {"id": 1, "result": {}},
            {"id": 2, "result": {"data": []}},
        ])
        with patch("agent_team.catalog.shutil.which", return_value="/bin/codex"), patch(
            "agent_team.catalog.subprocess.Popen", return_value=codex
        ):
            self.assertEqual(fetch_catalog("codex", 1).status, "unavailable")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "secret-value"}, clear=True), patch(
            "agent_team.catalog.urlopen", return_value=_FakeResponse({"data": [], "has_more": False})
        ):
            self.assertEqual(fetch_catalog("claude", 1).status, "unavailable")

    def test_claude_catalog_uses_existing_key_and_paginates(self) -> None:
        responses = [
            _FakeResponse({"data": [{"id": "claude-a", "display_name": "Claude A"}], "has_more": True, "last_id": "claude-a"}),
            _FakeResponse({"data": [{"id": "claude-b"}], "has_more": False}),
        ]
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "secret-value"}, clear=True), patch(
            "agent_team.catalog.urlopen", side_effect=responses
        ) as urlopen_mock:
            result = fetch_catalog("claude", 1)
        self.assertEqual(result.status, "ok")
        self.assertEqual([item["model_id"] for item in result.models], ["claude-a", "claude-b"])
        self.assertTrue(all(item["effort_options"] is None for item in result.models))
        requests = [call.args[0] for call in urlopen_mock.call_args_list]
        self.assertEqual(requests[0].get_header("X-api-key"), "secret-value")
        self.assertIn("after_id=claude-a", requests[1].full_url)

    def test_claude_catalog_rejects_unsupported_envelopes(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "secret-value"}, clear=True), patch(
            "agent_team.catalog.urlopen", return_value=_FakeResponse({"models": []})
        ):
            result = fetch_catalog("claude", 1)
        self.assertEqual(result.status, "error")

    def test_missing_authorized_source_is_unavailable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = fetch_catalog("claude", 1)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.source, "anthropic-api-catalog")


if __name__ == "__main__":
    unittest.main()
