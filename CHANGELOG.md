# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses semantic versioning.

## [Unreleased]

## [0.2.0] - 2026-07-31

### Fixed

- Checkpoint suggestions are delivered once per pending checkpoint and repeat only after the
  configured cooldown, instead of on every completed tool call.

### Changed

- Claude Code project installs write skills to `.claude/skills/` so the host lists
  `outcome-brief` and `session-checkpoint` natively.
- Claude Code project hook commands anchor on `$CLAUDE_PROJECT_DIR` so they no longer depend
  on the session's working directory.
- `doctor` resolves scope automatically: a project install for the current directory wins,
  the user install is the fallback, and `--scope` forces either. The report header now names
  the scope it checked.

## [0.1.0] - 2026-07-31

### Added

- `outcome-brief` with five honest terminal statuses and an evidence-first field order.
- `session-checkpoint` with orient, teach, and spoken modes.
- Dependency-free Python control plane for validation, safe-boundary triggers, and bounded state.
- Codex, Claude Code, and GitHub Copilot lifecycle adapters.
- Native plugin and marketplace manifests for all three ecosystems.
- Reversible user and project installers with receipts and conflict preservation.
- Network-free Copilot cloud bridge built as a deterministic Python zipapp.
- Doctor, configuration, state-retention, and validation commands.
- Synthetic Apex experience pilot and clean-room verification surfaces.

[Unreleased]: https://github.com/luanmorenommaciel/briefspec/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/luanmorenommaciel/briefspec/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/luanmorenommaciel/briefspec/releases/tag/v0.1.0
