"""Make Quota Coach available to Codex and Claude Code as a skill.

Links this package into each agent's personal skills folder (honoring
CODEX_HOME and CLAUDE_CONFIG_DIR). Agents that are not installed are skipped;
anything already at the destination that is not this package is left untouched,
except a broken link left by a moved Quota Coach folder, which is replaced. Such
a link, or one to this package, under the skill's former name is removed, so the
skill is not listed twice.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
AGENTS = {"Codex": ("CODEX_HOME", ".codex"), "Claude Code": ("CLAUDE_CONFIG_DIR", ".claude")}
CHOICES = {"codex": "Codex", "claude": "Claude Code"}
NAME = "quota-coach"
FORMER = "top-mode"


def git(folder, *args):
    return subprocess.run(
        ["git", "-C", str(folder), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.strip()


def revision(folder):
    """Identify this checkout, never a parent repository or a claimed package version."""
    if not (folder / ".git").exists():
        return "unknown (no Git checkout)"
    try:
        commit = git(folder, "rev-parse", "HEAD")
        branch = git(folder, "branch", "--show-current") or "detached"
        tags = git(folder, "tag", "--points-at", "HEAD")
        dirty = "; local changes" if git(folder, "status", "--porcelain") else ""
        return f"{commit} ({branch}; {tags or 'untagged'}{dirty})"
    except (OSError, subprocess.SubprocessError):
        return "unknown (Git unavailable or unreadable checkout)"


def check(home, env, agents=None):
    """Read link metadata only; do not load profiles, accounts, or quota sources."""
    print(f"Package: {PACKAGE}\nRevision: {revision(PACKAGE)}")
    ready = 0
    problems = False
    for agent, target in targets(home, env, agents=agents).items():
        former = target.with_name(FORMER)
        if not target.parent.parent.is_dir():
            print(f"{agent}: agent not found")
            problems |= agents is not None
            continue
        if ours(target) and (target / "SKILL.md").is_file():
            print(f"{agent}: ready for a new session — {target} -> {PACKAGE}")
            ready += 1
        else:
            problems = True
            if target.is_symlink():
                folder = target.resolve()
                state = "different copy" if folder.exists() else "broken link"
                print(f"{agent}: {state} — {target} -> {folder}\n  Revision: {revision(folder)}")
            elif target.exists():
                print(f"{agent}: occupied by another file or folder — {target}")
            else:
                print(f"{agent}: skill not installed — {target}")
        if former.exists() or former.is_symlink():
            problems = True
            folder = former.resolve()
            print(
                f"{agent}: former skill present — {former} -> {folder}\n"
                f"  Revision: {revision(folder)}"
            )
    print("Already-open sessions may still have older instructions; open a new session.")
    return bool(ready) and not problems


def update():
    """Fast-forward an identified, clean main checkout; keep all other branches intact."""
    if not (PACKAGE / ".git").exists():
        raise ValueError("Update requires a Git checkout.")
    origin = git(PACKAGE, "remote", "get-url", "origin").removesuffix("/").removesuffix(".git")
    names = ("quota-coach", "top-mode", "codex-top-mode")
    allowed = {
        f"{prefix}{name}"
        for prefix in (
            "https://github.com/adpablos/",
            "git@github.com:adpablos/",
        )
        for name in names
    }
    if origin not in allowed:
        raise ValueError("Origin is not the Quota Coach repository; nothing was updated.")
    if git(PACKAGE, "branch", "--show-current") != "main":
        raise ValueError("Update requires main. Keep development in a separate checkout.")
    if git(PACKAGE, "status", "--porcelain"):
        raise ValueError("Local changes found; preserve them before updating.")
    git(PACKAGE, "fetch", "origin", "refs/heads/main")
    if git(PACKAGE, "rev-list", "FETCH_HEAD..HEAD"):
        raise ValueError("Local commits found; preserve them before updating.")
    git(PACKAGE, "merge", "--ff-only", "FETCH_HEAD")


def targets(home, env, name=NAME, agents=None):
    return {
        agent: Path(env.get(variable) or home / folder).expanduser() / "skills" / name
        for agent, (variable, folder) in AGENTS.items()
        if agents is None or agent in agents
    }


def ours(path):
    return path.is_symlink() and path.resolve() == PACKAGE


def broken(path):
    """A link to a missing Quota Coach (or Top Mode) folder, as a move leaves."""
    return (
        path.is_symlink()
        and not path.exists()
        and Path(os.readlink(path)).name.lstrip(".") in {NAME, FORMER, "codex-" + FORMER}
    )


def install(home, env, agents=None):
    results = {}
    former = targets(home, env, FORMER)
    for agent, target in targets(home, env, agents=agents).items():
        replaced = ""
        if broken(target):
            target.unlink()
            replaced = "; replaced a broken link"
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
                results[agent] = f"installed at {target}" + replaced
        if ours(target) and (ours(former[agent]) or broken(former[agent])):
            former[agent].unlink()
            results[agent] += f"; removed the old link {former[agent]}"
    return results


def remove(home, env, agents=None):
    results = {}
    former = targets(home, env, FORMER)
    for agent, target in targets(home, env, agents=agents).items():
        removed = [link for link in (target, former[agent]) if ours(link) or broken(link)]
        for link in removed:
            link.unlink()
        names = ", ".join(str(link) for link in removed)
        results[agent] = f"removed {names}" if removed else "nothing to remove"
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--remove", action="store_true", help="Remove the links again")
    modes.add_argument(
        "--check", action="store_true", help="Show the copy each agent loads; read only"
    )
    modes.add_argument(
        "--update", action="store_true", help="Fast-forward a clean main and reinstall"
    )
    parser.add_argument(
        "--agent", choices=CHOICES, action="append", help="Only this agent (default: both)"
    )
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    args = parser.parse_args()
    agents = args.agent and {CHOICES[choice] for choice in args.agent}
    if args.check:
        sys.exit(0 if check(args.home, os.environ, agents) else 1)
    if args.update:
        try:
            update()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            # A Git error may contain a credential-bearing remote URL; keep it out of output.
            detail = (
                str(error)
                if isinstance(error, ValueError)
                else "Git update failed; inspect locally."
            )
            parser.error(detail)
        # Run the updated installer, not the old code already loaded in this process.
        argv = [sys.executable, "-B", str(PACKAGE / "scripts/install.py"), "--home", str(args.home)]
        for agent in args.agent or []:
            argv += ["--agent", agent]
        sys.exit(subprocess.call(argv))
    action = remove if args.remove else install
    results = action(args.home, os.environ, agents)
    for agent, result in results.items():
        print(f"{agent}: {result}")
    if not args.remove and any(r.startswith("installed") for r in results.values()):
        print("Start a new agent session and ask: 'Help me set up Quota Coach.'")
    if not args.remove and not check(args.home, os.environ, agents):
        sys.exit(1)


if __name__ == "__main__":
    main()
