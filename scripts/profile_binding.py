"""Save or locate one private Quota Coach profile without copying its contents."""

import argparse
import json
import os
import tempfile
from pathlib import Path

from capacity_policy import require, validate_profile


def private_folder(home=None) -> Path:
    """The private folder, moving the one from before the rename there on first use."""
    home = Path.home() if home is None else home
    folder, former = home / ".config" / "quota-coach", home / ".codex-top-mode"
    if folder.exists() or former.is_symlink() or not former.is_dir():
        return folder
    if in_worktree(folder.resolve()):
        return former
    try:
        folder.parent.mkdir(parents=True, exist_ok=True)
        former.rename(folder)
    except OSError:
        return former
    try:
        # Paths saved before the move, such as the profile's, keep working.
        former.symlink_to(folder, target_is_directory=True)
    except OSError:
        folder.rename(former)
        return former
    return folder


def default_binding() -> Path:
    return private_folder() / "binding.json"


def in_worktree(path: Path) -> bool:
    return any(
        (parent / ".git").exists() or (parent / ".git").is_symlink()
        for parent in (path.parent, *path.parent.parents)
    )


def private_path(path: Path, *, existing: bool) -> Path:
    path = path.expanduser()
    require(path.is_absolute(), "Use an absolute private path")
    require(not path.is_symlink(), "Private files must not be symlinks")
    path = path.resolve(strict=existing)
    require(not in_worktree(path), "Keep private files outside Git worktrees, even ignored folders")
    if existing:
        require(path.is_file(), "A private regular file is required")
        if os.name == "posix":
            require(not path.stat().st_mode & 0o077, "Restrict the file to its owner")
    return path


def locate(binding: Path) -> dict:
    binding = private_path(binding, existing=True)
    data = json.loads(binding.read_text(encoding="utf-8"))
    require(
        isinstance(data, dict)
        and set(data) == {"schemaVersion", "profilePath"}
        and type(data["schemaVersion"]) is int
        and data["schemaVersion"] == 1
        and isinstance(data["profilePath"], str)
        and bool(data["profilePath"].strip()),
        "Unsupported private binding",
    )
    profile = private_path(Path(data["profilePath"]), existing=True)
    return {"bindingPath": str(binding), "profilePath": str(profile)}


def bind(binding: Path, profile: Path, *, replace: bool = False) -> dict:
    profile = private_path(profile, existing=True)
    validate_profile(json.loads(profile.read_text(encoding="utf-8")))
    binding = private_path(binding, existing=False)
    require(binding != profile, "The binding must not replace the profile")
    if binding.exists() and not replace:
        current = locate(binding)
        if current["profilePath"] == str(profile):
            return current
        raise ValueError("A different profile is bound; confirm before using --replace")
    binding.parent.mkdir(mode=0o700, exist_ok=True)
    if os.name == "posix":
        require(
            not binding.parent.stat().st_mode & 0o077,
            "Use an owner-only directory for the binding",
        )
    handle, name = tempfile.mkstemp(prefix=".binding-", dir=binding.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"schemaVersion": 1, "profilePath": str(profile)}, stream)
            stream.write("\n")
        if replace:
            os.replace(name, binding)
        else:
            # Publish without overwriting another setup that won the create race.
            os.link(name, binding)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return locate(binding)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, help="Default: binding.json in the private folder")
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("bind", help="Save the approved profile's location")
    setup.add_argument("--profile", type=Path, required=True)
    setup.add_argument("--replace", action="store_true")
    commands.add_parser("locate", help="Locate a profile without starting work")
    args = parser.parse_args()
    args.binding = args.binding or default_binding()
    try:
        result = (
            bind(args.binding, args.profile, replace=args.replace)
            if args.command == "bind"
            else locate(args.binding)
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
