#!/usr/bin/env python3
"""Synchronize external Rust consumers with the aw-server-rust gitlink."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

UPSTREAM = "https://github.com/ActivityWatch/aw-server-rust"
PLACEHOLDER = "0" * 40
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
PIN_RE = re.compile(
    r'(?P<prefix>git = "https://github\.com/ActivityWatch/aw-server-rust", rev = ")'
    r"[0-9a-f]{40}"
    r'(?P<suffix>")'
)


@dataclass(frozen=True)
class Consumer:
    manifest: Path
    lockfile: Path
    direct_packages: tuple[str, ...]
    lock_packages: tuple[str, ...]
    update_package: str


RUST_PACKAGES = (
    "aw-client-rust",
    "aw-datastore",
    "aw-models",
    "aw-query",
    "aw-server",
    "aw-transform",
)
ROOT = Path(__file__).resolve().parents[2]
CONSUMERS = (
    Consumer(
        ROOT / "aw-notify" / "Cargo.toml",
        ROOT / "aw-notify" / "Cargo.lock",
        ("aw-client-rust", "aw-models"),
        ("aw-client-rust", "aw-models"),
        "aw-client-rust",
    ),
    Consumer(
        ROOT / "aw-tauri" / "src-tauri" / "Cargo.toml",
        ROOT / "aw-tauri" / "src-tauri" / "Cargo.lock",
        ("aw-server", "aw-datastore"),
        RUST_PACKAGES,
        "aw-server",
    ),
    Consumer(
        ROOT / "aw-tauri" / "scripts" / "server-api-contract" / "Cargo.toml",
        ROOT / "aw-tauri" / "scripts" / "server-api-contract" / "Cargo.lock",
        ("aw-server", "aw-datastore"),
        RUST_PACKAGES,
        "aw-server",
    ),
)


def checkout_revision() -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT / "aw-server-rust"), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def manifest_errors(consumer: Consumer, expected: str) -> list[str]:
    source = consumer.manifest.read_text(encoding="utf-8")
    errors: list[str] = []
    for package in consumer.direct_packages:
        match = re.search(
            rf"^{re.escape(package)}\s*=\s*\{{(?P<value>[^\n]+)\}}$",
            source,
            re.MULTILINE,
        )
        if match is None:
            errors.append(f"{consumer.manifest}: missing detailed dependency {package}")
            continue
        value = match.group("value")
        if f'git = "{UPSTREAM}"' not in value:
            errors.append(f"{consumer.manifest}: {package} must use {UPSTREAM}")
        revision = re.search(r'rev\s*=\s*"([0-9a-f]{40})"', value)
        actual = revision.group(1) if revision else None
        if actual != expected:
            errors.append(f"{consumer.manifest}: {package} pins {actual!r}, expected {expected}")
        if re.search(r"\b(path|branch|tag)\s*=", value):
            errors.append(f"{consumer.manifest}: {package} must use only an exact git revision")
    return errors


def lockfile_errors(consumer: Consumer, expected: str) -> list[str]:
    source = consumer.lockfile.read_text(encoding="utf-8")
    blocks = source.split("[[package]]")
    by_name: dict[str, str] = {}
    for block in blocks:
        name = re.search(r'^name = "([^"]+)"$', block, re.MULTILINE)
        if name and name.group(1) in consumer.lock_packages:
            by_name[name.group(1)] = block

    errors: list[str] = []
    for name in consumer.lock_packages:
        block = by_name.get(name)
        if block is None:
            errors.append(f"{consumer.lockfile}: missing {name}")
            continue
        source_match = re.search(r'^source = "([^"]+)"$', block, re.MULTILINE)
        resolved = source_match.group(1) if source_match else None
        if resolved is None or not resolved.startswith(f"git+{UPSTREAM}"):
            errors.append(f"{consumer.lockfile}: {name} is not resolved from {UPSTREAM}")
        elif not resolved.endswith(f"#{expected}"):
            errors.append(
                f"{consumer.lockfile}: {name} resolves to {resolved.rsplit('#', 1)[-1]}, "
                f"expected {expected}"
            )
    return errors


def verify(expected: str) -> None:
    errors: list[str] = []
    for consumer in CONSUMERS:
        errors.extend(manifest_errors(consumer, expected))
        errors.extend(lockfile_errors(consumer, expected))
    if errors:
        raise ValueError("\n  ".join(errors))


def update_manifest(consumer: Consumer, revision: str) -> None:
    source = consumer.manifest.read_text(encoding="utf-8")
    updated, count = PIN_RE.subn(rf"\g<prefix>{revision}\g<suffix>", source)
    if count != len(consumer.direct_packages):
        raise ValueError(
            f"{consumer.manifest}: expected {len(consumer.direct_packages)} pins, found {count}"
        )
    consumer.manifest.write_text(updated, encoding="utf-8")


def pin_lockfile_sources(consumer: Consumer, revision: str) -> None:
    source = consumer.lockfile.read_text(encoding="utf-8")
    blocks = source.split("[[package]]")
    found: set[str] = set()
    locked_source = f"git+{UPSTREAM}?rev={revision}#{revision}"
    for index, block in enumerate(blocks):
        name_match = re.search(r'^name = "([^"]+)"$', block, re.MULTILINE)
        if name_match is None or name_match.group(1) not in consumer.lock_packages:
            continue
        name = name_match.group(1)
        found.add(name)
        if re.search(r'^source = "[^"]+"$', block, re.MULTILINE):
            block = re.sub(
                r'^source = "[^"]+"$',
                f'source = "{locked_source}"',
                block,
                flags=re.MULTILINE,
            )
        else:
            block, count = re.subn(
                r'^(version = "[^"]+")$',
                rf'\1\nsource = "{locked_source}"',
                block,
                count=1,
                flags=re.MULTILINE,
            )
            if count != 1:
                raise ValueError(f"{consumer.lockfile}: {name} has no version field")
        blocks[index] = block

    missing = sorted(set(consumer.lock_packages) - found)
    if missing:
        raise ValueError(f"{consumer.lockfile}: missing packages: {', '.join(missing)}")
    consumer.lockfile.write_text("[[package]]".join(blocks), encoding="utf-8")


def refresh_lockfile(consumer: Consumer, revision: str) -> None:
    subprocess.run(
        [
            os.environ.get("CARGO", "cargo"),
            "update",
            "--manifest-path",
            str(consumer.manifest),
            "--package",
            consumer.update_package,
            "--precise",
            revision,
        ],
        cwd=consumer.manifest.parent,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="pin aw-notify and aw-tauri to the bundle's aw-server-rust revision"
    )
    parser.add_argument("revision", nargs="?", help="full aw-server-rust commit SHA")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify manifests and lockfiles against the checked-out gitlink target",
    )
    args = parser.parse_args()

    try:
        checked_out = checkout_revision()
        if not REVISION_RE.fullmatch(checked_out):
            raise ValueError(f"aw-server-rust checkout is not a full commit: {checked_out}")

        if args.check:
            if args.revision is not None:
                parser.error("revision cannot be used with --check")
            verify(checked_out)
            print(f"OK: Rust consumers and lockfiles pin aw-server-rust {checked_out}")
            return 0

        if args.revision is None:
            parser.error("revision is required unless --check is used")
        revision = args.revision.lower()
        if not REVISION_RE.fullmatch(revision) or revision == PLACEHOLDER:
            parser.error("revision must be a nonzero, lowercase 40-character commit SHA")
        if revision != checked_out:
            raise ValueError(
                f"requested revision {revision} does not match "
                f"aw-server-rust checkout {checked_out}"
            )

        for consumer in CONSUMERS:
            update_manifest(consumer, revision)
            pin_lockfile_sources(consumer, revision)
        for consumer in CONSUMERS:
            refresh_lockfile(consumer, revision)
        verify(revision)
        print(f"Updated Rust consumer pins and lockfiles to aw-server-rust {revision}")
        return 0
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
