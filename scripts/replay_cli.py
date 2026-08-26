"""
Chunk 40 -- CLI for the fixed-trajectory replay harness (replay_lib/).

SYS.PATH MECHANICS (read this before touching the imports below): this
script is what actually gets invoked, once per git ref under test, by
scripts/replay_compare.py -- each invocation is its OWN fresh subprocess (no
shared/cached module state between refs, so there's no risk of one ref's
`app.services.mcts` staying cached in `sys.modules` and leaking into the
other's run). Which commit's `app` package this process imports is selected
entirely by the REPLAY_APP_ROOT env var, set by the caller:

  - REPLAY_APP_ROOT unset -> `app` resolves to THIS repo's checked-out code
    (i.e. current HEAD + working tree, whatever that is at invocation time).
  - REPLAY_APP_ROOT=<path> -> `app` resolves to a `git worktree add`
    checkout of some other commit at that path instead.

Either way, `replay_lib` (this harness's own reusable logic, not the code
under test) must ALWAYS resolve to the current repo's copy -- an old
worktree has no replay_lib/ at all (it didn't exist before Chunk 40) -- so
this repo's own root is ALSO always on sys.path, inserted AFTER
REPLAY_APP_ROOT so `app.*` still resolves to the worktree first when one is
set. See replay_lib/harness.py's module docstring for the fuller reasoning.
This path setup MUST happen before any `app.*` or `replay_lib.*` import
below -- that's why it's at the very top of the file, ahead of those
imports, rather than the usual top-of-file import block.

Usage:
  python scripts/replay_cli.py snapshot --name NAME [--force-refresh]
  python scripts/replay_cli.py freeze-fixture --fixture PATH --pick-no N --my-slot N --name NAME [--num-teams N] [--source TEXT]
  python scripts/replay_cli.py freeze-mock --seed N --my-slot N --pick-no N --name NAME --snapshot PATH [--strategy draft_score|vbd_only|adp_only] [--mcts-iterations N]
  python scripts/replay_cli.py run --trajectory PATH --snapshot PATH [--seed N] [--out PATH]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_APP_ROOT = os.environ.get("REPLAY_APP_ROOT", str(_REPO_ROOT))
sys.path.insert(0, _APP_ROOT)
if str(_REPO_ROOT) != _APP_ROOT:
    sys.path.insert(1, str(_REPO_ROOT))

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402

from replay_lib import harness  # noqa: E402  -- ALWAYS from _REPO_ROOT, see module docstring


def _cmd_snapshot(args: argparse.Namespace) -> None:
    path = asyncio.run(harness.capture_data_snapshot(args.name, force_refresh=args.force_refresh))
    print(f"Snapshot written: {path}")


def _cmd_freeze_fixture(args: argparse.Namespace) -> None:
    with open(args.fixture, encoding="utf-8") as f:
        all_picks = json.load(f)
    path = harness.freeze_trajectory(
        all_picks,
        pick_no=args.pick_no,
        my_slot=args.my_slot,
        name=args.name,
        num_teams=args.num_teams,
        source=args.source or f"freeze-fixture:{args.fixture}",
    )
    print(f"Trajectory written: {path}")


def _cmd_freeze_mock(args: argparse.Namespace) -> None:
    # Imported here, not at module top, so `snapshot`/`freeze-fixture`/`run`
    # never pay for importing mock_draft.py's mcts/opponent_model transitive
    # deps unless this specific subcommand is actually used.
    from app.services import mock_draft

    players_by_id = harness.load_players_by_id(args.snapshot)
    result = mock_draft.run_mock_draft(
        my_slot=args.my_slot,
        strategy=args.strategy,
        opponent_seed=args.seed,
        players_by_id=players_by_id,
        mcts_iterations=args.mcts_iterations,
    )
    path = harness.freeze_trajectory(
        result["all_picks"],
        pick_no=args.pick_no,
        my_slot=args.my_slot,
        name=args.name,
        source=(
            f"freeze-mock:strategy={args.strategy},opponent_seed={args.seed},"
            f"snapshot={args.snapshot},mcts_iterations={args.mcts_iterations}"
        ),
    )
    print(f"Trajectory written: {path} (from a fresh {args.strategy} mock draft, seed={args.seed})")


def _cmd_run(args: argparse.Namespace) -> None:
    result = harness.replay_decision(args.trajectory, args.snapshot, seed=args.seed)
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"Result written: {args.out}")
    else:
        print(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk 40 fixed-trajectory replay harness CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_snap = sub.add_parser("snapshot", help="Capture a named, immutable data snapshot.")
    p_snap.add_argument("--name", required=True)
    p_snap.add_argument("--force-refresh", action="store_true")
    p_snap.set_defaults(func=_cmd_snapshot)

    p_ff = sub.add_parser("freeze-fixture", help="Freeze a trajectory from an existing pick-log JSON file.")
    p_ff.add_argument("--fixture", required=True)
    p_ff.add_argument("--pick-no", type=int, required=True)
    p_ff.add_argument("--my-slot", type=int, required=True)
    p_ff.add_argument("--name", required=True)
    p_ff.add_argument("--num-teams", type=int, default=10)
    p_ff.add_argument("--source", default="")
    p_ff.set_defaults(func=_cmd_freeze_fixture)

    p_fm = sub.add_parser("freeze-mock", help="Run a fresh synthetic mock draft and freeze a trajectory from it.")
    p_fm.add_argument("--seed", type=int, required=True)
    p_fm.add_argument("--my-slot", type=int, required=True)
    p_fm.add_argument("--pick-no", type=int, required=True)
    p_fm.add_argument("--name", required=True)
    p_fm.add_argument("--snapshot", required=True)
    p_fm.add_argument("--strategy", default="draft_score", choices=["draft_score", "vbd_only", "adp_only"])
    p_fm.add_argument("--mcts-iterations", type=int, default=150)
    p_fm.set_defaults(func=_cmd_freeze_mock)

    p_run = sub.add_parser("run", help="Replay one decision under the currently-importable code version.")
    p_run.add_argument("--trajectory", required=True)
    p_run.add_argument("--snapshot", required=True)
    p_run.add_argument("--seed", type=int, default=1)
    p_run.add_argument("--out", default=None)
    p_run.set_defaults(func=_cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
