"""Check the R10 source catalogue locally, optionally against the original Word file."""

import hashlib
import re
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs/nguon-va-bang-chung.md"
PLAN_HASH = "975228ea14edce90cfecbbfe05c9911dd33b35fd1a4acef75577a9499d884c9f"
ROW = re.compile(r"^\| (\d+) \| \[[^\]]+\]\(([^)]+)\) \| ([^|]+) \| ([^|]+) \|$", re.M)


class SourceCatalogTests(unittest.TestCase):
    def test_sources_are_ordered_unique_and_annotated(self):
        rows = ROW.findall(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual([int(row[0]) for row in rows], list(range(1, 22)))
        urls = [row[1] for row in rows]
        self.assertEqual(len(set(urls)), 21)
        for _, url, location, application in rows:
            with self.subTest(url=url):
                self.assertEqual(urlsplit(url).scheme, "https")
                self.assertTrue(urlsplit(url).hostname)
                self.assertTrue(location.strip() and application.strip())

    def test_local_evidence_references_exist(self):
        links = re.findall(r"\]\(([^)]+)\)", CATALOG.read_text(encoding="utf-8"))
        local_links = [link for link in links if not urlsplit(link).scheme]
        self.assertTrue(local_links)
        for link in local_links:
            self.assertTrue((CATALOG.parent / link).is_file(), link)


def compare_original(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != PLAN_HASH:
        raise ValueError("SHA256 differs from the approved P01 Word file")
    with zipfile.ZipFile(path) as archive:
        rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        document = ET.fromstring(archive.read("word/document.xml"))

    word = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    expected = []
    for paragraph in document.iter(word + "p"):
        content = "".join(node.text or "" for node in paragraph.iter(word + "t"))
        if re.match(r"^\[\d+\]\s", content):
            expected.extend(targets[link.attrib[rel + "id"]] for link in paragraph.iter(word + "hyperlink"))
    actual = [row[1] for row in ROW.findall(CATALOG.read_text(encoding="utf-8"))]
    if len(expected) != 21 or actual != expected:
        raise ValueError("Source URL or order differs from section 7 of the approved plan")
    print("21/21 source URLs match the approved Word file in order.")


if __name__ == "__main__":
    if len(sys.argv) == 2 and Path(sys.argv[1]).suffix.lower() == ".docx":
        compare_original(Path(sys.argv.pop()))
    unittest.main()
