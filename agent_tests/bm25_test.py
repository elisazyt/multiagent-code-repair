import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Add autogen_agents to path
autogen_agents_path = os.path.join(parent_dir, 'autogen_agents')
if autogen_agents_path not in sys.path:
    sys.path.append(autogen_agents_path)

from info_dict import InfoDict
import cr_functions
import isolate_bug as ib

# Get project root directory
project_root = parent_dir
working_directory = os.path.join(project_root, "defects4j_checkout")

# Load environment variables for Joern configuration
joern_executable = os.getenv('JOERN_EXECUTABLE')
joern_directory = os.getenv('JOERN_DIRECTORY')

if not joern_executable or not joern_directory:
    print("ERROR: JOERN_EXECUTABLE and JOERN_DIRECTORY must be set in .env file")
    exit(1)

# Setup InfoDict for Chart 2
chart2_path = os.path.join(project_root, "ALL_TESTS", "chart2.java")
information = InfoDict()
information.add_bug_info(
    project_name="Chart",
    bug_id="2",
    bug_locations=[(chart2_path, [(756, 757)])],
    working_directory=working_directory
)
information.add_joern_config(joern_executable, joern_directory)

# Add BM25 RAG configuration
jsonl_dir = os.path.join(project_root, "bm25_output")
index_dir = os.path.join(project_root, "bm25_output")
information.add_bm25_rag_config(jsonl_dir, index_dir)

# Extract class name from bug location
bug_location = (756, 757)
try:
    class_name = ib.extract_class_name_from_file(chart2_path, bug_location)
    if not class_name:
        print("WARNING: Could not extract class name, using None")
        class_name = None
except ValueError as e:
    print(f"Warning: Could not extract class name: {e}")
    class_name = None

print(f"Class name: {class_name}")
print(f"Java file: {chart2_path}")
print(f"Bug location: {bug_location}")
print()

# Test top_k_class_signatures
print("=" * 60)
print("Testing top_k_class_signatures")
print("=" * 60)

start_line, end_line = 756, 757
full_signatures, results_str = cr_functions.top_k_class_signatures(
    k=10,
    java_file_path=chart2_path,
    start_line=start_line,
    end_line=end_line,
    class_name=class_name,
    information=information
)

print("========================================================")
print(f"Full signatures: {full_signatures}")
print("========================================================")
print(f"Results string: {results_str}")
print("========================================================")

