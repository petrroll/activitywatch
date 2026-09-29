# Flexible rules v2 executable conformance corpus

This directory is the cross-language, cross-engine data-contract suite for canonical flexible-rules queries. It compares normalized event intervals and event data; it deliberately does **not** compare query-text snapshots.

## Run

From any directory in a provisioned ActivityWatch superproject checkout:

```sh
scripts/tests/flexible_rules_v2/run.sh
```

Environment overrides are supported and are the only machine-specific inputs:

```sh
PYTHON=/path/to/venv/bin/python \
CARGO=/path/to/cargo \
RUSTUP_HOME=/path/to/rustup \
CARGO_HOME=/path/to/cargo-home \
scripts/tests/flexible_rules_v2/run.sh
```

For reduced development passes:

```sh
# Python builder on all three Python storage engines
scripts/tests/flexible_rules_v2/run.sh --python-only

# Python + TypeScript builders on all three Python engines
scripts/tests/flexible_rules_v2/run.sh --skip-rust
```

Use `--work-dir PATH` to retain generated queries/results at a known location, or `--keep-work-dir` to retain an automatically created successful run. Failed runs always print and retain their artifacts.

## Dependencies

- an editable/source-visible `aw-core` and `aw-client` in the selected Python environment;
- the primary `aw-server/aw-webui/node_modules` installation, including TypeScript (the driver loads the real TS source modules directly);
- Cargo/Rust with this workspace's dependencies available.

No path outside the checkout, globally installed Node package, or network server is required.

## Matrix

For each fixture, the runner:

1. builds Query2 through the real TypeScript, Python, and Rust canonical builders;
2. appends `RETURN = [events, not_afk]` (or, for the browser compatibility fixture, returns those streams plus `browser_events` and its summed duration);
3. runs every builder's output in Python with `MemoryStorage`, `PeeweeStorage`, and `SqliteStorage`;
4. runs every builder's output in Rust with `aw-query` and the in-memory `aw-datastore`;
5. strips datastore-assigned IDs, normalizes UTC timestamps/numbers, treats active-mask data as non-semantic, and compares every result with the fixture's explicit expected intervals/data and with every other matrix cell;
6. runs paired Python/Rust native document-boundary and settings endpoint suites for unsupported versions, malformed/pre-atomic reads, selected-set aggregate budgets, CAS/recovery revisions, and legacy-write status behavior.

Heartbeat decisions use immutable original durations and the true boundary facts of connected original-coverage components; fills are separate synthetic records, so original bounds continue to govern overlap precedence. Fixtures marked `partition_of` additionally assert, in every builder/backend cell, that the narrow canonical stream equals the wide stream clipped to that query interval. Profile fixtures carry a canonical document or raw predecessor settings as `profile_contract`; TypeScript and native drivers pass these through their real migration, compilation, discovery, and materialization paths. Python additionally exercises its public settings-aware client method against a temporary HTTP origin. Fixtures can restrict themselves to a public builder that has the relevant API, and expected compile errors are checked without pretending that a query executed.

## Fixture coverage

