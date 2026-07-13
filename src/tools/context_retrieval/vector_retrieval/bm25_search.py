import json
import os
import sys
import subprocess
from typing import Any, List, Dict
from pyserini.search.lucene import LuceneSearcher

parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
from src.agents.data_structures.dicts import BugDict, ContextDict
from . import bm25_utils as utils


def make_index(signatures_list: List[str], bug_dict: BugDict, context_dict: ContextDict):
    """
    Builds an index for a given set of documents using Pyserini.

    Args:
        signatures_list: List[str], obtained by calling full_signatures_in_buggy_class
        bug_dict: BugDict - For project name, bug id
        context_dict: ContextDict - For BM25 directories (jsonl_dir, index_dir)

    Returns:
        str: Path to the created index directory
    """
    # Get BM25 directories from context_dict
    jsonl_dir = context_dict.get_info("bm25 rag jsonl directory")
    index_dir = context_dict.get_info("bm25 rag index directory")
    
    # Create jsonl_dir if it doesn't exist
    os.makedirs(jsonl_dir, exist_ok=True)

    # Create index_dir if it doesn't exist
    os.makedirs(index_dir, exist_ok=True)

    # Create the actual JSONL file
    project_name = bug_dict.get_info("project name")
    bug_id = bug_dict.get_info("bug id")
    jsonl_file_path = os.path.join(jsonl_dir, f"index_{project_name}_{bug_id}.jsonl")

    # Create subdirectory for this specific index
    index_dir = context_dict.get_info("bm25 rag index directory")
    index_subdir = os.path.join(index_dir, f"index_{project_name}_{bug_id}")

    # Reuse existing index if it exists
    if os.path.exists(jsonl_file_path):
        return index_subdir
    os.makedirs(index_subdir, exist_ok=True)

    # Process signatures: {original_signature: processed_signature}
    signatures_dict = utils.build_signatures(signatures_list)

    # Add signatures to the JSONL file
    # id = original signature (what you get back from search)
    # contents = processed signature (what BM25 indexes)
    with open(jsonl_file_path, "w") as f:
        for original_sig, processed_sig in signatures_dict.items():
            f.write(json.dumps({"id": original_sig, "contents": processed_sig}) + "\n")
    
    # Get the directory containing the JSONL file (Pyserini reads from directory)
    jsonl_file_dir = os.path.dirname(jsonl_file_path)
    
    cmd = [
        sys.executable,  # Use the same Python interpreter running this script
        "-m",
        "pyserini.index",
        "--collection", "JsonCollection",  # Collection type: JSON documents
        "--generator", "DefaultLuceneDocumentGenerator",  # How to convert JSON to Lucene docs
        "--threads", "2",  # Number of threads for indexing
        "--input", jsonl_file_dir,  # Directory containing the JSONL file(s)
        "--index", index_subdir,  # Directory where index will be created
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    _, error = proc.communicate()
    
    if proc.returncode != 0:
        raise Exception(f"Failed to build index with error: {error}")
    
    return index_subdir


def search(k: int, failing_test_list: list[dict[str, str]], buggy_func_signature: str, index_subdir: str, class_name: str = None):
    """
    Searches for relevant method signatures in the given index

    Args:
        failing_test_list and buggy_func_signature: used to build the query
        instance (dict): The instance to search for.
        index_subdir (str): The path to the index to search in.

    Returns:
        list[str]: list of the top k method signatures
    """
    try:
        searcher = LuceneSearcher(index_subdir)
        query = utils.build_query(failing_test_list, buggy_func_signature, class_name=class_name)
        cutoff = len(query)
        while True:
            try:
                hits = searcher.search(
                    query[:cutoff],
                    k=k,
                    remove_dups=True,
                )
            except Exception as e:
                if "maxClauseCount" in str(e):
                    cutoff = int(round(cutoff * 0.8))
                    continue
                else:
                    raise e
            break
        # hit.score gives the BM25 score, but we don't need it for our purposes.
        # We only care about the signature, which is hit.docid
        results = []
        for hit in hits:
            results.append(hit.docid)
        return results
    except Exception as e:
        print(f"[ERROR] search hit an exception: {e}")
        return None
