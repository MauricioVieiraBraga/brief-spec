# Compatibility

BriefSpec ships one Python core with host-specific discovery metadata. The compatibility promise is
therefore split into three independently testable layers:

1. the `outcome-brief` and `session-checkpoint` presentation contracts;
2. the hook payload and response adapter for each host;
3. installation and discovery in the host itself.

The first two layers are deterministic and covered by the repository test suite. The third layer
is checked with the host's own validator or a real installation whenever that host makes one
available.

## Supported surfaces

| Surface | Discovery | Hook configuration | Release gate |
| --- | --- | --- | --- |
| Codex CLI and app | `.codex-plugin/plugin.json` and `.agents/plugins/marketplace.json` | `hooks/hooks.json` | Install from an isolated local Codex marketplace |
| Claude Code | `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` | `hooks/hooks.json` | `claude plugin validate --strict` |
| GitHub Copilot CLI | `plugin.json` or the Claude-compatible manifest | `hooks/copilot.json` | Contract fixtures plus a manual CLI smoke test |
| VS Code Copilot agent | Claude-compatible plugin discovery | `hooks/hooks.json` | Agent Plugins view and Agent Debug Logs |
| GitHub Copilot cloud agent | Repository marketplace settings or the project bridge | `.github/hooks/briefspec.json` after bridge installation | A real cloud-agent job in the target repository |
| Python installer | Python package metadata and wheel resources | Generated host configuration | Python 3.11–3.14 tests and clean-room wheel installation |

BriefSpec requires Python 3.11 or newer. The release matrix exercises Python 3.11, 3.12, 3.13,
and 3.14. The hook runtime has no third-party Python dependency.

## Shared and host-specific files

The plugin root is deliberately the repository root:

```text
.codex-plugin/plugin.json          Codex metadata
.claude-plugin/plugin.json         Claude and compatible host metadata
plugin.json                        Copilot metadata
.agents/plugins/marketplace.json   Codex catalogue
.claude-plugin/marketplace.json    Claude catalogue
.github/plugin/marketplace.json    Copilot catalogue
hooks/hooks.json                   Codex, Claude, and VS Code hook shape
hooks/copilot.json                 Copilot CLI hook shape
skills/                            Shared presentation contracts
schemas/                           Machine-readable output contracts
scripts/briefspec-hook             Source-checkout plugin entrypoint
```

The wheel projects the skills, hooks, schemas, Copilot integration assets, and three plugin
manifests under `briefspec/resources/`. `scripts/verify-release.py` checks the configured
source-to-package mapping and, when given `--wheel`, confirms every projected file is present and
byte-identical in the built artifact.

## Lifecycle compatibility

BriefSpec uses only the shared command-hook subset:

| BriefSpec lifecycle | Codex / Claude / VS Code | Copilot CLI |
| --- | --- | --- |
| Session begins | `SessionStart` | `sessionStart` |
| User submits a prompt | `UserPromptSubmit` | `userPromptSubmitted` |
| Tool completes | `PostToolUse` | `postToolUse` |
| Context is about to compact | `PreCompact` | `preCompact` |
| Main agent is about to stop | `Stop` | `agentStop` |

The common hook file uses `${CLAUDE_PLUGIN_ROOT}`. Codex exposes it as a compatibility alias in
addition to its native plugin-root variables. The Copilot hook file uses `${PLUGIN_ROOT}`. Release
verification resolves every configured command target and fails if the target is missing,
non-executable, or wired to the wrong lifecycle event.

Portable Codex project installs use a different root contract from plugin-bundled hooks:
the generated POSIX command resolves the repository with
`git rev-parse --show-toplevel`, and `commandWindows` performs the equivalent
PowerShell lookup. CI executes the installed hook from a nested directory on
both Ubuntu and Windows.

Payloads and blocking responses are not identical:

- Codex and Claude expose the final assistant message to `Stop`, allowing BriefSpec to validate the
  actual Outcome Brief.
- Copilot CLI and VS Code do not provide the final assistant text in the same stable shape.
  BriefSpec can request one continuation at a natural boundary, but it does not claim semantic
  validation when the host has not supplied the text.
