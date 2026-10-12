"""Turn the user's Quota Coach level into their agent's own permission rules.

The agent answers each command from its own rules, not from the profile, so a
level governs only once its rules are in the folder where the user starts Top
Mode. Without --write this shows whether that folder's rules match the level;
with it, it writes them there. Claude Code's settings keep every rule this did
not add; Codex gets a rules file of its own.
"""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path, PureWindowsPath

from capacity_policy import effective_actions, require, validate_profile
from profile_binding import locate, private_path

PRIVATE = Path.home() / ".codex-top-mode"
PACKAGE = Path(__file__).resolve().parents[1]
BRANCH = "quota-coach/"
LISTS = {"allowed": "allow", "ask": "ask", "deny": "deny"}
# The run's own bookkeeping, needed at every level.
OWN = (
    "run.py",
    "check.py",
    "capacity_policy.py",
    "usage_report.py",
    "profile_binding.py locate",
)
# Claude Code Bash rules for each action. They match a command's text, not its
# effect, so protecting the default branch on GitHub stays the real guard. An
# allowed prefix takes any words after it, so commands with a destructive option
# are allowed only in the narrow forms a run needs, and each such option is
# denied below wherever it appears as its own word.
COMMANDS = {
    "read": (
        "git status:*",
        "git log:*",
        "git diff:*",
        "git show:*",
        "git fetch:*",
        "gh pr list:*",
        "gh pr view:*",
        "gh pr diff:*",
        "gh pr checks:*",
        "gh issue list:*",
        "gh issue view:*",
        "gh run list:*",
        "gh run view:*",
    ),
    "commit": (
        "git add:*",
        "git commit:*",
        f"git switch -c {BRANCH}*",
        f"git switch --create {BRANCH}*",
        f"git switch {BRANCH}*",
        f"git checkout -b {BRANCH}*",
        "git worktree add:*",
    ),
    "publish_pr": (f"git push -u origin {BRANCH}*", f"git push origin {BRANCH}*", "gh pr create:*"),
    "review": ("gh pr review:*", "gh pr comment:*"),
    "merge": ("gh pr merge:*",),
    "install": (
        "npm install:*",
        "npm ci:*",
        "pip install:*",
        "pip3 install:*",
        "python3 -m pip install:*",
        "brew install:*",
    ),
    "access": ("gh auth:*", "security find-*"),
    "destruction": (
        "git push * +*",
        "git push * :*",
        "git reset --hard:*",
        "git clean:*",
        "rm -rf:*",
        "rm -fr:*",
        "gh repo delete:*",
        "gh release delete:*",
        "security delete-*",
        "security * delete-*",
    ),
}
# Options that destroy work, per command; each is denied as its own word
# anywhere in the command. Combined short options (`-qC`) are not caught.
DESTRUCTIVE = {
    "git push": ("--force", "-f", "--delete", "-d"),
    "git switch": ("--force", "-f", "--discard-changes", "-C"),
    "git checkout": ("--force", "-f", "-B"),
    "git worktree add": ("--force", "-f", "-B"),
    "git branch": ("--force", "-f", "-D", "-M", "-C"),
}
# Denied at every level: work goes to a working branch, never the default one.
DEFAULT_BRANCH = tuple(
    rule
    for name in ("main", "master")
    for rule in (
        f"git push * {name}",
        f"git push * {name} *",
        f"git push *:{name}*",
        f"git push *refs/heads/{name}*",
    )
)
# Codex runs most commands in its sandbox without asking. Its rules name those
# that leave it (writing .git, using the network), each a prefix of literal
# words where a list means any of them; a command that matches several rules
# gets the strictest decision.
CODEX = {
    "read": (
        ["git", "fetch"],
        ["gh", "pr", ["list", "view", "diff", "checks"]],
        ["gh", "issue", ["list", "view"]],
        ["gh", "run", ["list", "view"]],
    ),
    "commit": (
        ["git", ["add", "commit"]],
        ["git", "switch", ["-c", "--create"]],
        ["git", "checkout", "-b"],
        ["git", "worktree", "add"],
    ),
    "publish_pr": (["git", "push"], ["gh", "pr", "create"]),
    "review": (["gh", "pr", ["review", "comment"]],),
    "merge": (["gh", "pr", "merge"],),
    "install": (
        ["npm", ["install", "ci"]],
        ["pip", "install"],
        ["pip3", "install"],
        ["python3", "-m", "pip", "install"],
        ["brew", "install"],
    ),
    "access": (
        ["gh", "auth"],
        ["security", ["find-generic-password", "find-internet-password", "find-identity"]],
    ),
    "destruction": (
        ["git", "push", ["--force", "-f", "--delete"]],
        ["git", "reset", "--hard"],
        ["git", "switch", ["-f", "--force", "--discard-changes", "-C", "--force-create"]],
        ["git", "checkout", "-B"],
        ["git", "clean"],
        ["git", "branch", "-D"],
        ["rm", ["-rf", "-fr"]],
        ["gh", "repo", "delete"],
        ["gh", "release", "delete"],
        [
            "security",
            [
                "delete-keychain",
                "delete-generic-password",
                "delete-internet-password",
                "delete-identity",
                "delete-certificate",
            ],
        ],
    ),
}
CODEX_DEFAULT_BRANCH = (
    ["git", "push", "origin", ["main", "master"]],
    ["git", "push", "-u", "origin", ["main", "master"]],
)
CODEX_DECISIONS = {"allowed": "allow", "ask": "prompt", "deny": "forbidden"}
CODEX_HEADER = """\
# Written by Quota Coach (host_rules.py) from your profile, and rewritten whole
# when your level changes. Keep your own rules in another file. Codex reads
# rules when a session starts.
"""


