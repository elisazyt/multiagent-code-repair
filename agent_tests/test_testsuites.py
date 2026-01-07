import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)  # Go up one level to revised_multiagent
env_path = os.path.join(parent_dir, '.env')
load_dotenv(env_path)

# Add patching_agents directory to path
patching_agents_path = os.path.join(parent_dir, 'patching_agents')
sys.path.insert(0, patching_agents_path)

# Add root directory to path for root-level imports
sys.path.insert(0, parent_dir)

# Import from patching_agents
import info_dict
from testing_agent import TestingAgent
import message_history


def test_patch_file(patch_file_path: str, project_name: str, bug_id: str, working_directory: str, modified_source_name: str = None):
    """
    Test a patch file by running the Defects4J test suite using TestingAgent.
    
    Args:
        patch_file_path: Path to the patched Java file
        project_name: Project name (e.g., 'Chart', 'Lang')
        bug_id: Bug ID (e.g., '2', '12')
        working_directory: Path to Defects4J working directory
        modified_source_name: Optional. If not provided, will try to extract from the patch file
    """
    # If modified_source_name not provided, try to extract it from the patch file
    if not modified_source_name:
        info = info_dict.InfoDict()
        modified_source_name = info.get_modified_source(patch_file_path)
        if not modified_source_name:
            print(f"Error: Could not extract modified source name from {patch_file_path}")
            print("Please provide modified_source_name explicitly.")
            return
    
    print(f"Testing patch file: {patch_file_path}")
    print(f"Project: {project_name}, Bug ID: {bug_id}")
    print(f"Modified source: {modified_source_name}")
    print(f"Working directory: {working_directory}")
    print("-" * 60)
    
    # Create InfoDict with project info (TestingAgent needs this)
    information = info_dict.InfoDict()
    
    # Create a dummy message history (TestingAgent requires it, but we won't use it)
    message_histories_dir = os.path.join(parent_dir, 'message_histories')
    msg_history = message_history.MessageHistory(message_histories_dir, f'{project_name.lower()}{bug_id}_test')
    information.add_message_history(msg_history)
    
    # Add bug info (TestingAgent needs project name, bug id, and working directory)
    information.add_bug_info(project_name, bug_id, [], working_directory)
    
    # Create TestingAgent
    testing_agent = TestingAgent(information)
    
    # Create mapping: modified_source_name -> patch_file_path
    mapping = {modified_source_name: patch_file_path}
    
    # Run the test suite using TestingAgent
    print("\nRunning test suite...")
    result = testing_agent.run(mapping)
    
    # Process and display results
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)
    
    if result is None:
        print("All tests passed!")
    else:
        print("Tests failed:")
        print(result)
    
    print("=" * 60)


if __name__ == "__main__":
    # Example usage - modify these values as needed
    patch_file_path = os.path.join(parent_dir, 'patches', 'chart2_patched_basic.java')
    project_name = "Chart"
    bug_id = "2"
    checkout_dir = os.getenv('CHECKOUT_DIR')
    working_directory = os.path.join(checkout_dir, f"{project_name.lower()}{bug_id}")
    modified_source_name = None  # Will be extracted from file if None
    
    test_patch_file(patch_file_path, project_name, bug_id, working_directory, modified_source_name)

