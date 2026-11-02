# Pi development validation

The source checkout includes a standard-library RPC harness and an isolated,
no-model smoke check. It is a development tool under `tools/`, outside the
installed `agent-team` package and product CLI. Run from the repository root:

```sh
PYTHONPATH=src python3 -m unittest tests.test_pi_validation
PYTHONPATH=src python3 tools/pi_validation.py --output "$TMPDIR/pi-host-$(date +%s).json"
```

Set `TMPDIR` to an existing writable temporary directory before running. Optional
`--pi /absolute/path/to/pi` selects the executable; otherwise it resolves `pi`
from PATH. `--timeout 10` sets each command deadline in seconds. Use a new output
filename for every run: reports are created exclusively and existing evidence is
never overwritten. The parent output directory must exist. Exit 0 means all core
RPC checks and orderly shutdown passed; exit 1 means the JSON report records a
blocked check (for example, missing Pi, startup rejection, or a deadline).
An invalid destination or argument raises an error before the check starts.

The runner first invokes `pi --version`, then launches Pi with:

```text
--mode rpc --no-session --no-extensions --no-mcp --no-context-files
--no-skills --no-prompt-templates --no-themes --no-tools
```

It sends only `get_state`, `get_commands`, `get_available_models`, and
`get_available_thinking_levels`. It requires successful, correlated responses,
an idle empty session, and list-valued catalog fields. It never sends `prompt`,
installs packages, or supplies a fake model/API key to bypass startup. An empty
model catalog is valid evidence of the no-account environment, not proof of
model availability. Pi 1.4.0 on Linux was observed returning no commands, no
models, thinking levels `["off"]`, and an unknown model in state.

Every invocation uses a fresh temporary HOME, PI_CODING_AGENT_DIR, cwd, and
TMPDIR, removed after child shutdown. The child environment allowlist is PATH,
HOME, PI_CODING_AGENT_DIR, TMPDIR, LANG, and TERM; provider credentials,
NODE_OPTIONS, user configuration overrides, and other inherited variables are
excluded. PATH selects the trusted installed executable; this is configuration
isolation, not an OS security sandbox or network firewall. The tool does not
read the real Pi agent directory or copy authentication files. Reports contain
only this isolated child's bounded protocol records and diagnostics; do not
reuse this logging setup with credentials without reviewing redaction needs.

The JSON report records the resolved executable, version command and exit,
RPC argv, temporary cwd, environment key names, responses, stderr, and shutdown
exit/action/reap state. Plugin installation/discovery, model prompts, delegation,
and child worktrees are explicitly skipped. Core `get_state` or `get_commands`
is not evidence that generated roles were discovered by a plugin. The existing
static rendering and installation-gate regressions can be checked separately:

```sh
PYTHONPATH=src python3 -m unittest tests.test_pi_support
```

Those tests check fixtures and declared settings, not actual plugin loading.

A separate no-model check on Linux loaded `pi-subagents@0.84.0` in Pi 1.4.0
from an isolated agent directory. The fixed npm archive was verified before
installation (SHA-256 `f9c038aac95d860c7adb77f02919b5016f410f8670f41a8cb911b56598742a02`),
and npm lifecycle scripts were disabled. A local observer called the installed
plugin's actual `discoverAgents` function inside Pi: all six generated roles
were found in project and user scopes, and the combined scope selected project
definitions for matching names. The plugin retained `model:effort` as its model
string with no separate thinking value; child execution was not exercised.

With no explicit tool filter, the observed registry included `subagent` and
`subagents_enable`; the unknown-model session activated `subagent` directly.
This does not verify loader-mode token savings. With an explicit
`--tools read,grep,find,ls` selection, extension delegation tools were filtered
out. A coordinator must include the appropriate plugin tool in its runtime
allowlist. Both checks exited cleanly without a model prompt. These observations
apply only to the stated versions and isolated fixtures; they do not establish
model routing, child tool enforcement, or worktree isolation.

Actual model routing, child tool boundaries, abort,
and child worktree isolation still require the separately approved live plan,
a fixed reviewed plugin version, and explicit model/provider/budget authorization.
This tool does not promote Pi support status or implement those later phases.

`tools.pi_validation.RpcClient` can be reused by development tests with an argv
array, explicit cwd/environment, and a context manager. It supports serialized
`request()`, `wait_settled(response)`, and idempotent `close()`. It assigns unique
IDs, parses binary JSONL on LF only (including JSON strings containing U+2028 or
U+2029), retains events arriving before the matching response, and continuously
drains stdout and stderr. Session output defaults to 4 MiB and 10,000 records;
excess output fails the check while pipes continue draining. Requests are capped
at 64 KiB. Failed responses, malformed records, mismatched IDs, premature exits,
and deadlines produce distinct diagnostics.

A successful prompt response means accepted/queued/handled, not completed.
`wait_settled()` returns immediately for `handled`; otherwise it waits for an
`agent_settled` event recorded since the request, including events before the
response. `agent_end` is insufficient. Settled is a session event, so concurrent
prompt completion cannot be inferred with this serialized driver. Callers must
assert task results and inspect failure events separately; settled alone does
not establish successful model work.

Closing stdin requests orderly shutdown, followed by bounded wait, terminate,
kill, and reap attempts if needed. The reader is stopped and streams closed;
cleanup failures are reported rather than claimed successful. Only the direct
owned child is signalled; this stage launches no extensions or child agents.
Descendant process supervision for later plugin/model scenarios is unverified.
The implementation uses POSIX pipe selectors; Linux is tested. Windows is not
supported by this harness, and other POSIX systems are unverified.

Unit tests use generated Python fake executables, never PATH Pi or real accounts.
They cover framing, Unicode, event ordering, response validation, output pressure,
limits, failure/exit/deadline diagnostics, SIGTERM escalation, reaping, stream
closure, environment isolation, and exclusive report creation. Run the real
smoke command separately to obtain host evidence.
