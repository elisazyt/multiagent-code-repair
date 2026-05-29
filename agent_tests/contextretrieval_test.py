import os
import sys

# Try to load environment variables from .env file (optional)
try:
    from dotenv import load_dotenv
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)  # Go up one level to revised_multiagent
    env_path = os.path.join(parent_dir, '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        print(f"Warning: .env file not found at {env_path}")
except ImportError:
    # dotenv not available, continue without it
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)

# Add root directory to path for imports
sys.path.insert(0, parent_dir)

from context_retrieval.joern_session import JoernSession
import context_retrieval.isolate_bug as ib

if __name__ == "__main__":

    # Test Chart15
    java_file_path = os.path.join(parent_dir, "ALL_TESTS", "chart15.java")
    joern_executable = os.getenv('JOERN_EXECUTABLE')
    joern_directory = os.getenv('JOERN_DIRECTORY')
    joern_session = JoernSession(java_file_path, joern_executable, joern_directory)

    checkout_dir = os.getenv('CHECKOUT_DIR')
    joern_github_dir = os.getenv('JOERN_GITHUB_DIR')
    joern_session.create_cpg_from_defects4j("Chart", "15", checkout_dir, joern_github_dir)
    
    joern_session.load_cpg("Chart15")
    
    # Extract class name using tree-sitter
    bug_location = (1378, 1380)
    class_name = ib.extract_class_name_from_file(java_file_path, bug_location)
    print(f"Extracted class name: {class_name}")
    
    print("="*100)
    print("Testing get_function_callers:")
    callers = joern_session.get_function_callers(java_file_path, bug_location, class_name)
    print(f"Callers: {callers}")
    print("="*100)
    
    print("Testing get_callees_in_line_range:")
    callees = joern_session.get_callees_in_line_range(java_file_path, bug_location, class_name)
    print(f"Callees: {callees}")
    print("="*100)

