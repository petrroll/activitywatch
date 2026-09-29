# Flexible activity model

ActivityWatch models activity as time covered by one or more sources with overlapping,
namespaced facts. A window event is a common source, not a privileged event type. This
supports meeting watchers, virtual desktops, browser facts, stopwatches, host-specific
rules, and other watcher data without changing raw buckets or watcher ingestion.

Canonical query composition remains in the client libraries. Current clients compile one
source plan and run one Query2 pipeline; servers provide storage, settings, and shared
transforms.

## Canonical settings

Current servers store one `rules_v2` envelope:

```json
{
  "revision": 1,
  "activity_profiles_v2": [],
  "category_sets_v2": []
}
```

`GET /api/0/settings/rules_v2` returns the envelope and returns 404 when the key is
absent. `POST` supplies the expected revision; replacement is atomic, increments the
revision, and returns 409 for a stale revision. Revisions are non-negative JSON-safe
integers (`0..2^53-1`). Malformed stored values remain exportable and require an explicit
repair. A malformed envelope with a valid safe revision retains that revision for CAS;
only a missing, invalid, or out-of-domain revision is repaired from revision 0. The
presence of malformed canonical data blocks ordinary migration and legacy rule writes
until that explicit repair.

Legacy settings keys (`classes`, `always_active_pattern`, `category_sets`,
`active_set_ids`, and predecessor v2 arrays) are compatibility views. Reads derive them
from `rules_v2`; representable writes translate to a complete canonical replacement under
the same lock. Partial or lossy advanced writes fail instead of creating another settings
authority. Unrelated preferences retain their existing API.

Settings are loaded without writes using this migration order:

1. a valid canonical `rules_v2` envelope;
2. complete predecessor v2 profile and category-set arrays;
3. legacy `category_sets` plus the deduplicated `active_set_ids` in their original order,
   preserving every inactive set and composing selected sets without a synthetic merged
   set;
4. `classes`;
5. the shared default categories when all category settings are absent.

An explicitly saved empty category set remains empty. Historical `{ "type": null }`
rules normalize to `none` only while migrating legacy data; strict canonical validation
still rejects them. Validators check the type and enum value of every present known field,
even when a built-in source has not discovered buckets yet. Only ownership completeness
which depends on discovery is deferred. Unknown properties on extensible model objects
are preserved as additive metadata (the envelope itself has a fixed shape); expression
walkers follow `rules` only for validated `all` and `any` nodes, so irrelevant properties
on other variants do not change execution.

## Sources and intervals

A source selects buckets, declares exposed fields and ownership/scope, and can have two
coverage roles:

- `creates_activity`: source intervals contribute reportable coverage;
- `keeps_active`: source coverage contributes active time independently of the active
  expression. This requires `creates_activity`.

Facts are exposed as `$source.<source-id>.<field>`. Optional presentation selectors
project facts to legacy root `app` and `title` fields, but presentation does not determine
coverage or rule semantics.

Each source has an `interval_policy`:

- `exact` preserves recorded intervals. It is the default for custom and stopwatch
  sources;
- `heartbeat` may fill short heartbeat gaps. Built-in window/browser and legacy AFK
  adapters select it explicitly.

Current builders load overlapping original bounds with
`query_bucket_optional_raw(bucket, expected_hostname?)`. Heartbeat sources load enough
halo for boundary normalization. `query_period()` supplies the unpadded query interval,
and every coverage, mask, and public projection is intersected with it. Frozen raw-event
HTTP reads retain their existing clipping and ordering contracts.

`flood_v2` preserves original records and emits separate synthetic records for fillable
gaps. It compares immutable adjacent anchors and uses one deterministic tie policy. The
left anchor is selected by furthest end, latest start, then later concatenated input; the
right anchor is selected by earliest start, longest end, then later concatenated input.
The longer anchor supplies the gap, with equal durations favoring the left. A previous
fill or query partition cannot change a later decision. The old `flood` transform is
retained only for explicit legacy Query2 programs.

## Fact precedence and active time

A source is resolved into non-overlapping fact slices before enrichment or active-rule
evaluation. The winning record has the latest start, then the later end. Raw source loads
are ordered by `(start, end, event id)`; Memory storage uses insertion order as its event
id. If bounds are identical, the later record in concatenated source order wins: later
bucket in the configured bucket list, then higher event id. Heartbeat normalization
preserves the original record origin.

