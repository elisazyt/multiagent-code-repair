import os
import sys
from dotenv import load_dotenv

# Add autogen_agents to path to import InfoDict and cr_functions
# File is at: agent_tests/unixcoder_test.py, need to go up one level to autogen_agents/
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
autogen_agents_path = os.path.join(parent_dir, 'autogen_agents')
if autogen_agents_path not in sys.path:
    sys.path.append(autogen_agents_path)
from info_dict import InfoDict, ContextDict
import cr_functions

# Load environment variables from .env file
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
info_dict = InfoDict()
info_dict.add_bug_info(
    project_name="Chart",
    bug_id="2",
    bug_locations=[(chart2_path, [(756, 757)])],
    working_directory=working_directory
)
# Create ContextDict from InfoDict and add BM25/UniXcoder RAG configs
context_dict = ContextDict(info_dict=info_dict)
context_dict.add_bm25_rag_config(
    k_signatures=10,  # BM25 stage: get top 10 signatures
    jsonl_dir=jsonl_dir,
    index_dir=index_dir,
    k_code_snippets=3,  # UniXcoder stage: get top 3 code snippets
    window_size=20,
    batch_size=10
)

# Add Joern configuration (needed for top_k_code_snippets)
joern_executable = os.getenv('JOERN_EXECUTABLE')
joern_directory = os.getenv('JOERN_DIRECTORY')
joern_github_dir = os.getenv('JOERN_GITHUB_DIR')
if joern_executable and joern_directory:
    info_dict.add_joern_config(joern_executable, joern_directory)

# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))

# Import JoernSession to create CPG if needed
from joern_session import JoernSession
import retrieval_utils as utils

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
    print(f"✓ CPG already exists at {cpg_path}")

# Load the CPG for querying
if not joern_session.load_cpg(cpg_project_name):
    print("ERROR: Failed to load CPG. Cannot continue.")
    exit(1)

try:
    import isolate_bug as ib
    bug_location = (756, 757)
    class_name = ib.extract_class_name_from_file(chart2_path, bug_location)
except ValueError as e:
    # If class name extraction fails, log warning but continue
    print(f"Warning: Could not extract class name: {e}")
    class_name = None

print(f"Class name: {class_name}")

########################################################
# ACTUAL USAGE OF TOP_K_CODE_SNIPPETS
########################################################

start_line, end_line = 756, 757

print(f"\nCalling top_k_code_snippets...")

# Print the query (bug location code)
query_code = utils.retrieve_code_by_line_number(chart2_path, (start_line, end_line))
print("\n" + "="*100)
print("QUERY (Bug Location Code):")
print("="*100)
print(query_code)
print("="*100)

results = cr_functions.top_k_code_snippets(
    java_file_path=chart2_path,
    start_line=start_line,
    end_line=end_line,
    class_name=class_name,
    info_dict=info_dict,
    context_dict=context_dict
)

# Handle both string (error) and list (success) return types
if isinstance(results, str):
    print(f"ERROR: {results}")
elif isinstance(results, list) and len(results) >= 3:
    print("\n" + "="*100)
    print("TOP 3 RESULTS:")
    print("="*100)
    print(results[0])
    print("="*100)
    print(results[1])
    print("="*100)
    print(results[2])
elif isinstance(results, list):
    print("\n" + "="*100)
    print(f"RESULTS (Found only {len(results)} results, expected at least 3):")
    print("="*100)
    for i, snippet in enumerate(results, 1):
        print(f"\n{'='*100}")
        print(f"Result {i}:")
        print(snippet)
else:
    print(f"Unexpected return type: {type(results)}")
    print(f"Value: {results}")

