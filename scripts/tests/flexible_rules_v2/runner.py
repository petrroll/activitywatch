#!/usr/bin/env python3
"""Execute the flexible-rules v2 fixture matrix across builders and engines."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RETURN_SUFFIX = "\nRETURN = [events, not_afk];"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def run(command: list[str], *, cwd: Path = REPO) -> None:
    shown = " ".join(command)
    print(f"+ (cd {cwd}) {shown}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def with_capabilities(corpus: Dict[str, Any], fixture: Dict[str, Any]) -> Dict[str, Any]:
    options = json.loads(json.dumps(fixture["options"]))
    options["capabilities"] = list(corpus["capabilities"])
    options.setdefault("filter_categories", None)
    return options


def result_suffix(fixture: Dict[str, Any]) -> str:
    result_variables = fixture.get("result_variables")
    if result_variables == "suffix":
        suffix = fixture["legacy_options"]["return_variable_suffix"]
        return f"\nRETURN = [events_{suffix}, not_afk_{suffix}];"
    if fixture.get("return_browser"):
        return (
            '\nRETURN = {"events": events, "active": not_afk, '
            '"browser": browser_events, "browser_duration": sum_durations(browser_events)};'
        )
    return RETURN_SUFFIX


def supports_builder(fixture: Dict[str, Any], builder: str) -> bool:
    return builder in fixture.get("supported_builders", ["python", "typescript", "rust"])


def python_legacy_query(corpus: Dict[str, Any], fixture: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
    from aw_client.queries import (
        ActiveTimeSource,
        ActivityCoverageSource,
        ContextSource,
        DesktopQueryParams,
        canonicalEvents,
        fullDesktopQuery,
    )

    options = json.loads(json.dumps(fixture["legacy_options"]))
    if "python" not in fixture.get("omit_capabilities_for", []):
        options["capabilities"] = list(corpus["capabilities"])
    options.pop("filter_categories", None)
    options["context_sources"] = [
        ContextSource(**source) for source in options.get("context_sources", [])
    ]
    options["activity_coverage_sources"] = [
        ActivityCoverageSource(**source)
        for source in options.get("activity_coverage_sources", [])
    ]
    options["active_time_sources"] = [
        ActiveTimeSource(**source) for source in options.get("active_time_sources", [])
    ]
    params = DesktopQueryParams(**options)
    query_text = (
        fullDesktopQuery(params)
        if fixture.get("legacy_variant") == "full_desktop"
        else canonicalEvents(params)
    )
    return dataclasses.asdict(params), query_text + result_suffix(fixture)


def python_query(options: Dict[str, Any]) -> str:
    from aw_client.queries import (
        ActiveTimeSource,
        ActivityCoverageSource,
        CanonicalQueryParamsV2,
        ContextSource,
        canonicalEventsV2,
    )

    value = dict(options)
    value["activity_coverage_sources"] = [
        ActivityCoverageSource(**source)
        for source in value.get("activity_coverage_sources", [])
    ]
    value["active_time_sources"] = [
        ActiveTimeSource(**source) for source in value.get("active_time_sources", [])
    ]
    value["context_sources"] = [
        ContextSource(**source) for source in value.get("context_sources", [])
    ]
    return canonicalEventsV2(CanonicalQueryParamsV2(**value)) + RETURN_SUFFIX


def profile_bucket_listing(fixture: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        bucket["id"]: {
            "id": bucket["id"],
            "type": bucket["type"],
            "client": bucket.get("client", "fixture"),
            "hostname": bucket["hostname"],
            "created": bucket.get("created", "2024-01-01T00:00:00Z"),
            "data": bucket.get("data", {}),
        }
        for bucket in fixture["buckets"]
    }


@contextmanager
def fixture_settings_server(corpus: Dict[str, Any], fixture: Dict[str, Any]):
    contract = fixture["profile_contract"]
    document = contract["document"]
    legacy_settings = contract.get("legacy_settings")
    if legacy_settings is not None:
        get_all = json.loads(json.dumps(legacy_settings))
    else:
        get_all = {
            "activity_profiles_v2": document["activity_profiles_v2"],
            "category_sets_v2": document["category_sets_v2"],
            "classes": contract.get("lossy_classes", []),
            "always_active_pattern": "",
        }
    canonical_absent = contract.get("canonical_absent") or legacy_settings is not None
    if not canonical_absent:
        get_all["rules_v2"] = document
    server_capabilities = list(corpus["capabilities"])
    if canonical_absent:
        server_capabilities = [
            item for item in server_capabilities if item != "settings.rules_v2.v1"
        ]
    routes = {
        "/api/0/info": {
            "hostname": fixture["options"]["hostname"],
            "capabilities": server_capabilities,
        },
        "/api/0/settings": get_all,
        "/api/0/buckets": profile_bucket_listing(fixture),
    }
    if not canonical_absent:
        routes["/api/0/settings/rules_v2"] = document

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            value = routes.get(self.path.rstrip("/"))
            if value is None:
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(value).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def generate_python(corpus: Dict[str, Any]) -> Dict[str, Any]:
    output: Dict[str, Any] = {
        "schema_version": 1,
        "builder": "python",
        "queries": {},
        "options": {},
    }
    for fixture in corpus["fixtures"]:
        fixture_id = fixture["id"]
        try:
            if not supports_builder(fixture, "python"):
                raise RuntimeError("fixture does not apply to the Python builder")
            contract = fixture.get("profile_contract")
            if fixture.get("builder_mode") == "legacy_desktop":
                options, query_text = python_legacy_query(corpus, fixture)
            elif contract:
                from aw_client.client import ActivityWatchClient

                # Exercise the public settings-aware path against an actual HTTP
                # origin. This catches accidental reads from default localhost or
                # process-global settings instead of this client's server.
                with fixture_settings_server(corpus, fixture) as port:
                    client = ActivityWatchClient(
                        "flexible-conformance",
                        testing=True,
                        host="127.0.0.1",
                        port=port,
                    )
                    materialized = client.build_profile_query_v2(
                        profile_id=contract["selected_profile_id"],
                        hostname=fixture["options"]["hostname"],
                        filter_afk=fixture["options"].get("filter_afk", True),
                        filter_categories=fixture["options"].get("filter_categories"),
                        explain_categories=fixture["options"].get(
                            "explain_categories", False
                        ),
                    )
                options = dataclasses.asdict(materialized.params)
                query_text = materialized.query() + result_suffix(fixture)
            else:
                options = with_capabilities(corpus, fixture)
                query_text = python_query(options)
            output["options"][fixture_id] = options
            output["queries"][fixture_id] = query_text
        except Exception as error:  # recorded so the matrix reports every blocked fixture
            output["queries"][fixture_id] = {
                "error": f"{type(error).__name__}: {error}"
            }
    return output


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def storage(kind: str, directory: Path):
    from aw_datastore import Datastore
    from aw_datastore.storages import MemoryStorage, PeeweeStorage, SqliteStorage

    if kind == "memory":
        return Datastore(MemoryStorage, testing=True)
    if kind == "peewee":
        return Datastore(
            PeeweeStorage, testing=True, filepath=str(directory / "peewee.db")
        )
    if kind == "sqlite":
        return Datastore(
            SqliteStorage,
            testing=True,
            filepath=str(directory / "sqlite.db"),
            enable_lazy_commit=False,
        )
    raise AssertionError(kind)


def close_storage(value: Any) -> None:
    # The legacy storage implementations intentionally do not share one close API.
    strategy = value.storage_strategy
    if hasattr(strategy, "conn"):
        strategy.conn.commit()
        strategy.conn.close()
    if hasattr(strategy, "db") and hasattr(strategy.db, "close"):
        if not strategy.db.is_closed():
            strategy.db.close()


def populate_storage(datastore: Any, fixture: Dict[str, Any]) -> None:
    from aw_core.models import Event

    for bucket in fixture["buckets"]:
        datastore.create_bucket(
            bucket["id"],
            bucket["type"],
            bucket.get("client", "fixture"),
            bucket["hostname"],
            parse_timestamp(bucket.get("created", "2024-01-01T00:00:00+00:00")),
            data=bucket.get("data", {}),
        )
        datastore[bucket["id"]].insert(
            [
                Event(
                    timestamp=event["timestamp"],
                    duration=event["duration"],
                    data=event.get("data", {}),
                )
                for event in bucket.get("events", [])
            ]
        )


def jsonable(value: Any) -> Any:
    from aw_core.models import Event

    if isinstance(value, Event):
        return value.to_json_dict()
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    return value


def execute_python_query(query_text: str, fixture: Dict[str, Any], kind: str) -> Any:
    from aw_query.query2 import query

    with tempfile.TemporaryDirectory(prefix=f"aw-v2-{kind}-") as temporary:
        datastore = storage(kind, Path(temporary))
        try:
            populate_storage(datastore, fixture)
            result = query(
                f"flexible-rules-v2/{fixture['id']}/{kind}",
                query_text,
                parse_timestamp(fixture["interval"][0]),
                parse_timestamp(fixture["interval"][1]),
                datastore,
            )
            return jsonable(result)
        finally:
            close_storage(datastore)


def iso_z(value: str) -> str:
    parsed = parse_timestamp(value)
    text = parsed.isoformat(timespec="milliseconds")
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    return text


def normalize_number(value: Any) -> Any:
    if isinstance(value, timedelta):
        value = value.total_seconds()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    rounded = round(float(value), 9)
    return int(rounded) if rounded.is_integer() else rounded


def normalize_event(event: Dict[str, Any], *, active: bool) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {
        "timestamp": iso_z(event["timestamp"]),
        "duration": normalize_number(event.get("duration", 0)),
    }
    if not active:
        normalized["data"] = event.get("data", {})
    return normalized


def normalize_result(result: Any) -> Dict[str, Any]:
    browser = None
    browser_duration = None
    if isinstance(result, dict) and "events" in result and "active" in result:
        events, active = result["events"], result["active"]
        browser = result.get("browser")
        browser_duration = result.get("browser_duration")
    elif isinstance(result, list) and len(result) == 2:
        events, active = result
    else:
        raise ValueError(f"query result must be [events, active], got {result!r}")

    def ordered(values: Iterable[Dict[str, Any]], *, active: bool) -> list[Dict[str, Any]]:
        normalized = sorted(
            [normalize_event(value, active=active) for value in values],
            key=lambda value: (
                value["timestamp"],
                value["duration"],
                json.dumps(value.get("data", {}), ensure_ascii=False, sort_keys=True),
            ),
        )
        if not active:
            return normalized
        # Active output is a period mask. Different builders may intersect it
        # before or after enrichment and therefore segment the same union at
        # different fact boundaries; those segmentations are semantically equal.
        merged: list[Dict[str, Any]] = []
        for event in normalized:
            start = parse_timestamp(event["timestamp"])
            end = start.timestamp() + float(event["duration"])
            if merged:
                previous_start = parse_timestamp(merged[-1]["timestamp"])
                previous_end = previous_start.timestamp() + float(merged[-1]["duration"])
                if start.timestamp() <= previous_end:
                    merged[-1]["duration"] = normalize_number(
                        max(previous_end, end) - previous_start.timestamp()
                    )
                    continue
            merged.append(dict(event))
        return merged

    normalized_result = {
        "events": ordered(events, active=False),
        "active": ordered(active, active=True),
    }
    if browser is not None:
        # Browser compatibility assertions cover interval presence and totals;
        # URL parser metadata differs slightly between the two engines.
        normalized_result["browser"] = ordered(browser, active=True)
        normalized_result["browser_duration"] = normalize_number(browser_duration)
    return normalized_result


def restrict_result_to_interval(
    result: Dict[str, Any], interval: list[str]
) -> Dict[str, Any]:
    """Clip a normalized canonical stream for query-partition invariance checks."""
    interval_start = parse_timestamp(interval[0]).timestamp()
    interval_end = parse_timestamp(interval[1]).timestamp()
    clipped: Dict[str, Any] = {"events": [], "active": []}
    for key in ("events", "active", "browser"):
        if key not in result:
            continue
        clipped[key] = []
        for event in result[key]:
            event_start = parse_timestamp(event["timestamp"]).timestamp()
            event_end = event_start + float(event["duration"])
            start = max(event_start, interval_start)
            end = min(event_end, interval_end)
            if end <= start:
                continue
            value: Dict[str, Any] = {
                "timestamp": datetime.fromtimestamp(start, timezone.utc).isoformat(),
                "duration": end - start,
            }
            if key != "active":
                value["data"] = event.get("data", {})
            clipped[key].append(value)
    if "browser" in clipped:
        clipped["browser_duration"] = sum(event["duration"] for event in clipped["browser"])
    return normalize_result(clipped)


def query_map(document: Dict[str, Any]) -> Dict[str, Any]:
    return document["queries"]


def execute_python_matrix(
    corpus: Dict[str, Any], builders: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    output: Dict[str, Any] = {"schema_version": 1, "engine": "python", "results": {}}
    for fixture in corpus["fixtures"]:
        fixture_id = fixture["id"]
        output["results"][fixture_id] = {}
        for builder, queries in builders.items():
            output["results"][fixture_id][builder] = {}
            for storage_kind in ("memory", "peewee", "sqlite"):
                try:
                    query_value = queries[fixture_id]
                    if isinstance(query_value, dict) and "error" in query_value:
                        raise RuntimeError(f"builder error: {query_value['error']}")
                    if not isinstance(query_value, str):
                        raise RuntimeError("builder did not return Query2 text")
                    result = execute_python_query(query_value, fixture, storage_kind)
                    output["results"][fixture_id][builder][storage_kind] = {
                        "result": normalize_result(result)
                    }
                except Exception as error:
                    output["results"][fixture_id][builder][storage_kind] = {
                        "error": f"{type(error).__name__}: {error}"
                    }
    return output


def collect_results(document: Dict[str, Any]) -> Iterable[tuple[str, str, Any]]:
    engine = document["engine"]
    for fixture_id, builders in document["results"].items():
        for builder, stores in builders.items():
            for store, result in stores.items():
                label = f"{engine}/{store}/{builder}"
                yield fixture_id, label, result


def check(
    corpus: Dict[str, Any],
    result_documents: list[Dict[str, Any]],
    available_builders: Iterable[str],
) -> list[str]:
    failures: list[str] = []
    fixtures = {fixture["id"]: fixture for fixture in corpus["fixtures"]}
    expected = {
        fixture["id"]: normalize_result(fixture["expected"])
        for fixture in corpus["fixtures"]
    }
    observed: Dict[str, list[tuple[str, Dict[str, Any]]]] = {
        fixture_id: [] for fixture_id in expected
    }
    for document in result_documents:
        for fixture_id, label, wrapped in collect_results(document):
            builder = label.rsplit("/", 1)[-1]
            fixture = fixtures[fixture_id]
            if not supports_builder(fixture, builder):
                continue
            expects_error = builder in fixture.get("expected_builder_errors", [])
            if "error" in wrapped:
                if not expects_error:
                    failures.append(f"{fixture_id} [{label}] ERROR: {wrapped['error']}")
                continue
            if expects_error:
                failures.append(f"{fixture_id} [{label}] unexpectedly built and executed")
                continue
            actual = normalize_result(wrapped["result"])
            observed[fixture_id].append((label, actual))
            builder_expected = fixture.get("expected_by_builder", {}).get(
                builder, fixture["expected"]
            )
            normalized_expected = normalize_result(builder_expected)
            if actual != normalized_expected:
                failures.append(
                    f"{fixture_id} [{label}] != expected\n"
                    f"  expected: {json.dumps(normalized_expected, ensure_ascii=False, sort_keys=True)}\n"
                    f"  actual:   {json.dumps(actual, ensure_ascii=False, sort_keys=True)}"
                )
    for fixture_id, values in observed.items():
        if not values:
            fixture = fixtures[fixture_id]
            applicable = set(
                fixture.get("supported_builders", ["python", "typescript", "rust"])
            ).intersection(available_builders)
            if not applicable or applicable.issubset(
                set(fixture.get("expected_builder_errors", []))
            ):
                continue
            failures.append(f"{fixture_id}: no successful executions")
            continue
        baseline_label, baseline = values[0]
        intervals_only = fixtures[fixture_id].get("comparison") == "intervals_across_builders"
        for label, actual in values[1:]:
            left = baseline
            right = actual
            if intervals_only:
                left = {
                    key: (
                        [{k: v for k, v in event.items() if k != "data"} for event in value]
                        if isinstance(value, list)
                        else value
                    )
                    for key, value in baseline.items()
                }
                right = {
                    key: (
                        [{k: v for k, v in event.items() if k != "data"} for event in value]
                        if isinstance(value, list)
                        else value
                    )
                    for key, value in actual.items()
                }
            if right != left:
                failures.append(
                    f"{fixture_id}: semantic disagreement {baseline_label} != {label}"
                )

    # A canonical query must be local: executing a narrow partition must equal
    # clipping the corresponding wide execution, for every builder/backend cell.
    observed_by_label = {
        fixture_id: dict(values) for fixture_id, values in observed.items()
    }
    for fixture_id, fixture in fixtures.items():
        wide_id = fixture.get("partition_of")
        if not wide_id:
            continue
        for label, narrow in observed_by_label[fixture_id].items():
            wide = observed_by_label.get(wide_id, {}).get(label)
            if wide is None:
                failures.append(
                    f"{fixture_id} [{label}]: missing wide partition result {wide_id}"
                )
                continue
            restricted = restrict_result_to_interval(wide, fixture["interval"])
            if narrow != restricted:
                failures.append(
                    f"{fixture_id} [{label}] is not the restriction of {wide_id}\n"
                    f"  restricted wide: {json.dumps(restricted, ensure_ascii=False, sort_keys=True)}\n"
                    f"  narrow:          {json.dumps(narrow, ensure_ascii=False, sort_keys=True)}"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=HERE / "fixtures.json")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument(
        "--python-only", action="store_true", help="run only the Python builder/engines"
    )
    parser.add_argument(
        "--skip-rust",
        action="store_true",
        help="run Python and TypeScript builders on Python engines",
    )
    parser.add_argument("--keep-work-dir", action="store_true")
    args = parser.parse_args()

    corpus = load_json(args.fixtures.resolve())
    if corpus.get("schema_version") != 1:
        raise SystemExit("unsupported fixture schema")

    temporary = None
    if args.work_dir:
        work = args.work_dir.resolve()
        work.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.mkdtemp(prefix="aw-flexible-rules-v2-")
        work = Path(temporary)

    try:
        python_document = generate_python(corpus)
        python_path = work / "python-queries.json"
        write_json(python_path, python_document)
        builders = {"python": query_map(python_document)}

        result_documents: list[Dict[str, Any]] = []
        if not args.python_only:
            ts_path = work / "typescript-queries.json"
            run(
                [
                    os.environ.get("NODE", "node"),
                    str(HERE / "typescript_driver.cjs"),
                    str(args.fixtures.resolve()),
                    str(ts_path),
                ]
            )
            ts_document = load_json(ts_path)
            builders["typescript"] = query_map(ts_document)

        if not args.python_only and not args.skip_rust:
            rust_path = work / "rust-queries.json"
            cargo = os.environ.get("CARGO", "cargo")
            run(
                [
                    cargo,
                    "run",
                    "--quiet",
                    "-p",
                    "aw-client-rust",
                    "--example",
                    "flexible_conformance",
                    "--",
                    "generate",
                    str(args.fixtures.resolve()),
                    str(rust_path),
                ],
                cwd=REPO / "aw-server-rust",
            )
            rust_document = load_json(rust_path)
            builders["rust"] = query_map(rust_document)

        combined_path = work / "queries.json"
        executable_builders = {
            builder: {
                fixture_id: query
                for fixture_id, query in queries.items()
                if isinstance(query, str)
            }
            for builder, queries in builders.items()
        }
        write_json(
            combined_path, {"schema_version": 1, "queries": executable_builders}
        )

        python_results = execute_python_matrix(corpus, builders)
        python_results_path = work / "python-results.json"
        write_json(python_results_path, python_results)
        result_documents.append(python_results)

        if not args.python_only and not args.skip_rust:
            rust_results_path = work / "rust-results.json"
            run(
                [
                    os.environ.get("CARGO", "cargo"),
                    "run",
                    "--quiet",
                    "-p",
                    "aw-client-rust",
                    "--example",
                    "flexible_conformance",
                    "--",
                    "execute",
                    str(args.fixtures.resolve()),
                    str(combined_path),
                    str(rust_results_path),
                ],
                cwd=REPO / "aw-server-rust",
            )
            result_documents.append(load_json(rust_results_path))

        failures = check(corpus, result_documents, builders)
        if failures:
            print(f"\nFAILED: {len(failures)} conformance mismatch(es)", file=sys.stderr)
            for failure in failures:
                print(f"\n- {failure}", file=sys.stderr)
            print(f"\nArtifacts: {work}", file=sys.stderr)
            if temporary:
                temporary = None  # retain failure artifacts
            return 1

        fixtures_by_id = {fixture["id"]: fixture for fixture in corpus["fixtures"]}
        executions = sum(
            1
            for document in result_documents
            for fixture_id, label, wrapped in collect_results(document)
            if supports_builder(fixtures_by_id[fixture_id], label.rsplit("/", 1)[-1])
            and "result" in wrapped
        )
        expected_builder_errors = sum(
            1
            for fixture in corpus["fixtures"]
            for builder in fixture.get("expected_builder_errors", [])
            if builder in builders
        )
        error_summary = (
            f", {expected_builder_errors} expected builder errors"
            if expected_builder_errors
            else ""
        )
        print(
            f"PASS: {len(corpus['fixtures'])} fixtures, {len(builders)} builders, "
            f"{executions} semantic executions{error_summary}"
        )
        if args.keep_work_dir:
            print(f"Artifacts: {work}")
            temporary = None
        return 0
    finally:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
