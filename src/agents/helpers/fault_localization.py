"""
Standalone experiment: derive a Defects4J bug's file(s) and changed line ranges
automatically, by diffing the buggy checkout against the human-fixed checkout,
instead of hand-typing bug locations.
"""

import difflib
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from defects4j_utils import checkout_defects4j_project, get_modified_sources


def find_source_file(checkout_root: str, full_class_name: str) -> str | None:
    """
    Locate a Java source file under checkout_root matching a fully-qualified class name
    full_class_name is the result of calling get_modified_sources
    """
    # class path currently connected by ., replace by / to make it a valid file path
    relative_suffix = Path(full_class_name.replace(".", os.sep) + ".java")
    # recursively glob the entire checkout to find file matching the exact class path
    matches = list(Path(checkout_root).rglob(relative_suffix.name))
    for match in matches:
        if match.as_posix().endswith(relative_suffix.as_posix()):
            return str(match)
    return None


def diff_to_line_ranges(buggy_lines: List[str], fixed_lines: List[str]) -> List[Tuple[int, int]]:
    """
    Diff buggy vs. fixed file lines
    Return bug locations as 1-based inclusive line ranges, based on the original buggy file
    """
    matcher = difflib.SequenceMatcher(None, buggy_lines, fixed_lines)
    line_ranges = []
    # possible tags: 'replace', 'delete', 'insert', 'equal'
    for tag, i1, i2, _, _ in matcher.get_opcodes():
        if tag == "equal":
            continue
        # i1 and i2 are indeces indicating line ranges in buggy_lines that were changed
        if i1 == i2:
            # Pure insertion: nothing removed from the buggy file
            # Mark bug location as the single line where the insertion occurs
            insert_loc = max(i1, 1)
            line_ranges.append((insert_loc, insert_loc))
        else:
            # 0-based half-open [i1:i2) -> 1-based inclusive (i1+1, i2)
            line_ranges.append((i1 + 1, i2))
    return line_ranges


def find_bug_locations(project_name: str, bug_id: str, buggy_checkout: str) -> List[Tuple[str, str, List[Tuple[int, int]]]]:
    """
    Derive bug locations for a Defects4J bug by comparing the diff of the buggy and fixed checkout

    Assumes the buggy version has already been checked out via BugDict.add_paths and exists at buggy_checkout

    Returns a list of (absolute_file_path, modified_source_name, [(start_line, end_line), ...]),
    matching the format BugDict stores under "bug files and locations".
    """
    # don't need to use fixed checkout anywhere else, so ok to check out in a temp directory
    with tempfile.TemporaryDirectory() as fixed_dir:
        if not checkout_defects4j_project(project_name, bug_id, fixed_dir, buggy=False):
            raise RuntimeError(f"Failed to checkout fixed version of {project_name}-{bug_id}")

        modified_classes = get_modified_sources(project_name, bug_id)

        bug_locations = []
        for full_class_name in modified_classes:
            buggy_file = find_source_file(buggy_checkout, full_class_name)
            fixed_file = find_source_file(fixed_dir, full_class_name)
            if not buggy_file or not fixed_file:
                print(f"[WARN] Could not locate {full_class_name} in both checkouts, skipping")
                continue

            with open(buggy_file, "r", encoding="utf-8", errors="replace") as f:
                buggy_lines = f.readlines()
            with open(fixed_file, "r", encoding="utf-8", errors="replace") as f:
                fixed_lines = f.readlines()

            line_ranges = diff_to_line_ranges(buggy_lines, fixed_lines)
            if not line_ranges:
                continue

            # full_class_name is already the Defects4J-style modified source name
            bug_locations.append((buggy_file, full_class_name, line_ranges))

        return bug_locations