- Copilot `preCompact` is notification-only. It can preserve session state, but it cannot be the
  canonical checkpoint delivery mechanism.
- VS Code places a blocking `Stop` decision inside `hookSpecificOutput`; the other hosts use a
  top-level decision. The runtime adapter emits the host-specific response.
- Any automatic continuation is bounded by the host's stop-hook-active marker. BriefSpec never
  repeatedly blocks completion.

`session-checkpoint` remains the reliable explicit interface for an orient, teach, or spoken recap.
Timers and tool-count thresholds create eligibility only; checkpoints are delivered at natural
boundaries.

## Installation gates

### Codex

Codex currently has no separate `plugin validate` command. Its authoritative local gate is an
isolated marketplace installation:

```bash
export CODEX_HOME="$(mktemp -d)"
codex plugin marketplace add "$PWD" --json
codex plugin add briefspec@briefspec --json
codex plugin list
```

Start a new task after installation. Plugin hooks require explicit trust in Codex; `/plugins` and
`/hooks` provide the final interactive discovery check.

### Claude Code

Claude exposes non-interactive validators suitable for CI:

```bash
claude plugin validate .claude-plugin/plugin.json --strict
claude plugin validate .claude-plugin/marketplace.json --strict
```

For a local runtime smoke:

```bash
claude --plugin-dir .
```

### Copilot CLI and VS Code

Copilot CLI can install the source checkout directly:

```bash
copilot plugin install .
```

It can also install `briefspec@briefspec` after adding the repository marketplace. A release must
be exercised with the currently supported Copilot CLI before publication. That test remains a
local release gate because no standalone Copilot executable is provisioned in this repository's
CI environment.

For VS Code development, add the absolute plugin-root path to `chat.pluginLocations`, enable Agent
Plugins where organization policy permits it, and inspect `Developer: Show Agent Debug Logs`.
Visual discovery and hook execution are manual host checks; a JSON-only test is not equivalent.

### Copilot cloud agent

Cloud jobs run in an ephemeral, network-restricted Linux environment and do not inherit a
developer's personal plugin installation. The deterministic path is:

```bash
briefspec install copilot --scope project --project /path/to/repository
```

This writes the repository-local skill, hook, instruction, and self-contained zipapp bridge
described in `integrations/copilot/cloud/README.md`. Local tests can validate those artifacts, but
only a real Copilot cloud-agent job can prove that GitHub loaded and executed them. Local files are
destroyed with the job, and external persistence would require an explicitly allowed network
destination.

## Release checklist

Run the deterministic gates:

```bash
python scripts/verify-release.py
python -m ruff check .
python -m pytest --cov=briefspec --cov-report=term-missing
python -m build
python -m twine check dist/*
python scripts/verify-release.py --wheel dist/briefspec-*.whl
```

Then run the Codex and Claude host gates above. Before claiming Copilot compatibility for a
release, also complete:

1. a Copilot CLI source-plugin smoke test;
2. VS Code discovery and Agent Debug Logs inspection;
3. one real Copilot cloud-agent task using the repository bridge.

Do not promote a structurally valid manifest or a simulated payload to proof that a host actually
loaded the plugin.

Pushing a matching `v*` tag starts `.github/workflows/release.yml`. The workflow
requires the tag to equal the package version, re-runs the source and wheel
checks, records SHA-256 checksums, generates GitHub build provenance, and
creates the release from those verified artifacts. A configured workflow is
not evidence that a release ran; retain the successful run URL and release
asset list in the versioned verification record.

## Official references

- [Codex plugins](https://learn.chatgpt.com/docs/build-plugins)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Claude plugin reference](https://code.claude.com/docs/en/plugins-reference)
- [Claude hooks](https://code.claude.com/docs/en/hooks)
- [Copilot CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference)
- [GitHub Copilot hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference)
- [GitHub Copilot agent plugins](https://docs.github.com/en/copilot/concepts/agents/about-plugins)
- [VS Code agent plugins](https://code.visualstudio.com/docs/agent-customization/agent-plugins)
- [VS Code agent hooks](https://code.visualstudio.com/docs/agent-customization/hooks)
