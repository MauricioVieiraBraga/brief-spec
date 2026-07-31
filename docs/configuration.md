# Configuration

Create a user or project configuration:

```bash
briefspec config init
briefspec config init --scope project
briefspec config show --json
```

User configuration lives under the BriefSpec state root. Project configuration is
`.briefspec.toml`. Only known presentation and retention keys are read; configuration cannot inject
commands or arbitrary executable paths.

## Defaults

```toml
[checkpoint]
policy = "suggest" # off | manual | suggest | auto
default_mode = "orient" # orient | teach | spoken
elapsed_minutes = 12
turns = 8
assistant_chars = 16000
tool_calls = 12
cooldown_minutes = 6
minimum_turns_after_checkpoint = 2

[outcome]
policy = "suggest" # off | suggest | enforce
one_repair = true

[state]
retention_days = 14
```

### Checkpoint policies

- `off`: no lifecycle checkpoint behavior; explicit skill use remains possible.
- `manual`: only explicit checkpoint requests.
- `suggest`: record eligibility and give the host context at a safe boundary.
- `auto`: request one checkpoint at the next agent-stop boundary.

### Outcome policies

- `off`: no lifecycle outcome behavior; explicit skill use remains possible.
- `suggest`: install the contract as session context.
- `enforce`: conservatively classify action requests and request one correction when the terminal
  handoff lacks a valid Outcome Brief.

Enforcement is intentionally opt-in. A stop hook cannot perfectly infer whether every conversational
turn is a terminal task boundary.

## State operations

```bash
briefspec state list --json
briefspec state prune --older-than 14
briefspec state prune --older-than 14 --dry-run
briefspec state reset --runtime codex --session SESSION_ID
```

Set `BRIEFSPEC_HOME` to isolate state for automation or testing. BriefSpec stores bounded metadata,
not raw session content.
