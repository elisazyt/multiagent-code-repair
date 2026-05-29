import json
import os
import sys
import subprocess
import re
from typing import Any, List, Dict
from pyserini.search.lucene import LuceneSearcher

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from autogen_agents.info_dict import InfoDict, ContextDict
from bm25_rag import bm25_code_snippets as bm25_cs
from bm25_rag import bm25_utils as bm25_utils
from dotenv import load_dotenv

project_root = parent_dir
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

# Get checkout directory from .env file (where Defects4J projects will be checked out)
checkout_directory = os.getenv('CHECKOUT_DIR')
if not checkout_directory:
    raise ValueError("CHECKOUT_DIR not set in .env file. Please set it to the directory where Defects4J projects should be checked out.")
checkout_directory = os.path.abspath(checkout_directory)

# Create checkout directory if it doesn't exist
os.makedirs(checkout_directory, exist_ok=True)

# working_directory is where Defects4J checkouts will be stored
working_directory = checkout_directory

jsonl_dir = os.path.join(project_root, "bm25_output", "jsonl")
index_dir = os.path.join(project_root, "bm25_output", "index")

chart2_path = os.path.join(project_root, "ALL_TESTS", "chart2.java")
information = InfoDict()
information.add_bug_info(
    project_name="Chart",
    bug_id="2",
    bug_locations=[(chart2_path, [(756, 757)])],
    working_directory=working_directory
)
joern_executable = os.getenv('JOERN_EXECUTABLE')
joern_directory = os.getenv('JOERN_DIRECTORY')
joern_github_dir = os.getenv('JOERN_GITHUB_DIR')
if joern_executable and joern_directory:
    information.add_joern_config(joern_executable, joern_directory)

context_dict = ContextDict(information)
context_dict.add_bm25_rag_config(10, jsonl_dir, index_dir, 10, 20, 8)

from context_retrieval.joern_session import JoernSession

# Check if CPG exists, create it if it doesn't
cpg_project_name = "Chart2"
cpg_path = os.path.join(joern_directory, 'workspace', cpg_project_name, 'cpg.bin.zip')
joern_session = JoernSession(chart2_path, joern_executable, joern_directory)
if not os.path.exists(cpg_path):
    print(f"CPG not found at {cpg_path}, creating it...")
    if not joern_github_dir:
        print("ERROR: JOERN_GITHUB_DIR not set in .env file. Cannot create CPG.")
        exit(1)
    success = joern_session.create_cpg_from_defects4j(
        project_name="Chart",
        bug_id="2",
        checkout_dir=working_directory,
        joern_github_dir=joern_github_dir
    )
    if not success:
        print("ERROR: Failed to create CPG. Cannot continue.")
        exit(1)
    else:
        print(f"CPG already exists at {cpg_path}")

# Load the CPG for querying
if not joern_session.load_cpg(cpg_project_name):
    print("ERROR: Failed to load CPG. Cannot continue.")
    exit(1)

try:
    import context_retrieval.isolate_bug as ib
    bug_location = (756, 757)
    class_name = ib.extract_class_name_from_file(chart2_path, bug_location)
except ValueError as e:
    # If class name extraction fails, log warning but continue
    # Some functions don't require class_name, so we'll handle it per function
    print(f"Warning: Could not extract class name: {e}")
    class_name = None

print(f"Class name: {class_name}")

start_line, end_line = 756, 757
signatures = joern_session.get_full_signatures_in_buggy_class(chart2_path, (start_line, end_line))

print(f"Found {len(signatures)} signatures in class")
if signatures:
    print(f"Signatures: {signatures}")
    print(f"First signature example: {signatures[0]}")
else:
    print("WARNING: No signatures found. Cannot build index without signatures.")
    exit(1)

test_info = {
    'failing test': "", # test identifier
    'failure message': "",
    'buggy method': "",  # buggy method with marked line numbers
    'buggy line': ""
}
# Get the actual buggy function signature at the bug location
bug_location = (756, 757)
buggy_sig = joern_session.get_full_method_signature_from_line_numbers(chart2_path, bug_location, class_name)
if not buggy_sig:
    print(f"WARNING: Could not find method signature at bug location {bug_location}")
    buggy_sig = ""
else:
    print(f"Found buggy function signature: {buggy_sig}")



########################################################
# ACTUAL USAGE OF BM25 WITHIN FILE
########################################################

index_path = bm25_cs.make_index(signatures, information, context_dict)
print(f"Index created at {index_path}")

results = bm25_cs.search(10, test_info, buggy_sig, index_path, class_name=class_name)
print(f"Query: {bm25_utils.build_query(test_info, buggy_sig, class_name=class_name)}")
print(f"Results ({len(results)}): {results}")