def folder_rule(tool: str, folder: str) -> str:
    """Claude Code reads `//path` as absolute, and `C:\\work` as `//c/work`."""
    windows = PureWindowsPath(folder)
    if windows.drive:
        require(windows.drive.endswith(":"), f"Network folders are not supported: {folder}")
        folder = "/".join([f"/{windows.drive[0].lower()}", *windows.parts[1:]])
    return f"{tool}(/{folder}/**)"


def package_folders(package: Path) -> list:
    """The package as an agent may write it: absolute, or from the home folder."""
    folders = [str(package)]
    home = Path.home()
    if package.is_relative_to(home):
        folders.append(f"~/{package.relative_to(home)}")
    return folders


def expected(profile: dict, package: Path = PACKAGE) -> dict:
    """The allow, ask and deny rules for the profile's level and exceptions."""
    validate_profile(profile)
    decisions = effective_actions(profile)
    rules = {name: set() for name in LISTS.values()}

    def add(action: str, entries) -> None:
        rules[LISTS[decisions[action]]].update(entries)

    for action, commands in COMMANDS.items():
        add(action, (f"Bash({c})" for c in commands))
    add(
        "destruction",
        (
            f"Bash({command}{gap}{option}*)"
            for command, options in DESTRUCTIVE.items()
            for option in options
            for gap in (" ", " * ")
        ),
    )
    for project in profile["projects"].values():
        add("read", [folder_rule("Read", project["path"])])
        add("edit", [folder_rule("Edit", project["path"])])
        add("checks", (f"Bash({c}:*)" for c in project.get("checks", [])))
    rules["allow"].update(
        f"Bash(python3 -B {folder}/scripts/{script}:*)"
        for folder in package_folders(package)
        for script in OWN
    )
    rules["deny"].update(f"Bash({c})" for c in DEFAULT_BRANCH)
    for folder in profile.get("excluded", []):
        rules["deny"].update(folder_rule(tool, folder) for tool in ("Read", "Edit"))
    # A stricter list wins in Claude Code anyway; keep each rule in one list.
    rules["allow"] -= rules["ask"] | rules["deny"]
    rules["ask"] -= rules["deny"]
    return {name: sorted(entries) for name, entries in rules.items()}


def words(pattern: list) -> str:
    return " ".join("|".join(w) if isinstance(w, list) else w for w in pattern)


def codex_rules(profile: dict, package: Path = PACKAGE) -> list:
    """(pattern, decision, why) for the profile's level and exceptions."""
    validate_profile(profile)
    decisions = effective_actions(profile)
    rules = [
        (
            pattern,
            CODEX_DECISIONS[decisions[action]],
            f"Your setup: {action} is {decisions[action]}",
        )
        for action, patterns in CODEX.items()
        for pattern in patterns
    ]
    rules += [
        (["python3", "-B", f"{folder}/scripts/{script}", *rest], "allow", "Quota Coach itself")
        for folder in package_folders(package)
        for script, *rest in (name.split() for name in OWN)
    ]
    rules += [(p, "forbidden", "never the default branch") for p in CODEX_DEFAULT_BRANCH]
    return rules


def codex_text(rules: list) -> str:
    return CODEX_HEADER + "".join(
        f"prefix_rule(pattern={json.dumps(pattern)}, decision={json.dumps(decision)}, "
        f"justification={json.dumps(why)})\n"
        for pattern, decision, why in rules
    )


def read_json(path: Path, default: dict) -> dict:
    if not path.exists() and not path.is_symlink():
        return default
    data = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(data, dict), f"{path} must hold a JSON object")
    return data


