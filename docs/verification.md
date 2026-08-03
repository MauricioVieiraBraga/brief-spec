<!-- briefspec:verification:v1 version=0.2.1 -->
# BriefSpec v0.2.1 verification record

This record separates direct deterministic evidence, live-host evidence, and
externally pending evidence for the v0.2.1 release candidate. It was last
updated on 2026-08-03.

The public GitHub release remains v0.2.0 until the v0.2.1 tag and release
workflow complete. A prepared source tree is not publication proof.

## Direct deterministic evidence

The following checks ran from the v0.2.1 source checkout on macOS:

- `uv run ruff check .` passed.
- `uv run python scripts/verify-release.py` passed 258 source checks.
- A clean temporary `uv build` produced the v0.2.1 wheel and source
  distribution; Twine passed both and wheel verification passed 295 checks.
- `uv run pytest --cov=briefspec --cov-report=term-missing` passed 228 tests
  with 96.14% branch coverage, above the configured 85% gate.
- Every Session Checkpoint mode passed a mode-specific JSON Schema contract
  test, and vague proof without an inspectable locator was rejected.
- The Codex project installer generated a Git-root-resolved POSIX command and a
  PowerShell `commandWindows` override.
- The installed `SessionStart` command executed successfully from
  `docs/architecture/` inside a temporary Git repository whose path contained
  spaces.
- Package, plugin, marketplace, README badge, version-pinned installation URL,
  changelog, and this verification marker are checked against one version by
  `scripts/verify-release.py`.
- Every GitHub Action reference uses a Node 24 release pinned to a full commit
  SHA and enforced by the release verifier.

The CI matrix repeats the nested-directory execution test on Ubuntu and
Windows. That matrix is configured in `.github/workflows/ci.yml`; it is not
reported as passed until GitHub executes the v0.2.1 commit.

## Build and release evidence

The tag-driven release workflow:

1. rejects a tag that does not match `pyproject.toml`;
2. verifies source release surfaces;
3. builds the wheel and source distribution once;
4. runs Twine metadata checks;
5. verifies byte-identical wheel resource projections;
6. records SHA-256 checksums;
7. generates GitHub build provenance for both distributions;
8. creates the GitHub release with the verified artifacts.

The workflow definition is direct structural evidence. Release assets,
attestations, and the release URL remain pending until the `v0.2.1` tag is
pushed and the workflow succeeds.

## Native and live-host evidence

| Host surface | Evidence | Result |
| --- | --- | --- |
| Codex project installer on macOS | Generated hooks executed from a nested Git directory | Passed |
| Codex project installer on Windows | `commandWindows` generated and covered by a Windows CI job | Pending CI execution |
| Codex CLI 0.146.0 plugin bundle | Isolated marketplace add, plugin install, and plugin inventory | Passed |
| Codex CLI 0.146.0 model turn | Ephemeral read-only task launched from Nexo `docs/`; live activation, skills, five hooks, and validated Outcome Brief observed | Passed, task `019fc313-3823-7040-96a3-3e08baf97fae` |
| Claude Code | v0.2.0 native skill and project-root acceptance | Previously passed; unaffected by this patch |
| Copilot CLI | v0.1 live skill and Outcome Brief acceptance | Previously passed; unaffected by this patch |

Historical v0.1.0 evidence is retained in
[`verification-v0.1.0.md`](verification-v0.1.0.md). Historical host results are
not silently promoted to v0.2.1 evidence.

## Structurally verified, externally pending

- VS Code: discovery and Agent Debug Logs inspection must be repeated in a
  compatible installed version.
- Copilot cloud agent: a checked-in bridge can be verified locally, but only a
  real cloud-agent task proves GitHub loaded and executed it.
- GitHub.com Chat and Copilot code review: BriefSpec claims no automatic
  lifecycle integration.
- GitHub immutable releases: repository-level immutable-release protection must
  be confirmed before calling the tag and attached assets immutable.

## Primary design sources

- [Codex hooks](https://learn.chatgpt.com/docs/hooks) — hook commands run with
  the session working directory; repository-local commands should resolve from
  the Git root.
- [Python Packaging release workflow](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
  — build artifacts once, transfer them between jobs, and publish from a tagged
  workflow.
- [GitHub artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
  — generate verifiable build provenance for release artifacts.
