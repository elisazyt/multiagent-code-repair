import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)  # Go up one level to revised_multiagent
env_path = os.path.join(parent_dir, '.env')
load_dotenv(env_path)

# Add root directory to path for imports
sys.path.insert(0, parent_dir)

from context_retrieval.joern_callgraph import JoernSession

if __name__ == "__main__":
    java_file_path = "ALL_TESTS/chart19.java"
    joern_executable = os.getenv('JOERN_EXECUTABLE')
    joern_directory = os.getenv('JOERN_DIRECTORY')
    joern_session = JoernSession(java_file_path, joern_executable, joern_directory)

    checkout_dir = os.getenv('CHECKOUT_DIR')
    joern_github_dir = os.getenv('JOERN_GITHUB_DIR')
    joern_session.create_cpg_from_defects4j("Chart", "19", checkout_dir, joern_github_dir)
    
    joern_session.load_cpg("Chart19")
    print(joern_session.get_functions_in_buggy_class((698, 699)))
    print("="*100)
    print(joern_session.get_buggy_variable_type("axis", (698, 699)))

