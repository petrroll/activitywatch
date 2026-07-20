# Flexible Activity Model

ActivityWatch historically derived most reports from one window bucket, then filtered that stream with one AFK bucket. That works for standard desktop use, but it cannot naturally express the cases raised in [discussion #1169](https://github.com/orgs/ActivityWatch/discussions/1169): a virtual-desktop watcher that changes categorization, or a meeting watcher that contributes activity even while the computer is AFK.

The flexible model instead treats **activity as time with overlapping facts**, not as a privileged window event.

## Model

A **source** selects one or more watcher buckets for a device and exposes selected event fields. Its activity options are:

- **`creates_activity`** ("Can create activity periods"): its event intervals contribute to activity coverage.
- **`keeps_active`** ("Counts as active even while AFK"): its covered time is added to active time before AFK masking. It requires `creates_activity`.

Sources without this option can still be used by active-time and category rules, but cannot create reportable time by themselves. When sources overlap, no source takes precedence. Their fields coexist under `$source.<source-id>.<field>`, and the interval is split wherever any source starts or ends.

Simple mode configures ordinary auto-discovering sources for App & window (coverage), browser tabs (context), and stopwatch (coverage with `keeps_active`). None has activity or categorization precedence: facts are namespaced like every other source, and Simple app/title predicates explicitly reference App & window. Advanced profiles can change fields or buckets, change coverage or AFK behavior, or remove any default. Merely having a watcher bucket never adds coverage. Profiles persist `source_defaults_version` so each versioned default is applied once while later removals remain durable. AFK and audible-browser checks remain visible active-time inputs rather than category sources.

## In the UI

- **Simple** keeps the familiar app/title categories and automatic AFK behavior.
- **Advanced** adds sources, nested rules, weights, prerequisites, host limits, and custom active-time rules without changing the underlying model.
- **Can create activity periods** is a profile-wide source setting: it affects every report, not only the rule where it is changed.
- **Counts as active even while AFK** keeps that source's covered time when AFK filtering is enabled.
- Active-time rules can remove covered time, but cannot create time where no activity-producing source has data.

```mermaid
flowchart LR
    B[Host-local watcher buckets] --> S[Resolve configured sources]
    S --> C[Union periods from sources that can create activity]
    C --> P[Split at every source boundary]
    S --> P
    P --> F[Attach all overlapping fields by source ID]
    F --> A[Apply the active-time rule]
    A --> R[Evaluate category rules and scores]
    R --> H[Resolved activity stream for this host]
```

For example, a window, meeting, and virtual-desktop watcher can all describe the same period:

```mermaid
flowchart TB
    W["09:00-10:00 window<br/>app = Visual Studio"] --> X["09:20-09:45 resolved slice"]
    D["09:20-10:30 desktop<br/>name = Personal"] --> X
    G["09:15-09:45 meeting<br/>subject = Design review"] --> X
    X --> E["$source.window.app = Visual Studio<br/>$source.desktop.name = Personal<br/>$source.meeting.subject = Design review"]
    E --> K["Rules decide the category"]
```

## Rules and resolution

Active-time and category rules use the same expression shape:

- a predicate selects a source, one or more fields, a regular expression, optional negation, host, and match weight;
- **All (AND)** requires every child and adds their weights;
- **Any (OR)** requires one child and uses only the highest-scoring matched branch;
- nested groups provide parentheses;
- category prerequisites can require selected parent or ancestor rules to match.

The winning category is chosen by match score, then category tie-break priority, hierarchy depth, category-set priority, and definition order. Source order is not part of this decision. A negative predicate requires relevant source data to exist; missing data is not treated as a successful negative match.

The active-time rule masks within resolved coverage; it never creates time outside it.

Each host is resolved independently. Bucket ownership is checked before querying, so data does not leak across hosts. Host-scoped optional sources additionally use `query_bucket_optional(bucket, expected_hostname)` when the server advertises `query.query_bucket_optional.expected_hostname.v1`; a stale or manually entered bucket ID then returns no events unless its stored hostname matches. Older servers retain client-side ownership filtering. Resolved host streams are combined afterward using the existing device-order precedence.

Canonical resolution preserves original event intervals. Aggregation by app, title, or category happens only in report summaries, never before enrichment or categorization. A `keeps_active` source contributes its coverage to active time; the default stopwatch source uses this to preserve legacy stopwatch behavior while remaining an ordinary configurable source.

Reports expose the resolved stream as **activity**. Category and duration summaries work for every source shape. Profiles explicitly select `app_title_source_id` and `browser_focus_source_id`, both defaulting to App & window. If a selected source is absent or lacks the required fields, those optional summaries are empty rather than inferring another source.

## Compatibility and API impact

This is a query/settings migration, not a datastore migration. Existing buckets, events, watcher APIs, ingestion clients, and SQLite data remain unchanged.

The server info response adds an optional `capabilities` list. The Query2 HTTP endpoint is unchanged; namespaced overlap enrichment, active-period expressions, scored categorization and explanation, and the optional hostname argument are additive functions. Old clients can ignore the additive field. New desktop dashboards require the v2 capabilities and show an unsupported-state notice instead of substituting legacy results.

Settings add `activity_profiles_v2` and `category_sets_v2` through the existing arbitrary-JSON settings API. Loading old settings creates the v2 model in memory; it is persisted only after an explicit save. Legacy `classes`, the predecessor category set, and AFK settings are refreshed as compatibility projections for older clients. Advanced rules that cannot be represented faithfully project to no rule rather than being silently flattened.

WebUI, Python, and Rust provide separate source-only v2 builders (`CanonicalQueryParamsV2`/`canonicalEventsV2`, and `CanonicalQueryV2Options`/`try_build_canonical_events_v2` in Rust). They accept explicit coverage, context, and active-time sources and never accept or synthesize `bid_window`, `bid_afk`, `legacy_window_mode`, or root `app`/`title`.

The older desktop builders remain explicit compatibility APIs for old UIs and external callers. Their `bid_window`, `bid_afk`, `activity_sources`, `background_sources`, root aliases, and `"window"` report section are not mixed into the v2 dashboard path. Android remains a separate legacy query path. New integrations should use v2 builders, namespaced facts, and the generic `"activity"` report section.

Rust's public `QueryError` is now `#[non_exhaustive]` because datastore failures need distinct server-error classification. This is an intentional source-level change for exhaustive downstream matches: integrations must include a wildcard arm. `AdvancedQueryOptions` should likewise be constructed with `..Default::default()` so additive fields remain compatible.

The legacy Query2 string grammar cannot represent any query-bound string ending in an odd number of backslashes. Query builders now reject that case explicitly instead of emitting a corrupted query; a future versioned JSON wire grammar is required to remove this protocol limitation.

Advanced v2 evaluation requires updated backend capabilities. Release packaging publishes updated `aw-core` and the Rust transform/query crates first; then updates and locks `aw-client`, `aw-server`, `aw-client-rust`, and `aw-server-rust`; then updates nested WebUI and `aw-server-rust` pins in Python, Rust, and Tauri distributions; and finally refreshes the top-level submodule pins. Mixed-version desktop installations show the unsupported state until that sequence is complete.
