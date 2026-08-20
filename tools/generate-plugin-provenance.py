#!/usr/bin/env python3
"""Generate or verify a plugin's embedded runtime provenance record."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    ROOT
    / "plugins"
    / "multi-agent-role-work"
    / "skills"
    / "sdlc-orchestrator"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))
try:
    import runtime_provenance as provenance
finally:
    sys.path.pop(0)


def _serialized(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin_root", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path; defaults to <plugin>/.codex-plugin/provenance.json",
    )
    parser.add_argument(
        "--entry",
        default=provenance.DEFAULT_ENTRY_PATH.as_posix(),
        help="Plugin-relative runtime entry used for the entry digest",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that the existing record is current without writing it",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the complete generated record instead of a compact result",
    )
    return parser


def _output_path(plugin_root: Path, output: Path | None) -> Path:
    if output is None:
        return (plugin_root / provenance.PROVENANCE_PATH).resolve()
    if output.is_absolute():
        return output.expanduser().resolve()
    return (plugin_root / output).resolve()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plugin_root = args.plugin_root.expanduser().resolve()
    output = _output_path(plugin_root, args.output)
    try:
        expected = provenance.build_embedded_provenance(
            plugin_root,
            entry_path=args.entry,
        )
        expected_bytes = _serialized(expected)
        if args.check:
            try:
                actual_bytes = output.read_bytes()
            except OSError:
                print(f"OUTDATED {output}: provenance record is missing", file=sys.stderr)
                return 1
            if actual_bytes != expected_bytes:
                print(f"OUTDATED {output}: payload identity changed", file=sys.stderr)
                return 1
        else:
            expected = provenance.write_embedded_provenance(
                plugin_root,
                output_path=output,
                entry_path=args.entry,
            )
            expected_bytes = _serialized(expected)
        if args.stdout:
            sys.stdout.buffer.write(expected_bytes)
        else:
            action = "CURRENT" if args.check else "WROTE"
            print(
                f"{action} {output} "
                f"version={expected['version']} payload={expected['payload_sha256']}"
            )
        return 0
    except provenance.ProvenanceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