Positive and negative predicates both inspect the winning fact for each slice. Missing
source data matches neither form. Predicate periods are then intersected for `all` and
unioned for `any`. Thus an `on [0,30)` record overridden by `off [10,20)` matches `on`
only on `[0,10)` and `[20,30)`, and `all(on, off)` is empty.

The effective active mask is:

```
(active-expression periods UNION keeps-active coverage)
INTERSECT reportable coverage
INTERSECT query period
```

It is computed even when the caller requests unfiltered events. Explicit `none` produces
an empty mask. A declared but undiscovered built-in source is an empty stream for
unfiltered output. Filtering by an unavailable active input is an error unless
`keeps_active` preserves the required coverage.

Audible time has one authority: the profile's configured browser source, including its
bucket selection, fields, ownership, and interval policy. Native materializers create one
synthetic active source per browser family containing that family's configured buckets in
order, leaving overlap precedence to the common fact resolver. Removing the configured
browser source removes its audible contribution. `include_audible` defaults from the
profile and only an explicit `false` call-site override disables it.

Browser reports reuse the same configured source plan. Exact sources receive no heartbeat
halo or fill; heartbeat sources use the common normalization. Reports expose only the
configured fields, so a source without `url` produces no URL or derived domain output.
Browser ownership, including the supported `hostname: "unknown"` fallback, is retained in
report projections; foreign-host buckets remain rejected.

## Rules and ranking

Active and category expressions contain predicates and nested `all`/`any` groups.
Predicates select a source, fields, regex, optional negation, host, value mode, and weight.
`all` adds matching child weights; `any` uses its highest-scoring matching branch.
Categories may require other rules from their own set.

In `value_mode: "scalar"`, strings are unchanged, booleans are `true`/`false`, JSON
integers retain exact decimal spelling, and finite JSON floats use ECMAScript
`Number.prototype.toString()` spelling. This includes `-0` as `0`, exponent form below
`1e-6` or at/above `1e21`, and integral floats without `.0`. Null, arrays, and objects do
not match scalar predicates.

Rule-ranking integers (`weight`, category `priority`, and `set_priority`) are JSON integer
tokens in `[-1000000, 1000000]`; booleans and every floating-point token, including
`1.0`, are invalid at settings boundaries. Expression-node and category limits bound
aggregate scores.

The category winner is ordered by expression score, category priority, hierarchy depth,
category-set priority, then definition order. Selected sets compose in profile order;
inactive sets remain stored and editable. Prerequisite identifiers are qualified within
their originating set so equal local IDs cannot collide.

## Hosts, projections, and compatibility

Hosts are resolved independently with source ownership checks. Global sources are
explicit. Device precedence is applied before category filters, preventing a filter from
revealing lower-priority activity hidden by an unfiltered host result.

Public legacy-signature builders are current-server shims. They translate window, AFK,
browser, stopwatch, context, selector, category, suffix, and multidevice inputs into the
v2 source plan, run the current pipeline, and project the old output shape. Omitting
capabilities targets a current server. Settings-aware APIs load the actual client's
server settings, capabilities, buckets, and hostname.

The old Query2 grammar implementation is confined to explicitly named `legacy_v1`
modules and is selected only for an old server or Android target. Frozen raw Query2
transforms such as `flood`, `tag`, `Rule.match`, clipped bucket reads, and field mapping
remain legacy API contracts. Legacy `categorize` adapts to the common evaluator without
applying canonical input-schema budgets and reports all failures as Query2 client errors;
it must never panic on user input.

Query2 event transforms have value semantics: they return new events and never mutate
input events or their data. `union_no_overlap` gives the complete first stream precedence,
removing or trimming every covered segment from lower-priority streams.

## Distribution and verification

The Python packages keep their normal published-version constraints; source-bundle builds
install submodules in dependency order. Rust consumers outside `aw-server-rust` use
`https://github.com/ActivityWatch/aw-server-rust` at an exact commit equal to the bundle's
`aw-server-rust` gitlink. Their lockfiles resolve that same commit. Local development
against an uncommitted sibling uses an explicit Cargo `patch` command-line override, not a
committed path dependency.

The executable corpus under `scripts/tests/flexible_rules_v2/` compares real Python,
Rust, and TypeScript builders across Python Memory/Peewee/SQLite and the Rust server.
Packaging also starts shipped server artifacts and verifies the rules/settings capability
contract exposed by `/api/0/info`.
