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
from basic_agent import BasicAgent
from api_agent import ApiAgent
from context_agent import ContextAgent
from testing_agent import TestingAgent
import patch_utils as p_utils
import message_history

# Import from root directory
from prompt_templates import SYSTEM_DESCRIPTION, API_PROMPT, BASIC_PROMPT, CONTEXT_PROMPT
from test_suites import test_suites as ts

# TODO: figure out the order in which the prompt and message history are provided.
# TODO: find a way to make the system description more prominent, i.e. make it clear that it is the system task


buggy_file_path = os.path.join(parent_dir, 'ALL_TESTS', 'chart2.java')

message_histories_dir = os.path.join(parent_dir, 'message_histories')
msg_history = message_history.MessageHistory(message_histories_dir, 'chart2')

# Create a single shared info dict with message history and bug info
information = info_dict.InfoDict()
information.add_message_history(msg_history)

# Add bug info
bug_locations = [(buggy_file_path, [(752, 764), (1239, 1251)])]
project_name = "Chart"
bug_id = "2"
checkout_dir = os.getenv('CHECKOUT_DIR')
working_directory = os.path.join(checkout_dir, f"{project_name.lower()}{bug_id}")
information.add_bug_info(project_name, bug_id, bug_locations, working_directory)

####################################################################
# AGENTS/FUNCTIONALITIES THAT ARE STILL BEING IMPLEMENTED:
####################################################################

# Add Joern configuration
joern_executable = os.getenv('JOERN_EXECUTABLE')
joern_directory = os.getenv('JOERN_DIRECTORY')
information.add_joern_config(joern_executable, joern_directory)

context_agent = ContextAgent(information, "context", CONTEXT_PROMPT)

print(f"\n" + "=" * 60)
print("Step 3: Initializing ContextAgent")
print("=" * 60)

agent_role = "context"
agent_task = "Retrieve context information including call graph analysis"
agent = ContextAgent(information, agent_role, agent_task)
print(f"✓ ContextAgent initialized")

# Step 4: Test format_context
print(f"\n" + "=" * 60)
print("Step 4: Testing format_context()")
print("=" * 60)

print(f"\nCalling format_context()...")
result = agent.format_context()

# Write result to file in message_histories directory
output_file = os.path.join(message_histories_dir, 'chart2_context.txt')
with open(output_file, 'w', encoding='utf-8') as f:
    f.write(result)
print(f"\nResult written to: {output_file}")