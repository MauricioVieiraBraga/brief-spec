# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses semantic versioning.

## [Unreleased]

## [0.2.1] - 2026-08-03

### Fixed

- Codex project hook commands resolve the BriefSpec bundle from the Git root, so all lifecycle
  events continue to work when a task starts in a nested repository directory.
- Codex project installs include a PowerShell `commandWindows` override with the same root-stable
  behavior.
- The README badge, installation command, and verification record now stay aligned with the
  package version.
- Session Checkpoint JSON fields now match all Orient, Teach, and Spoken human-facing contracts.
- Markdown validation rejects proof without an inspectable locator and warns when evidence basis
  and result labels are missing.
- Repeat installation upgrades unchanged receipt-owned skill references while preserving
  independently modified files.

### Added

- Executable nested-directory regression coverage for Codex project hooks.
- A tag-driven release workflow that builds once, verifies the wheel, records SHA-256 checksums,
  generates GitHub build provenance, and attaches the artifacts to the release.
- Contract-equivalence tests for every Session Checkpoint mode.
- Full-SHA GitHub Actions pins with Dependabot maintenance.

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

[Unreleased]: https://github.com/luanmorenommaciel/briefspec/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/luanmorenommaciel/briefspec/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/luanmorenommaciel/briefspec/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/luanmorenommaciel/briefspec/releases/tag/v0.1.0
