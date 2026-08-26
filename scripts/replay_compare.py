"""
Chunk 40 -- compares what two git refs' code would recommend for the SAME
frozen trajectory + pinned data snapshot + seed.

Mechanism: for each ref, `git worktree add --detach <tmp_dir> <ref>` checks
out that commit's own copy of the `app` package into a throwaway directory,
then scripts/replay_run.py -- ALWAYS invoked from THIS repo's own path, via
subprocess, never copied into the worktree -- is run with
REPLAY_APP_ROOT=<tmp_dir>, so `import app...` inside that subprocess
resolves to the OLD commit's code while replay_cli.py/replay_lib.py
themselves (this chunk's own harness logic, which doesn't exist in old
commits at all) still come from the current repo. See replay_cli.py's own
module docstring for the sys.path mechanics this depends on. Each
subprocess is a fresh Python process, so there's no cross-ref module-
caching risk (`app.services.mcts` for ref A can never leak into ref B's
process).

Worktrees are added --detach (no branch checkout, avoids "already checked
out on branch main" conflicts) and always removed (--force, so a
still-open file handle from a just-exited subprocess can't strand one)
in a `finally` block, even on failure.

Usage:
  python scripts/replay_compare.py --trajectory PATH --snapshot PATH \
      --ref-a <git-ref> --ref-b <git-ref> [--seed N] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REPLAY_RUN_SCRIPT = REPO_ROOT / "scripts" / "replay_cli.py"


def _run_ref(ref: str, trajectory: str, snapshot: str, seed: int, out_path: Path) -> dict[str, Any]:
    worktree_dir = Path(tempfile.mkdtemp(prefix="replay_worktree_"))
    # mkdtemp already created the directory; `git worktree add` refuses a
    # non-empty target, and refuses an EXISTING empty one too on some git
    # versions -- remove it first and let worktree add recreate it.
    worktree_dir.rmdir()
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree_dir), ref],
            check=True, cwd=REPO_ROOT, capture_output=True, text=True,
        )
        env = {"REPLAY_APP_ROOT": str(worktree_dir)}
        import os
        full_env = os.environ.copy()
        full_env.update(env)
        proc = subprocess.run(
            [sys.executable, str(REPLAY_RUN_SCRIPT), "run",
             "--trajectory", trajectory, "--snapshot", snapshot, "--seed", str(seed), "--out", str(out_path)],
            check=True, cwd=REPO_ROOT, env=full_env, capture_output=True, text=True,
        )
        print(f"--- ref {ref} (worktree {worktree_dir}) ---\n{proc.stdout}")
        with open(out_path, encoding="utf-8") as f:
            return json.load(f)
    except subprocess.CalledProcessError as exc:
        print(f"--- ref {ref} FAILED ---\nSTDOUT:\n{exc.stdout}\nSTDERR:\n{exc.stderr}", file=sys.stderr)
        raise
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_dir)],
            check=False, cwd=REPO_ROOT, capture_output=True, text=True,
        )
        shutil.rmtree(worktree_dir, ignore_errors=True)


def _top_recommendation(result: dict[str, Any]) -> dict[str, Any]:
    recs = result["recommend_result"]["recommendations"]
    return recs[0] if recs else {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk 40: compare two git refs' recommend() output on one frozen decision.")
    parser.add_argument("--trajectory", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--ref-a", required=True)
    parser.add_argument("--ref-b", required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", default=None, help="Write the full {ref_a, ref_b} result pair as JSON here.")
    args = parser.parse_args()

    trajectory = str(Path(args.trajectory).resolve())
    snapshot = str(Path(args.snapshot).resolve())

    with tempfile.TemporaryDirectory() as tmp:
        out_a = Path(tmp) / "result_a.json"
        out_b = Path(tmp) / "result_b.json"
        result_a = _run_ref(args.ref_a, trajectory, snapshot, args.seed, out_a)
        result_b = _run_ref(args.ref_b, trajectory, snapshot, args.seed, out_b)

    top_a = _top_recommendation(result_a)
    top_b = _top_recommendation(result_b)

    print("\n=== COMPARISON ===")
    print(f"ref_a={args.ref_a}: top pick = {top_a.get('name')} ({top_a.get('position')}), "
          f"mcts_score={top_a.get('mcts_score')} +/- {top_a.get('mcts_score_stderr')}, "
          f"would_start_now={top_a.get('would_start_now')}, "
          f"adaptive_resolution_applied={result_a['recommend_result']['adaptive_resolution_applied']}, "
          f"adp_tie_break_applied={result_a['recommend_result']['adp_tie_break_applied']}")
    print(f"ref_b={args.ref_b}: top pick = {top_b.get('name')} ({top_b.get('position')}), "
          f"mcts_score={top_b.get('mcts_score')} +/- {top_b.get('mcts_score_stderr')}, "
          f"would_start_now={top_b.get('would_start_now')}, "
          f"adaptive_resolution_applied={result_b['recommend_result']['adaptive_resolution_applied']}, "
          f"adp_tie_break_applied={result_b['recommend_result']['adp_tie_break_applied']}")
    print(f"SAME top pick: {top_a.get('player_id') == top_b.get('player_id')}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"ref_a": args.ref_a, "ref_b": args.ref_b, "result_a": result_a, "result_b": result_b}, f, indent=2, sort_keys=True)
        print(f"\nFull comparison written: {args.out}")


if __name__ == "__main__":
    main()
