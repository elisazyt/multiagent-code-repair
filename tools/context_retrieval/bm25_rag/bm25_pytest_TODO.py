"""
Unit test for BM25 query building (Chart-2 round-1 case from bm25_test.py).

Run: pytest tools/context_retrieval/bm25_rag/bm25_pytest.py -v
"""
import os
import sys

import pytest

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tools.context_retrieval.bm25_rag import bm25_utils

CHART2_BUGGY_SIG = (
    "org.jfree.data.general.DatasetUtilities.iterateDomainBounds:"
    "org.jfree.data.Range(org.jfree.data.xy.XYDataset,boolean)"
)


def test_build_query_round1_uses_buggy_signature_tokens():
    """Empty test_info (round 1) + buggy Joern signature → tokenized BM25 query."""
    test_info = [{
        "failing test": "",
        "failure message": "",
        "buggy method": "",
        "buggy line": "",
    }]
    query = bm25_utils.build_query(test_info, CHART2_BUGGY_SIG, class_name="DatasetUtilities")

    assert "iterate" in query
    assert "Domain" in query
    assert "Bounds" in query
    assert "XYDataset" in query
