# Verified delivery

Brief-Spec treats downloads as projections of one canonical object, not as
separate model responses.

```text
bounded host output
  -> canonical brief-spec-delivery/2.0 object
  -> validation and safe evidence resolution
  -> Markdown, JSON, HTML, or optional renderer
  -> deterministic bundle manifest
  -> external delivery receipt
```

## Canonical envelope

The envelope keeps the existing Outcome Brief and Session Checkpoint `1.0`
objects unchanged under `brief`. It adds deterministic `classification` and ordered
`explanation.sections`, while `source` records the harness, adapter, model, and host boundary;
`provenance` can identify Exa, Tavily, Firecrawl, local files, or another
provider without importing a provider SDK; `artifacts` describes evidence
objects; and `work_items` carries explicit multi-agent activity.

Brief-Spec exports only the bounded region. Raw transcripts, authentication
state, and host resume tokens are not canonical fields and cannot leak through
the renderer pipeline by default.

## Determinism

Canonical time is captured once from an explicit `--created-at`,
`SOURCE_DATE_EPOCH`, source-file modification time, or finally the current UTC
time. Renderers reuse that value. ZIP member ordering, timestamps, modes,
compression, and manifest serialization are fixed, so the same canonical
object produces identical bundle bytes.

The bundle contains generated files and `manifest.json`. The adjacent receipt
template is intentionally outside the archive. `deliver` replaces that
template with a receipt containing the actual destination, delivery time, and
delivered-byte hash.

## Verification

`structural` verifies schemas and manifests. `resolved` additionally checks
local files, Git commit objects, and unauthenticated URLs. Command evidence is
never executed. Paths are contained within the declared workspace unless
`--allow-outside-workspace` is explicit.

`rendered` verifies the output itself: embedded canonical JSON and restrictive
CSP for HTML; Poppler text, fonts, metadata, geometry, and rendered-page hash
for PDF; or `ffprobe` codec, duration, disclosure, and source-Script hash for
MP3. Core ZIP members must be deterministic byte renderings of the embedded
canonical JSON. `delivered` verifies the external receipt against its local
destination.

Offline URL checks remain visibly unresolved instead of being promoted to
passing evidence.

## Optional renderers

Renderer packages register under the canonical `brief_spec.renderers` Python entry-point
group and the legacy `briefspec.renderers` group. The interface exposes capabilities, setup,
render, and verify behavior.
The core CLI discovers installed renderers without importing PDF, browser,
audio, or network dependencies into the base package.

PDF uses the exact self-contained HTML as its source. Audio reads only a Spoken
Checkpoint Script. Local macOS speech never falls back to OpenAI; OpenAI speech
requires an explicit provider, network consent, and runtime credential. The
OpenAI implementation follows the current
[text-to-speech guide](https://developers.openai.com/api/docs/guides/text-to-speech)
with `gpt-4o-mini-tts` and the recommended `marin` voice; model and voice remain
explicitly configurable and are recorded with the artifact.
