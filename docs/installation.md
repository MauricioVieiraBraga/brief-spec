# Installation

## Prerequisites

- Python 3.11 or newer
- One or more supported hosts: Codex, Claude Code, or GitHub Copilot
- `uv` is recommended for isolated tool installation

BriefSpec has no runtime Python dependencies and performs no network calls from hooks.

## Recommended user installation

```bash
uv tool install git+https://github.com/luanmorenommaciel/briefspec.git
briefspec install all --scope user
briefspec doctor all --probe
```

Install or inspect one host:

```bash
briefspec install codex
briefspec install claude
briefspec install copilot
briefspec doctor copilot --probe
```

The portable installer copies the two skills, creates a self-contained runtime zipapp, merges host
hook configuration, and writes a receipt. It does not require a host executable to be present;
`doctor` reports a missing executable as a warning so configuration can be prepared ahead of time.

Preview without writing:

```bash
briefspec install all --dry-run
```

## Project and Copilot cloud installation

```bash
briefspec install copilot --scope project --project .
briefspec doctor copilot --scope project --project . --probe
```

Commit the generated `.github/briefspec/`, `.github/hooks/`,
`.github/instructions/`, and `.agents/skills/` files when a Copilot cloud job must discover them.
The bridge is network-free and stores only ephemeral counters during the job.

Codex and Claude also support project scope:

```bash
briefspec install codex --scope project
briefspec install claude --scope project
```

## Native plugin installation

The repository ships native manifests in addition to the portable installer.

### Codex

```bash
codex plugin marketplace add luanmorenommaciel/briefspec --ref main
codex plugin add briefspec@briefspec
```

### Claude Code

```bash
claude plugin marketplace add luanmorenommaciel/briefspec
claude plugin install briefspec@briefspec --scope user
```

For local development, pass the absolute checkout path to each marketplace command.

### Copilot CLI

```bash
copilot plugin marketplace add luanmorenommaciel/briefspec
copilot plugin install briefspec@briefspec
```

VS Code can discover plugins installed by Copilot CLI. Agent plugins and hooks in VS Code are
currently Preview features and may be disabled by organization policy.

Native plugin installation gives the host its normal plugin inventory experience. The portable
installer remains the most deterministic path because it also installs the standalone runtime and
receipts.

## Upgrade

```bash
uv tool upgrade briefspec
briefspec install all --scope user
briefspec doctor all --probe
```

Installation is idempotent. BriefSpec-owned assets are refreshed; foreign or locally modified files
cause a conflict instead of being overwritten. If any write fails during one runtime installation,
the installer restores every managed path to its exact pre-install content.

## Uninstall

```bash
briefspec uninstall all --scope user
```

Project installations require the same scope and project path used during installation. Uninstall
removes only matching receipt-owned files. Shared files still used by another runtime and modified
files are preserved with warnings.
