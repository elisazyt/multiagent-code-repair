"""
Standalone experiment: derive a Defects4J bug's file(s) and changed line ranges
automatically, by diffing the buggy checkout against the human-fixed checkout,
instead of hand-typing bug locations.
"""

import difflib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from defects4j_utils import checkout_defects4j_project, get_modified_sources, get_java11_env


def checkout_fixed_version(project_name: str, bug_id: str, checkout_dir: str) -> bool:
    """
    Check out the patched version of a Defects4J bug (the 'f' variant).
    """
    try:
        result = subprocess.run(
            ['defects4j', 'checkout', '-p', project_name, '-v', bug_id + 'f', '-w', checkout_dir],
            capture_output=True,
            text=True,
            env=get_java11_env(),
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[ERROR] checkout_fixed_version hit an exception: {e}")
        return False


def find_source_file(checkout_root: str, fully_qualified_class: str) -> str | None:
    """
    Locate a Java source file under checkout_root matching a fully-qualified class name
    """
    relative_suffix = Path(fully_qualified_class.replace(".", os.sep) + ".java")
    matches = list(Path(checkout_root).rglob(relative_suffix.name))
    for match in matches:
        if match.as_posix().endswith(relative_suffix.as_posix()):
            return str(match)
    return None


def diff_to_line_ranges(buggy_lines: List[str], fixed_lines: List[str]) -> List[Tuple[int, int]]:
    """
    Diff buggy vs. fixed file lines, return 1-based inclusive line ranges on the buggy side
    """
    matcher = difflib.SequenceMatcher(None, buggy_lines, fixed_lines)
    line_ranges = []
    for tag, i1, i2, _, _ in matcher.get_opcodes():
        if tag == "equal":
            continue
        if i1 == i2:
            # Pure insertion: nothing removed from the buggy file, so anchor a
            # single-line range at the insertion point as the closest useful reference.
            anchor = max(i1, 1)
            line_ranges.append((anchor, anchor))
        else:
            # 0-based half-open [i1:i2) -> 1-based inclusive (i1+1, i2)
            line_ranges.append((i1 + 1, i2))
    return line_ranges


def find_bug_locations(project_name: str, bug_id: str) -> List[Tuple[str, List[Tuple[int, int]]]]:
    """
    Derive bug locations for a Defects4J bug by diffing the buggy checkout against
    the fixed checkout, instead of hand-typing them.

    Returns a list of (file_path_relative_to_buggy_checkout, [(start_line, end_line), ...]),
    matching the format BugDict.add_bug_locations already expects.
    """
    with tempfile.TemporaryDirectory() as buggy_dir, tempfile.TemporaryDirectory() as fixed_dir:
        if not checkout_defects4j_project(project_name, bug_id, buggy_dir):
            raise RuntimeError(f"Failed to checkout buggy version of {project_name}-{bug_id}")
        if not checkout_fixed_version(project_name, bug_id, fixed_dir):
            raise RuntimeError(f"Failed to checkout fixed version of {project_name}-{bug_id}")

        modified_classes = get_modified_sources(project_name, bug_id)

        bug_locations = []
        for fully_qualified_class in modified_classes:
            buggy_file = find_source_file(buggy_dir, fully_qualified_class)
            fixed_file = find_source_file(fixed_dir, fully_qualified_class)
            if not buggy_file or not fixed_file:
                print(f"[WARN] Could not locate {fully_qualified_class} in both checkouts, skipping")
                continue

            with open(buggy_file, "r", encoding="utf-8", errors="replace") as f:
                buggy_lines = f.readlines()
            with open(fixed_file, "r", encoding="utf-8", errors="replace") as f:
                fixed_lines = f.readlines()

            line_ranges = diff_to_line_ranges(buggy_lines, fixed_lines)
            if not line_ranges:
                continue

            relative_path = os.path.relpath(buggy_file, buggy_dir)
            bug_locations.append((relative_path, line_ranges))

        return bug_locations


if __name__ == "__main__":
    result = find_bug_locations("Closure", "16")
    print(result)
