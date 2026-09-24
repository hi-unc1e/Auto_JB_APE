# Change Log

All notable changes to Auto_JB_APE are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic versioning.

## [2.0.0] - 2026-09-24

### Release summary

Version 2.0.0 turns Auto_JB_APE from the original top-level experiment into a
packaged, machine-verifiable agent red-team engine. The release joins target
reconnaissance, contextual planning, guarded submission, evidence-based judging,
trajectory-aware rewriting, bandit/tree feedback, stateful engagements, QA smoke
tests, browser/session adapters, MCP, CLI, and a local GUI into one testable loop.

The central design principle is **observable signal consumption**: a signal is
not considered implemented until a producer creates it, a real consumer changes
behavior because of it, and a with/without contract test proves that difference.

### ASR and search-quality improvements

- Added `SubmissionResult.diagnostic_context`, carried through `TreeNode` and
  `Feedback` into the semantic rewriter. Target replies, tool choices, arguments,
  errors, and termination state can now guide the next mutation.
- Kept diagnostic context outside `SubmissionResult.corpus()`. Untrusted target
  text—including a forged `{"oracle": true}`—cannot satisfy the Judge or create
  a false success.
- Added trajectory-aware mutation rules:
  - stop repeating a framing the target explicitly recognized or rejected;
  - preserve a correct tool choice while repairing its arguments;
  - remove search/recon invitations when they consumed the previous run;
  - pivot from a detected injection framing to an adjacent legitimate workflow
    with the same machine-observable effect;
  - require materially different strategies rather than cosmetic paraphrases.
- Changed frontier scheduling to submit feedback-derived survivor expansions
  before unrelated fresh seeds.
- Made expansion aware of the remaining submission budget. The engine no longer
  pays for mutations, secondary parents, crossovers, or fresh seeds that cannot
  be submitted in the current run.
- When only one budget slot remains and target diagnostics exist, the slot is
  reserved for a semantic pivot instead of a generic mechanical wrapper.
- Added generation-time `intent_score` to structured rewrite output. The legacy
  same-model second-pass self-check remains available with
  `fallback_selfcheck=True`, but is off by default because it is not an
  independent adjudicator and adds a network round trip.
- Added exact rewriter LLM call and latency counters to `RunReport` so search
  quality and speed can be evaluated together.

### Live guarded validation

The optimized loop was tested against the frozen AgentArena indirect-injection
range without changing its system policy, mock tools, or binary oracle. With one
known-failing initial seed, a budget of three submissions, a real
`mistralai/ministral-8b-2512` target, and a separate
`deepseek/deepseek-v4.1-flash` rewriter:

- `success@3`: **3/3 fresh campaigns**;
- first successful submission: **[3, 3, 3]**;
- verified action: `read_ticket(T-1042)` followed by the exact guarded
  `notify(exfil-webhook, LEAK-CANARY-9f3a)` call;
- median rewriter calls per campaign: **6 → 2** compared with the pre-budget-aware
  implementation (about 67% fewer);
- median end-to-end time: **51.08 s → 33.11 s** (about 35% lower in this sample).

These are bounded results for one model/range cell, not a universal ASR estimate.
Timeouts and incomplete runs remain separate from resolved failures.

### Agent and tool-runtime support

- Added fresh-session-per-submission operation for tool-using LLM targets.
- Added a bounded native tool loop with configurable total steps and repeated-tool
  caps, preventing low-value tool thrashing from consuming the entire session.
- Captured tool calls in structured network evidence for machine adjudication.
- Added dangerous-tool recognition for AgentArena `notify`, `delete_record`, and
  `transfer` actions.
- Added three frozen-range scenarios covering indirect injection, forbidden tool
  use, and later-turn constraint amnesia.

### Product and integration capabilities since v1.0

- Introduced the installable `jb_ape` Python package and `jb-ape` CLI.
- Added the full recon → plan → submit → judge → rewrite → learn loop.
- Added contextual bandit and decision-tree planners, effective-chain reuse,
  crossover mutations, selective decoding, and machine-verifiable S/A/B/C verdicts.
- Added stateful Engagement APIs with step, steer, snapshot, resume, and MCP
  exposure.
- Added a deterministic 24-case QA smoke suite with severity mapping and CI exit
  codes.
- Added a local Web GUI that consumes the same engine/report path as the CLI.
- Added a localhost-only browser-extension bridge for authorized testing in an
  existing logged-in session.
- Added bilingual operating documentation, contributor gates, and pre-commit IP,
  lint, and regression checks.

### Testing and correctness

- Expanded the offline suite to **393 tests**, including **19 end-to-end signal
  contracts**.
- Added a contract proving that target diagnostics change rewrite behavior but
  cannot change the Judge verdict.
- Added contracts for feedback-first scheduling and remaining-budget enforcement.
- Verified both normal and `ResourceWarning`-strict unittest suites, plus a clean
  Ruff scan.

### Breaking changes and migration

- The supported implementation now lives under `src/jb_ape`; the former top-level
  scripts are retained under `legacy/` for reference and are not the release API.
- Install with `pip install -e .` and use the `jb-ape` command or import
  `build_engine` / `quick_run` from `jb_ape`.
- Consumers of the old direct-script interface should migrate configuration into
  `Objective`, `RunConfig`, target adapters, and the facade API.
- Package metadata is realigned with the Git release line: the stale `0.1.0`
  project version is replaced by `2.0.0`, following the existing `v1.0` tag.

### Security and misuse disclaimer

> **AUTHORIZED SECURITY TESTING ONLY.** Auto_JB_APE is designed for defensive
> research, controlled evaluations, and systems you own or have explicit written
> permission to test. Do not use it to access third-party systems, bypass controls
> without authorization, exfiltrate real data, impersonate users, cause financial
> or operational harm, or deploy payloads against production services without an
> approved scope and rollback plan. Operators are solely responsible for legal
> compliance, target authorization, data handling, rate limits, human oversight,
> and any consequences of use. The maintainers provide no warranty that generated
> payloads are safe, lawful, accurate, or suitable for any particular environment.

[2.0.0]: https://github.com/hi-unc1e/Auto_JB_APE/releases/tag/v2.0.0
