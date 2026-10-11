"""Keep the documentation and the scripts it mentions in sync."""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The package's own docs only: not notes, virtual environments or generated files.
DOCS = sorted(p for folder in ("", "references", "examples") for p in (ROOT / folder).glob("*.md"))
LINK = re.compile(r"\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6} (.+)$", re.MULTILINE)
SCRIPT = re.compile(r"scripts/([a-z_]+\.py)")
MENTION = re.compile(r"\b([a-z_]+\.py)\b")
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z-]*")


def anchor(heading):
    """GitHub's anchor for a Markdown heading."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


class DocumentationTests(unittest.TestCase):
    def test_local_links_and_anchors_resolve(self):
        broken = []
        for doc in DOCS:
            for target in LINK.findall(doc.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path, _, fragment = target.partition("#")
                resolved = (doc.parent / path).resolve() if path else doc
                if not resolved.exists():
                    broken.append(f"{doc.relative_to(ROOT)}: {target}")
                elif fragment and resolved.suffix == ".md":
                    headings = HEADING.findall(resolved.read_text(encoding="utf-8"))
                    if fragment not in {anchor(h) for h in headings}:
                        broken.append(f"{doc.relative_to(ROOT)}: {target}")
        self.assertEqual(broken, [])

    def test_scripts_named_in_docs_exist_and_show_help(self):
        named = set()
        for doc in DOCS:
            named.update(SCRIPT.findall(doc.read_text(encoding="utf-8")))
        self.assertTrue(named)
        for name in sorted(named):
            with self.subTest(script=name):
                script = ROOT / "scripts" / name
                self.assertTrue(script.exists(), name)
                result = subprocess.run(
                    [sys.executable, "-B", str(script), "--help"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_documented_flags_exist(self):
        """Each --flag written after a script's name is one that script accepts."""
        scripts = {p.name for p in (ROOT / "scripts").glob("*.py")}
        unknown = []
        for doc in DOCS:
            text = doc.read_text(encoding="utf-8").replace("\\\n", " ")
            for line in text.splitlines():
                parts = MENTION.split(line)
                # parts: text, name, text, name, text... flags belong to the name before them.
                for name, after in zip(parts[1::2], parts[2::2]):
                    for flag in FLAG.findall(after) if name in scripts else []:
                        if flag not in flags_of(name):
                            unknown.append(f"{doc.relative_to(ROOT)}: {name} {flag}")
        self.assertEqual(unknown, [])


class SkillTests(unittest.TestCase):
    """What Codex and Claude Code need to load the skill (agentskills.io)."""

    def test_frontmatter_follows_the_agent_skills_format(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        head, separator, _ = text.removeprefix("---\n").partition("\n---\n")
        self.assertTrue(text.startswith("---\n") and separator, "frontmatter is missing")
        fields = dict(line.split(": ", 1) for line in head.splitlines())
        self.assertRegex(fields.get("name", ""), r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(fields["name"]), 64)
        self.assertTrue(0 < len(fields.get("description", "")) <= 1024)
        self.assertLess(len(text.splitlines()), 500)


_HELP = {}


def flags_of(name):
    """The flags in --help of a script and of each of its subcommands."""
    if name not in _HELP:
        script = str(ROOT / "scripts" / name)

        def run(*args):
            command = [sys.executable, "-B", script, *args, "--help"]
            return subprocess.run(command, capture_output=True, text=True, check=False).stdout

        text = run()
        commands = re.search(r"\{([a-z,]+)\}", text)
        for command in commands.group(1).split(",") if commands else []:
            text += run(command)
        _HELP[name] = set(FLAG.findall(text))
    return _HELP[name]


if __name__ == "__main__":
    unittest.main()
