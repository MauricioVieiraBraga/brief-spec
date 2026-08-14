# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses semantic versioning.

## [Unreleased]

## [0.5.0] - Unreleased candidate

### Added

- Canonical Brief-Spec identity: `brief-spec` distribution and CLI plus the
  `brief_spec` Python package, while preserving all `briefspec` 0.x aliases.
- Eight deterministic work-type profiles and open subject slugs with local,
  bounded classification; explicit, host, inferred, and fallback origins;
  categorical confidence; sticky task behavior; and pivot handling.
- `types list`, `types show`, and `classify` CLI commands, plus the universal
  `brief-spec` routing skill.
- Typed Markdown wrapper and `brief-spec-delivery/2.0` canonical schema with
  classification, ordered explanations, harness/model metadata, provenance,
  artifacts, work items, manifests, and receipts.
- Data-driven harness registry and native user/project installers for Codex,
  Claude Code, OMP, Grok Build, and Kimi Code; experimental adapters for
  Copilot, Cursor Agent, and Goose.
- OMP native extension lifecycle and Kimi user-plugin integration, including
  the project-scope skills-only capability boundary.
- Canonical `brief-spec-delivery/2.0` exports for deterministic Markdown,
  JSON, self-contained offline HTML, ZIP, spoken text, and SSML, with optional
  PDF and MP3 renderer packages.
- Provider-neutral provenance for Exa, Tavily, Firecrawl, local files, and
  future research systems without adding their SDKs to the core package.
- Ordered bundle manifests, external delivery receipts, SHA-256 integrity,
  fixed ZIP metadata, and structural, resolved, rendered, and delivered
  verification levels.
- Portable Outcome Brief, Session Checkpoint, evidence, delivery, manifest,
  and receipt schemas plus a self-contained offline compound schema bundle.
- Sanitized, source-fingerprinted live-host evidence and exact-SHA release
  authorization inputs for build-once publication.
- Browser, PDF, local-audio, clean-wheel, clean-sdist, rollback, hermetic-host,
  and cross-harness live acceptance gates.

### Changed

- The unpublished `0.3.0` delivery and `0.4.0` renderer candidates are folded
  into this release; no intermediate packages will be published.
- Canonical state uses `BRIEF_SPEC_HOME` and `~/.local/state/brief-spec`, while
  the legacy variable, state, markers, receipts, schemas, and renderer entry
  point group remain readable through the `0.x` line.
- Optional renderer distribution names are now `brief-spec-renderer-pdf` and
  `brief-spec-renderer-audio`, version-aligned at `0.5.0`.
- Human-facing Markdown, HTML, and PDF projections are status-first while the
  unchanged Outcome Brief and Session Checkpoint `1.0` contracts remain
  backward compatible.
- Verification is zero-network and no-plugin by default. Public URL checks and
  renderer code loading require explicit consent.
- Inferred classifications are capped at medium confidence; ambiguous or
  conflicting intent falls back to `general` instead of fabricating certainty.
- Harness maturity is evidence-based: Codex, Claude Code, OMP, Grok Build, and
  Kimi Code pass their required local live matrices; Copilot, Cursor, and Goose
  remain explicitly experimental.

### Fixed

- Grok Build now accepts native camelCase assistant payloads, obtains exact
  classification metadata through one bounded Stop-hook repair, and uses the
  actual `read_file`/`search_replace` native tool IDs for its disposable
  implementation gate.
- Receipt ownership now requires the recorded path and prior hash. Locally
  modified managed files are preserved and staged beside the new candidate
  rather than overwritten.
- Runtime auto-detection follows explicit payload, stable session identifier,
  mutually exclusive host markers, then deterministic fallback precedence.
- Doctor and installer tests no longer depend on optional host executables from
  the maintainer's real `PATH`.

### Security

- Resolved verification rejects loopback, private, link-local, metadata,
  multicast, unspecified, redirected-private, and other non-public network
  targets unless the relevant operation is explicitly permitted.
- File and archive verification now bounds input size, member count, expanded
  size, compression ratio, redirects, requests, headers, and fetched bodies.
- Path traversal, absolute archive members, duplicate names, special files,
  symlink escapes, command-like evidence, and silent workspace escapes are
  rejected.
- Hook input, transcript tails, session state, and repair behavior remain
  bounded; secrets and raw transcripts are excluded from artifacts and
  receipts.

## [0.4.0] - Unpublished candidate folded into 0.5.0

### Added

- Optional `briefspec-renderer-pdf` package using canonical offline HTML and Playwright Chromium,
  with A4/Letter output and Poppler-backed verification.
- Optional `briefspec-renderer-audio` package for local macOS `say` plus `ffmpeg` MP3 output and
  explicitly consented OpenAI text-to-speech.
- Renderer discovery through the `briefspec.renderers` Python entry-point group.
- Linux PDF/browser and macOS local-audio end-to-end CI jobs, plus mocked OpenAI boundaries.

## [0.3.0] - Unpublished candidate folded into 0.5.0

### Added

- Canonical `briefspec-delivery/1.0` envelope with source metadata, provenance, artifacts, and
  multi-agent work activity.
- Deterministic Markdown, JSON, self-contained HTML, and ZIP downloads generated from one object.
- External delivery receipts and structural, resolved, rendered, and delivered verification.
- `export`, `bundle`, `verify`, `deliver`, `setup`, and `capabilities` CLI commands.
- Atomic multi-runtime setup plus doctor repair, all-scope inventory, and version-drift checks.
- PyPI Trusted Publishing workflow, release manifest, restart-safe digest checks, and staged
  GitHub Release finalization.

### Changed

- Rich evidence annotations can include a safe `kind=` hint while legacy annotations remain valid.
- Spoken text and SSML are exportable only from a Spoken Checkpoint.

## [0.2.1] - Unpublished candidate from 2026-08-03

### Fixed

- Codex project hook commands resolve the Brief-Spec bundle from the Git root, so all lifecycle
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

[Unreleased]: https://github.com/luanmorenommaciel/brief-spec/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/luanmorenommaciel/brief-spec/compare/v0.2.0...v0.5.0
[0.4.0]: https://github.com/luanmorenommaciel/brief-spec/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/luanmorenommaciel/brief-spec/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/luanmorenommaciel/brief-spec/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/luanmorenommaciel/brief-spec/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/luanmorenommaciel/brief-spec/releases/tag/v0.1.0
