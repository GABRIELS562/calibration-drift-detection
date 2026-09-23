"""Command line for the approval gate.

    uv run python -m drift.cli status
    uv run python -m drift.cli approve 3 --actor analyst@lab --reason "sensors replaced"
    uv run python -m drift.cli reject  4 --actor analyst@lab --reason "regression on acetaldehyde"
    uv run python -m drift.cli rollback --actor analyst@lab --reason "v4 misbehaving"

``--actor`` defaults to ``$DRIFT_ACTOR`` (set by the CI approval job to the
GitHub user who approved the deployment), but never to an anonymous value.
"""

import argparse
import os
import sys
from typing import Final

import mlflow

from drift.registry import (
    ApprovalError,
    approve,
    audit_trail,
    production_version,
    reject,
    rollback,
)
from drift.train import DEFAULT_TRACKING_URI

_STATUS_WIDTH: Final = 16


def _set_tracking_uri() -> None:
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))


def _print_status() -> None:
    current = production_version()
    print(f"production: {'version ' + current if current else 'nothing promoted'}\n")
    header = f"{'ver':>4}  {'status':<{_STATUS_WIDTH}}  {'actor':<18}  trigger / reason"
    print(header)
    print("-" * len(header))
    for entry in audit_trail():
        status = entry.get("approval_status", "?")
        actor = (
            entry.get("approved_by")
            or entry.get("rejected_by")
            or entry.get("rolled_back_by")
            or "—"
        )
        detail = (
            entry.get("approval_reason")
            or entry.get("rejection_reason")
            or entry.get("trigger", "")
        )
        marker = " *" if entry["version"] == current else "  "
        print(f"{entry['version']:>4}{marker}{status:<{_STATUS_WIDTH}}  {actor:<18}  {detail[:60]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="drift.cli",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show the registry and who approved what")
    actions = (
        ("approve", "promote a pending candidate"),
        ("reject", "record a rejected candidate"),
    )
    for name, help_text in actions:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("version")
        p.add_argument("--actor", default=os.environ.get("DRIFT_ACTOR", ""))
        p.add_argument("--reason", required=True)
    p = sub.add_parser("rollback", help="restore the previous approved version")
    p.add_argument("--actor", default=os.environ.get("DRIFT_ACTOR", ""))
    p.add_argument("--reason", required=True)

    args = parser.parse_args(argv)
    _set_tracking_uri()
    try:
        if args.command == "status":
            _print_status()
        elif args.command == "approve":
            version = approve(args.version, actor=args.actor, reason=args.reason)
            print(f"approved version {version} -> production (by {args.actor})")
        elif args.command == "reject":
            version = reject(args.version, actor=args.actor, reason=args.reason)
            print(f"rejected version {version} (by {args.actor})")
        elif args.command == "rollback":
            restored = rollback(actor=args.actor, reason=args.reason)
            print(f"rolled back: production -> version {restored} (by {args.actor})")
    except ApprovalError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
