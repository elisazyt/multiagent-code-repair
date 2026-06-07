import os
import sys
from pyserini.search.lucene import LuceneSearcher

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from agents.data_structures.dicts import BugDict, ContextDict
from tools.context_retrieval.bm25_rag import bm25_search as search
from tools.context_retrieval.bm25_rag import bm25_utils
from dotenv import load_dotenv

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

results_path = os.path.join(project_root, "tests", "test_results")
bm25_path = os.path.join(results_path, "external_tools", "bm25_indexes")
joern_executable = os.getenv("JOERN_EXECUTABLE", "/opt/homebrew/bin/joern")
joern_working_dir = os.path.dirname(os.path.realpath(joern_executable))

chart2_path = os.path.join(project_root, "tests", "ALL_TESTS", "chart2.java")
bug_dict = BugDict()
bug_dict.add_project_info("Chart", "2")
bug_dict.add_paths(
    results_path=results_path,
    bm25_path=bm25_path,
    joern_executable=joern_executable,
    joern_working_dir=joern_working_dir,
    joern_workspace_path=os.path.join(results_path, "external_tools", "joern_workspace"),
    defects4j_checkout_path=os.path.join(results_path, "external_tools", "defects4j_checkouts"),
)
bug_dict.add_bug_locations([(chart2_path, [(756, 757)])])

bm25_run = bug_dict.get_info("bm25 path")
context_dict = ContextDict(bug_dict=bug_dict)
context_dict.add_bm25_rag_config(
    k_signatures=5,
    jsonl_dir=os.path.join(bm25_run, "jsonl"),
    index_dir=os.path.join(bm25_run, "index"),
    k_code_snippets=5,
    window_size=20,
    batch_size=8,
)

from tools.context_retrieval.parsing_retrieval_funcs.joern_session import JoernSession
from tools.context_retrieval.parsing_retrieval_funcs.cr_function_implementations import get_full_signatures_in_buggy_class
from tools.context_retrieval.parsing_retrieval_funcs.joern_utils import get_full_method_signature_from_line_numbers

cpg_project_name = f"{bug_dict.get_info('project name')}{bug_dict.get_info('bug id')}"
joern_workspace_path = bug_dict.get_info("joern workspace path")
reference_checkout_dir = bug_dict.get_info("defects4j reference checkout path")
cpg_path = os.path.join(joern_workspace_path, "cpg.bin.zip")
joern_session = JoernSession(joern_executable, joern_workspace_path, joern_working_dir)
if not os.path.exists(cpg_path):
    print(f"CPG not found at {cpg_path}, creating it...")
    success = joern_session.create_cpg_from_defects4j(
        project_name="Chart",
        bug_id="2",
        reference_checkout_dir=reference_checkout_dir,
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
    from tools.context_retrieval.parsing_retrieval_funcs import tree_sitter_utils
    bug_location = (756, 757)
    class_name = tree_sitter_utils.extract_class_name_from_file(chart2_path, bug_location)
except ValueError as e:
    # If class name extraction fails, log warning but continue
    # Some functions don't require class_name, so we'll handle it per function
    print(f"Warning: Could not extract class name: {e}")
    class_name = None

print(f"Class name: {class_name}")

start_line, end_line = 756, 757
signatures = get_full_signatures_in_buggy_class(joern_session, chart2_path, (start_line, end_line))

print(f"Found {len(signatures)} signatures in class")
if signatures:
    print(f"Signatures: {signatures}")
    print(f"First signature example: {signatures[0]}")
else:
    print("WARNING: No signatures found. Cannot build index without signatures.")
    exit(1)

# Will be populated after running test suites. For now, use empty placeholder.
test_info = [{
    'failing test': "",
    'failure message': "",
    'buggy method': "",
    'buggy line': ""
}]

# Get the actual buggy function signature at the bug location
bug_location = (756, 757)
buggy_sig = get_full_method_signature_from_line_numbers(joern_session, chart2_path, bug_location, class_name)
if not buggy_sig:
    print(f"WARNING: Could not find method signature at bug location {bug_location}")
    buggy_sig = ""
else:
    print(f"Found buggy function signature: {buggy_sig}")



########################################################
# ACTUAL USAGE OF BM25 WITHIN FILE
########################################################

index_path = search.make_index(signatures, bug_dict, context_dict)
print(f"Index created at {index_path}")

results = search.search(10, test_info, buggy_sig, index_path, class_name=class_name)
print(f"Query: {bm25_utils.build_query(test_info, buggy_sig, class_name=class_name)}")
print(f"Results ({len(results)}): {results}")


