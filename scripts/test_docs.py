"""Keep the documentation and the scripts it mentions in sync."""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = sorted(p for p in ROOT.rglob("*.md") if ".git" not in p.parts)
LINK = re.compile(r"\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6} (.+)$", re.MULTILINE)
SCRIPT = re.compile(r"scripts/([a-z_]+\.py)")


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


if __name__ == "__main__":
    unittest.main()