def permission_lists(settings: dict) -> dict:
    permissions = settings.get("permissions", {})
    require(isinstance(permissions, dict), "The settings' permissions must be an object")
    lists = {name: permissions.get(name, []) for name in LISTS.values()}
    require(
        all(isinstance(v, list) and all(isinstance(r, str) for r in v) for v in lists.values()),
        "The settings' allow, ask and deny must be lists of rules",
    )
    return lists


def changes(settings: dict, rules: dict, added: dict) -> dict:
    """What to add, and which rules this script added before that no longer apply."""
    present = permission_lists(settings)
    return {
        "add": {k: [r for r in rules[k] if r not in present[k]] for k in rules},
        "remove": {
            k: [r for r in added.get(k, []) if r in present[k] and r not in rules[k]] for k in rules
        },
    }


def apply(settings: dict, change: dict) -> dict:
    """The settings with the change made; every other key and rule stays."""
    present = permission_lists(settings)
    lists = {
        k: [r for r in present[k] if r not in change["remove"][k]] + change["add"][k]
        for k in present
    }
    permissions = dict(settings.get("permissions", {}))
    for name, entries in lists.items():
        if entries:
            permissions[name] = entries
        else:
            permissions.pop(name, None)
    return {**settings, "permissions": permissions}


def rules_path(folder: Path, *parts: str) -> Path:
    folder = folder.expanduser()
    require(folder.is_absolute() and folder.is_dir(), "Use the absolute folder where you start")
    path = folder.joinpath(*parts)
    require(not path.is_symlink(), f"{path} is a link: change the file it points to instead")
    return path


def outside_git(folder: Path, path: Path) -> None:
    """The rules name the user's folders, so Git must never pick them up."""
    if not any((p / ".git").exists() for p in (folder, *folder.parents)):
        return
    ignored = subprocess.run(
        ["git", "-C", str(folder), "check-ignore", "-q", str(path)], capture_output=True
    )
    require(ignored.returncode == 0, f"Have Git ignore {path} first")


def write_text(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=".quota-coach-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, data: dict, mode: int) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", mode)


def sync_claude(profile: dict, folder: Path, private: Path, write: bool, package=PACKAGE):
    """Compare the folder's Claude Code rules with the level; if asked, bring them in line."""
    folder = folder.expanduser()
    path = rules_path(folder, ".claude", "settings.local.json")
    state_path = private_path(private / "host-rules.json", existing=False)
    if state_path.exists():
        private_path(state_path, existing=True)
    state = read_json(state_path, {"schemaVersion": 1, "claude": {}})
    require(
        state.get("schemaVersion") == 1 and isinstance(state.get("claude"), dict),
        "Unsupported host rules record",
    )
    settings = read_json(path, {})
    rules = expected(profile, package)
    change = changes(settings, rules, state["claude"].get(str(path), {}))
    current = not any(change["add"].values()) and not any(change["remove"].values())
    if write and not current:
        outside_git(folder, path)
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
        write_json(path, apply(settings, change), mode)
        mine = state["claude"].get(str(path), {})
        state["claude"][str(path)] = {
            k: sorted(
                {r for r in mine.get(k, []) if r not in change["remove"][k]} | set(change["add"][k])
            )
            for k in rules
        }
        private.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_json(state_path, state, 0o600)
    return {
        "agent": "claude",
        "settings": str(path),
        "current": current or write,
        "written": write and not current,
        **change,
    }


def sync_codex(profile: dict, folder: Path, write: bool, package: Path = PACKAGE) -> dict:
    """Compare the folder's Codex rules file with the level; if asked, rewrite it."""
    folder = folder.expanduser()
    path = rules_path(folder, ".codex", "rules", "quota-coach.rules")
    rules = codex_rules(profile, package)
    text = codex_text(rules)
    current = path.exists() and path.read_text(encoding="utf-8") == text
    if write and not current:
        outside_git(folder, path)
        write_text(path, text, 0o600)
    return {
        "agent": "codex",
        "rules": str(path),
        "current": current or write,
        "written": write and not current,
        **{
            decision: [words(p) for p, d, _ in rules if d == decision]
            for decision in CODEX_DECISIONS.values()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=["claude", "codex"], required=True)
    parser.add_argument("--profile", type=Path, help="Default: the saved setup")
    parser.add_argument(
        "--folder", type=Path, default=Path.cwd(), help="Where the user starts Top Mode"
    )
    parser.add_argument("--write", action="store_true", help="Only with the user's OK")
    parser.add_argument("--private", type=Path, default=PRIVATE, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        path = args.profile or Path(locate(args.private / "binding.json")["profilePath"])
        profile = json.loads(path.read_text(encoding="utf-8"))
        result = (
            sync_claude(profile, args.folder, args.private, args.write)
            if args.agent == "claude"
            else sync_codex(profile, args.folder, args.write)
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