| Fixture | Behavioral contract |
|---|---|
| `true-query-bounds-and-original-source-origins` | Final clipping uses the requested period while overlap precedence retains original source bounds. |
| `newest-overlapping-context-fact-wins` | A later-starting context fact wins only for its real lifetime. |
| `generic-exact-preserves-gap` | Exact sources do not synthesize heartbeat coverage. |
| `heartbeat-equal-tie-goes-left` | Equal heartbeat anchors fill a gap from the left deterministically. |
| `heartbeat-longer-right-gets-gap-and-overlap-retained` | Heartbeat gap ownership and overlapping original facts remain distinct. |
| `heartbeat-halo-narrow-inside-gap` | A narrow query wholly inside a gap loads both halo anchors. |
| `heartbeat-halo-right-boundary-neighbor` | A fact beginning at the right query boundary participates in heartbeat choice. |
| `partition-exact-wide`, `partition-exact-narrow` | Exact-source narrow output is the clipped wide output. |
| `partition-heartbeat-original-duration-wide`, `partition-heartbeat-original-duration-gap` | Heartbeat decisions use immutable original durations across query partitions. |
| `partition-heartbeat-nested-wide`, `partition-heartbeat-nested-gap` | Nested facts and the surrounding gap are partition invariant. |
| `partition-heartbeat-boundary-anchors-wide`, `partition-heartbeat-boundary-anchors-gap`, `partition-heartbeat-boundary-anchors-both-sides` | Boundary halos, later-end precedence, and both-sided narrow queries agree with the wide stream. |
| `none-negation-scalar-alias-weight-and-prerequisite` | None, negation, scalar values, legacy aliases, weights, and prerequisites compose. |
| `keeps-active-union-unfiltered`, `keeps-active-union-filtered` | `keeps_active` contributes to the mask with and without event filtering. |
| `host-ownership-browser-and-host-category-priority` | Host ownership rejects foreign facts and category scores choose the intended source. |
| `multi-set-precedence-and-remapped-prerequisite` | Selected-set priority and prerequisite IDs survive compilation, including UTF-8 IDs. |
| `settings-aware-pre-atomic-v2-profile-wins-over-lossy-classes` | Complete predecessor-v2 arrays outrank a lossy classes projection. |
| `legacy-desktop-current-server-shim` | Ordinary desktop compatibility output uses the current pipeline and defaults to Uncategorized. |
| `legacy-find-bucket-prefix-and-host` | Current compatibility shims retain host-qualified prefix selectors. |
| `legacy-regex-select-keys` | Legacy `select_keys` projection still executes through the compatibility boundary. |
| `profile-audible-must-match-browser-family` | Audible Chrome facts do not activate Firefox focus. |
| `profile-audible-omitted-focus-uses-builtin-window` | Omitted focus-source metadata falls back to the configured window source. |
| `profile-audible-all-same-family-buckets` | Omitted audible options use profile policy and later configured-bucket ties win and enrich. |
| `profile-audible-chrome-does-not-match-brave-focus` | Browser-family matching distinguishes Chrome from Brave. |
| `legacy-focus-before-winning-browser-fact`, `legacy-focus-hides-newer-audible-fact`, `legacy-focus-losing-window-fact` | Current compatibility adapters preserve raw browser/focus facts until winning-fact active evaluation. |
| `profile-focus-preserves-winning-browser-fact` | Settings-aware focus/audible construction is the control for compatibility focus semantics. |
| `legacy-same-family-bucket-winner`, `legacy-same-family-newer-fact`, `profile-same-family-bucket-winner` | Current compatibility and settings-aware plans group every ordered bucket of a browser family before winning-fact resolution. |
| `partition-heartbeat-backfill-overlap-wide`, `partition-heartbeat-backfill-overlap-narrow` | An older heartbeat fact reappears after a newer overlap expires, invariant under partitioning. |
| `legacy-browser-projection-query-bounds` | Legacy browser projection and totals are clipped to the true query bounds. |
| `explicit-none-is-empty-mask` | An explicit none active expression yields an empty mask. |
| `active-winning-fact-overlap-and-expiry` | Active predicates see the winning source fact and reveal the older fact after expiry. |
| `active-winning-fact-contradiction` | Contradictory predicates cannot match different overlapping facts from one source. |
| `scalar-ecmascript-golden-vectors` | Category and active predicates share ECMAScript spelling for every required scalar vector. |
| `scalar-shortest-tie-category`, `scalar-shortest-tie-active` | Halfway binary64 values use exactly ECMAScript shortest-decimal tie rounding in both evaluators. |
| `ranking-weight-inclusive-boundary-winner` | Both ranking bounds are accepted and `+1_000_000` wins over `-1_000_000`. |
| `exact-tie-higher-event-id-wins` | Higher event ID wins an exact start/end tie on every datastore. |
| `exact-tie-later-bucket-wins` | Later configured bucket order wins an exact cross-bucket tie. |
| `heartbeat-exact-left-anchor-tie`, `heartbeat-exact-right-anchor-tie` | Same-bucket heartbeat boundary ties use later event order and coalesce the complete active stream. |
| `heartbeat-cross-bucket-left-anchor-tie`, `heartbeat-cross-bucket-right-anchor-tie` | Cross-bucket heartbeat boundary ties use later configured bucket order and coalesce the complete stream. |
| `heartbeat-same-bucket-left-anchor-gap-only`, `heartbeat-same-bucket-right-anchor-gap-only` | Narrow gap-only queries choose the later same-bucket boundary fact on either side. |
| `heartbeat-cross-bucket-left-anchor-gap-only`, `heartbeat-cross-bucket-right-anchor-gap-only` | Narrow gap-only queries choose the later configured bucket's boundary fact on either side. |
| `settings-fresh-default-categories` | Absent settings migrate to the shared defaults and classify `vim` as programming. |
| `settings-legacy-sets-selection-and-null-rule` | Legacy set selection preserves inactive sets and normalizes a historical null rule. |
| `two-selected-same-path` | Legacy migration retains ordered multi-set selection so canonical set ranking resolves duplicate paths. |
| `selected-repeat-reverse-and-inactive` | Selected-set IDs are deduplicated in requested order while inactive sets remain available. |
| `null-type-with-stale-regex` | Historical null rule types remain disabled even when stale regex metadata is present. |
| `ignored-regex-metadata-backslash` | Irrelevant settings metadata is omitted before Query2 representability checks and execution. |
| `canonical-select-keys-selected-field`, `canonical-select-keys-nonselected-field` | Canonical `select_keys` aliases survive compilation and restrict matching to the effective selector. |
| `unavailable-active-source-unfiltered` | An undiscovered declared builtin is an empty stream for unfiltered output. |
| `unavailable-active-source-filtered` | Filtering with an unavailable required builtin fails during profile materialization. |
| `unavailable-active-source-keeps-active` | Real `keeps_active` coverage permits filtering despite another unavailable active input. |
| `removed-browser-source-contributes-nothing` | Removing the configured browser source removes its audible-time influence. |
| `audible-later-silent-wins` | One ordered active source per browser family lets a later silent fact suppress an older audible fact. |
| `audible-newer-silent-expires` | An older audible fact reappears only after the newer silent winning fact expires. |
| `synthetic-collision-focus`, `synthetic-collision-browser_audible_0`, `synthetic-collision-afk`, `synthetic-collision-afk-enabled` | Generated AFK/audible IDs avoid every declared source ID and remain consistent in plans and expressions. |
| `afk-discovery-order` | Competing discovered AFK buckets use deterministic lexical order in every compiler. |
| `legacy-browser-partial-presence`, `legacy-browser-empty-presence`, `legacy-browser-absent-presence` | Compatibility browser reports are bounded by real browser presence and reject empty/absent sources. |
| `legacy-browser-presence-partial`, `legacy-browser-presence-empty`, `legacy-browser-presence-missing` | Browser presence remains correct when long raw facts overlap a narrow query period. |
| `report-browser-unknown-host-owner` | The Web report carries global ownership for the supported unknown-host browser fallback. |
| `legacy-full-desktop-current-wrapper` | Full desktop wrappers execute completely, including empty stopwatch/browser report setup. |
| `legacy-suffix-current-wrapper` | TypeScript suffix output is bound after root projection and categorization. |
| `legacy-multidevice-current-wrapper` | TypeScript multidevice output retains projected app/title/category data. |
| `legacy-context-active-prefix-selector` | Context-mode window facts load before active aliases and prefix selection works. |
| `context-browser-report-coverage` | Current compatibility browser output is bounded by context-mode canonical activity coverage. |
| `union-precedence-one-long-vs-many-short`, `union-precedence-partition-invariant` | First-stream host precedence suppresses every covered lower segment and is invariant to equivalent high-stream partitioning. |

The reserved Rust example has two stable machine-readable modes used by the runner:

```sh
cargo run -p aw-client-rust --example flexible_conformance -- generate FIXTURES OUTPUT
cargo run -p aw-client-rust --example flexible_conformance -- execute FIXTURES QUERIES OUTPUT
```
