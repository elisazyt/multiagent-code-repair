import json
import os
import sys
import subprocess
import re
from typing import Any, List, Dict
from pyserini.search.lucene import LuceneSearcher

# Add autogen_agents to path to import InfoDict
# File is at: bm25_rag/bm25_test.py, need to go up one level to autogen_agents/
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
autogen_agents_path = os.path.join(parent_dir, 'autogen_agents')
if autogen_agents_path not in sys.path:
    sys.path.append(autogen_agents_path)
from info_dict import InfoDict, ContextDict
import context_retrieval.joern_session as joern_session

def build_signatures(signatures_list: List[str]) -> Dict[str, str]:
    """
    Builds a dictionary of documents from a given repository directory and commit.

    Args:
        signatures_list (List[str]): A list of signatures resulting from calling all_signatures_in_class.
        class_name (str, optional): Class name to strip from signatures (e.g., "CategoryPlot").
                                   If provided, strips class prefix to reduce noise in BM25 search.

    Returns:
        dict: A dictionary where keys are original signatures and values are processed signatures.
    """
    signatures = dict()
    for signature in signatures_list:
        stripped = strip_characters(signature)
        split_str = split_words(stripped)
        signatures[signature] = split_str
    return signatures

def build_query(failing_test_info: str, buggy_func_signature: str, class_name: str) -> str:
    """
    Build a processed query for BM25 search.
    
    Args:
        failing_test_info: Test failure information
        buggy_func_signature: Buggy function signature
        class_name: Optional class name to strip from signature
    
    Returns:
        Processed query string (stripped and split)
    """    
    query = failing_test_info + " " + buggy_func_signature
    query = strip_characters(query)
    query = split_words(query)
    return query

def strip_characters(original_str: str) -> str:
    '''
    Replace special characters with spaces: ()[]{}<>,:;/
    This preserves word boundaries for better tokenization.
    '''
    stripped = original_str.replace('(', ' ').replace(')', ' ').replace('[', ' ').replace(']', ' ').replace('{', ' ').replace('}', ' ').replace('<', ' ').replace('>', ' ')
    stripped = stripped.replace(',', ' ').replace(':', ' ').replace(';', ' ').replace('/', ' ')
    # Replace multiple spaces with single space and strip
    import re
    stripped = re.sub(r'\s+', ' ', stripped).strip()
    return stripped

def split_words(stripped_str: str) -> str:
    '''
    Split words into subtokens when the following appear:
        - capital letter (camel case)
        - numbers
        - _ (snake case)
        - :: (test failures)
        - . (package separator)
    '''
    words = []
    for word in stripped_str.split():
        if not word:  # Skip empty strings
            continue
        
        # First split on :: (test failures)
        parts = word.split('::')
        for part in parts:
            # Then split on . (package separator)
            dot_parts = part.split('.')
            for dot_part in dot_parts:
                # Then split on _ (snake case)
                underscore_parts = dot_part.split('_')
                for underscore_part in underscore_parts:
                    if not underscore_part:
                        continue
                    
                    # Split on camel case (before capital letters) and number boundaries
                    # Pattern: split before capital letters (but not at start), and between letters/numbers
                    tokens = re.split(r'(?<![A-Z])(?=[A-Z])|(?<=\d)(?=\D)|(?<=\D)(?=\d)', underscore_part)
                    # Filter out empty strings
                    words.extend([token for token in tokens if token])
    
    return ' '.join(words)

def make_index(signatures_list: List[str], info_dict: InfoDict, context_dict: ContextDict):
    """
    Builds an index for a given set of documents using Pyserini.

    Args:
        signatures_list: List[str], obtained by calling all_funcs_in_class
        info_dict: InfoDict - For project name, bug id
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
    project_name = info_dict.get_info("project name")
    bug_id = info_dict.get_info("bug id")
    jsonl_file_path = os.path.join(jsonl_dir, f"index_{project_name}_{bug_id}.jsonl")

    '''
    # TODO: if the jsonl file already exists, we have already run this query before
    if os.path.exists(jsonl_file_path):
        return None
    '''

    # Process signatures: {original_signature: processed_signature}
    signatures_dict = build_signatures(signatures_list)

    # Add signatures to the JSONL file
    # id = original signature (what you get back from search)
    # contents = processed signature (what BM25 indexes)
    with open(jsonl_file_path, "w") as f:
        for original_sig, processed_sig in signatures_dict.items():
            f.write(json.dumps({"id": original_sig, "contents": processed_sig}) + "\n")
    
    # Get the directory containing the JSONL file (Pyserini reads from directory)
    jsonl_file_dir = os.path.dirname(jsonl_file_path)
    
    # Create subdirectory for this specific index
    index_dir = context_dict.get_info("bm25 rag index directory")
    index_subdir = os.path.join(index_dir, f"index_{project_name}_{bug_id}")
    # Clear old index if it exists (to avoid mixing old and new signatures)
    if os.path.exists(index_subdir):
        import shutil
        shutil.rmtree(index_subdir)
    os.makedirs(index_subdir, exist_ok=True)
    
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
    output, error = proc.communicate()
    
    if proc.returncode != 0:
        raise Exception(f"Failed to build index with error: {error}")
    
    return index_subdir

def search(k: int, failing_test_info: str, buggy_func_signature: str, index_subdir: str, class_name: str = None):
    """
    Searches for relevant documents in the given index for the given instance.

    Args:
        instance (dict): The instance to search for.
        index_subdir (str): The path to the index to search in.

    Returns:
        dict: A dictionary containing the instance ID and a list of hits, where each hit is a dictionary containing the
        document ID and its score.
    """
    try:
        searcher = LuceneSearcher(index_subdir)
        query = build_query(failing_test_info, buggy_func_signature, class_name=class_name)
        print(f"Query: {query}")
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
        print(f"Failed to process query: {e}")
        import traceback
        traceback.print_exc()
        return None
