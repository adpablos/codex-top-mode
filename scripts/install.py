"""Make Top Mode available to Codex and Claude Code as a skill.

Links this package into each agent's personal skills folder (honoring
CODEX_HOME and CLAUDE_CONFIG_DIR). Agents that are not installed are skipped;
anything already at the destination that is not this package is left untouched.
"""

import argparse
import os
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
AGENTS = {"Codex": ("CODEX_HOME", ".codex"), "Claude Code": ("CLAUDE_CONFIG_DIR", ".claude")}
NAME = "top-mode"


def targets(home, env):
    return {
        agent: Path(env.get(variable) or home / folder).expanduser() / "skills" / NAME
        for agent, (variable, folder) in AGENTS.items()
    }


def ours(path):
    return path.is_symlink() and path.resolve() == PACKAGE


def install(home, env):
    results = {}
    for agent, target in targets(home, env).items():
        if not target.parent.parent.is_dir():
            results[agent] = "skipped: agent not found"
        elif ours(target):
            results[agent] = f"already installed at {target}"
        elif target.exists() or target.is_symlink():
            results[agent] = f"not changed: {target} already exists and is not this package"
        else:
            try:
                target.parent.mkdir(exist_ok=True)
                target.symlink_to(PACKAGE, target_is_directory=True)
            except OSError as error:
                results[agent] = f"failed: {error.strerror or error}"
            else:
                results[agent] = f"installed at {target}"
    return results


def remove(home, env):
    results = {}
    for agent, target in targets(home, env).items():
        if ours(target):
            target.unlink()
            results[agent] = f"removed {target}"
        else:
            results[agent] = "nothing to remove"
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true", help="Remove the links again")
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    args = parser.parse_args()
    action = remove if args.remove else install
    results = action(args.home, os.environ)
    for agent, result in results.items():
        print(f"{agent}: {result}")
    if not args.remove and any(r.startswith("installed") for r in results.values()):
        print("Start a new agent session and ask: 'Help me set up Top Mode.'")
    if any(r.startswith("failed") for r in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
