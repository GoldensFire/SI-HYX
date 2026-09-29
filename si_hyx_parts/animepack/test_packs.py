"""Classify existing SIQ packs by their actual number of questions."""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile


TEST_LIMIT = 96


def is_test_pack(path: str) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("content.xml"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError):
        return False
    return sum(1 for node in root.iter()
               if node.tag.rsplit("}", 1)[-1] == "question") < TEST_LIMIT
