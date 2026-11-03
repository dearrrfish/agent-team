from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.pi_validation import RpcClient, RpcError, isolated_environment, main, smoke


class PiValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="pi-validation-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = isolated_environment(self.root)

    def client(self, body, **options):
        fake = self.root / "fake.py"
        fake.write_text(textwrap.dedent("""
            import json, os, signal, sys, time
            def emit(record):
                sys.stdout.buffer.write(json.dumps(record, ensure_ascii=False).encode() + b'\\n')
                sys.stdout.buffer.flush()
            def reply(request, **fields):
                emit(dict(type='response', id=request['id'], command=request['type'],
                          success=True, **fields))
        """) + textwrap.dedent(body), encoding="utf-8")
        client = RpcClient([sys.executable, "-I", str(fake)], cwd=self.root,
                           env=self.env, timeout=0.6, **options)
        self.addCleanup(client.close)
        return client

    def assert_closed(self, client):
        client.close()
        self.assertIsNotNone(client.process.returncode)
        self.assertFalse(client._reader.is_alive())
        for stream in (client.process.stdin, client.process.stdout, client.process.stderr):
            self.assertTrue(stream.closed)
        self.assertTrue(client.shutdown["reaped"])
        client.close()  # idempotent

    def test_close_drains_unterminated_shutdown_record(self):
        client = self.client("""
            request = json.loads(sys.stdin.buffer.readline())
            reply(request)
            sys.stdin.buffer.read()
            sys.stdout.buffer.write(b'{')
            sys.stdout.buffer.flush()
        """)
        client.request("get_state")
        # Hold the reader until close() has observed process exit. The reader
        # must still reach EOF rather than stopping at the process boundary.
        original_join = client._reader.join
        original_read = os.read
        tail_read = threading.Event()
        release = threading.Event()
        stdout_fd = client.process.stdout.fileno()

        def held_read(fd, size):
            data = original_read(fd, size)
            if fd == stdout_fd and data:
                tail_read.set()
                release.wait(2)
            return data

        def release_at_join(timeout=None):
            self.assertTrue(tail_read.wait(2))
            release.set()
            return original_join(timeout)

        with patch("os.read", held_read), patch.object(client._reader, "join", release_at_join):
            try:
                client.close()
            finally:
                release.set()
        self.assertIn("unterminated", client._error)
        self.assert_closed(client)

    def test_lf_unicode_events_before_response_and_unique_ids(self):
        client = self.client("""
            for line in sys.stdin.buffer:
                request = json.loads(line)
                emit(dict(type='message_update', text='one two three'))
                emit(dict(type='agent_end'))
                emit(dict(type='agent_settled', marker=request['id']))
                reply(request, data=dict(disposition='started'))
        """)
        first = client.request("prompt", message="unicode value")
        settled = client.wait_settled(first)
        second = client.request("prompt", message="second")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(settled["marker"], first["id"])
        self.assertEqual(client.wait_settled(second)["marker"], second["id"])
        self.assertEqual(client.records[0]["text"], "one two three")
        self.assert_closed(client)

    def test_handled_does_not_wait_for_missing_settled(self):
        client = self.client("""
            for line in sys.stdin.buffer:
                reply(json.loads(line), data=dict(disposition='handled'))
        """)
        response = client.request("prompt")
        self.assertIsNone(client.wait_settled(response))

    def test_agent_end_does_not_settle_and_old_settled_is_not_reused(self):
        client = self.client("""
            for index, line in enumerate(sys.stdin.buffer):
                request = json.loads(line)
                if index == 0:
                    emit(dict(type='agent_settled'))
                emit(dict(type='agent_end'))
                reply(request, data=dict(disposition='started'))
        """)
        client.wait_settled(client.request("prompt"))
        response = client.request("prompt")
        with self.assertRaisesRegex(RpcError, "deadline.*agent_settled"):
            client.wait_settled(response, timeout=0.1)

    def test_rejected_response(self):
        client = self.client("""
            request = json.loads(sys.stdin.buffer.readline())
            emit(dict(type='response', id=request['id'], command=request['type'],
                      success=False, error='fixture denied'))
        """)
        with self.assertRaisesRegex(RpcError, "get_state rejected: fixture denied"):
            client.request("get_state")

    def test_response_correlation_and_shape(self):
        for record in ("dict(type='response', id='wrong', success=True)",
                       "dict(type='response', id=request['id'], command='wrong', success=True)"):
            with self.subTest(record=record):
                client = self.client(f"""
                    request = json.loads(sys.stdin.buffer.readline())
                    emit({record})
                """)
                with self.assertRaisesRegex(RpcError, "unexpected response id|malformed response"):
                    client.request("get_state")
                self.assert_closed(client)

    def test_invalid_stdout_and_unterminated_record(self):
        for raw in (b"not json\n", b"[]\n", b"\xff\n", b'{"type":"event"}'):
            with self.subTest(raw=raw):
                client = self.client(f"os.write(1, {raw!r})")
                with self.assertRaisesRegex(RpcError, "invalid stdout JSONL|unterminated"):
                    client.request("get_state")
                self.assert_closed(client)

    def test_early_exit_stderr_context(self):
        client = self.client("""
            sys.stdin.buffer.readline()
            sys.stderr.write('fixture startup refused')
            sys.exit(7)
        """)
        with self.assertRaisesRegex(RpcError, "before get_state.*fixture startup refused"):
            client.request("get_state")
        self.assert_closed(client)
        self.assertEqual(client.process.returncode, 7)

    def test_request_deadline_and_kill_reap(self):
        client = self.client("""
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            sys.stdin.buffer.readline()
            while True:
                time.sleep(1)
        """)
        start = time.monotonic()
        with self.assertRaisesRegex(RpcError, "deadline"):
            client.request("get_state", timeout=0.2)
        self.assert_closed(client)
        self.assertEqual(client.shutdown["action"], "kill")
        self.assertLess(time.monotonic() - start, 3)

    def test_stderr_and_stdout_drained_before_response(self):
        client = self.client("""
            request = json.loads(sys.stdin.buffer.readline())
            os.write(2, b'x' * 200000)
            for index in range(2000):
                emit(dict(type='progress', index=index))
            reply(request, data=dict(ok=True))
            for line in sys.stdin.buffer:
                pass
        """)
        self.assertTrue(client.request("get_state")["data"]["ok"])
        self.assertEqual(len(client.stderr), 200000)
        self.assertEqual(len(client.records), 2001)
        self.assert_closed(client)

    def test_bounded_output_and_record_count(self):
        for options, output in (({"max_bytes": 2048}, "os.write(2, b'x' * 200000)"),
                                ({"max_bytes": 2048}, "os.write(1, b'x' * 200000)"),
                                ({"max_records": 2},
                                 "[emit(dict(type='progress')) for _ in range(20)]")):
            with self.subTest(options=options, output=output):
                client = self.client("sys.stdin.buffer.readline()\n" + output, **options)
                with self.assertRaisesRegex(RpcError, "limit"):
                    client.request("get_state")
                self.assertLessEqual(len(client.stderr) + len(client.stdout), client.max_bytes)
                self.assertLessEqual(len(client.records), client.max_records)
                self.assert_closed(client)

    def test_environment_excludes_credentials_and_host_resources(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "NODE_OPTIONS": "bad",
                                     "PI_CODING_AGENT_DIR": "/host", "HOME": "/host"}):
            nested = self.root / "nested"
            nested.mkdir()
            env = isolated_environment(nested)
        self.assertEqual(set(env), {"PATH", "HOME", "PI_CODING_AGENT_DIR", "TMPDIR", "LANG", "TERM"})
        for key in ("HOME", "PI_CODING_AGENT_DIR", "TMPDIR"):
            self.assertTrue(Path(env[key]).is_relative_to(nested))

    def test_smoke_fake_host_only_sends_read_commands_and_cleans_fixture(self):
        fake = self.root / "fake-pi"
        fake.write_text(f"#!{sys.executable}\n" + textwrap.dedent("""
            import json, os, sys
            assert set(os.environ) <= {'PATH', 'HOME', 'PI_CODING_AGENT_DIR', 'TMPDIR', 'LANG', 'TERM', 'LC_CTYPE'}
            if sys.argv[1:] == ['--version']:
                print('fake-pi-test')
                sys.exit(0)
            assert '--no-extensions' in sys.argv and '--no-mcp' in sys.argv
            for line in sys.stdin.buffer:
                request = json.loads(line)
                assert request['type'] in ('get_state', 'get_commands', 'get_available_models', 'get_available_thinking_levels')
                data = {'get_state': dict(isStreaming=False, messageCount=0), 'get_commands': dict(commands=[]), 'get_available_models': dict(models=[]), 'get_available_thinking_levels': dict(levels=['off'])}[request['type']]
                print(json.dumps(dict(type='response', id=request['id'], command=request['type'], success=True, data=data)), flush=True)
        """), encoding="utf-8")
        fake.chmod(0o700)
        report = smoke(str(fake), 2)
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(len(report["checks"]), 4)
        self.assertEqual(report["version"], "fake-pi-test")
        self.assertEqual(report["shutdown"]["exit_code"], 0)
        self.assertIn("plugin_discovery", report["skipped"])
        self.assertFalse(Path(report["cwd"]).exists())

    def test_invalid_timeout_overrides(self):
        client = self.client("""
            for line in sys.stdin.buffer:
                reply(json.loads(line), data=dict(disposition='started'))
        """)
        response = client.request("prompt")
        for timeout in (0, -1, float('nan'), float('inf')):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(ValueError, "finite and positive"):
                    client.request("get_state", timeout=timeout)
                with self.assertRaisesRegex(ValueError, "finite and positive"):
                    client.wait_settled(response, timeout=timeout)

    def test_report_is_exclusive_and_missing_host_is_blocked(self):
        output = self.root / "result.json"
        with patch("tools.pi_validation.shutil.which", return_value=None):
            self.assertEqual(main(["--output", str(output)]), 1)
        before = output.read_bytes()
        self.assertEqual(json.loads(before)["status"], "blocked")
        with self.assertRaises(FileExistsError):
            main(["--output", str(output)])
        self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
