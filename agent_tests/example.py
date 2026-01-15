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

# TODO: once context retrieval agent is added, check out defects4j project before running anything else
# since both the context retrieval agent and testing agent need it

buggy_file_path = os.path.join(parent_dir, 'ALL_TESTS', 'closure8.java')

# Create shared message history
message_histories_dir = os.path.join(parent_dir, 'message_histories')
msg_history = message_history.MessageHistory(message_histories_dir, 'closure8')

# Delete existing file to start fresh
if os.path.exists(msg_history.history_file):
    os.remove(msg_history.history_file)

msg_history.add_system_message(SYSTEM_DESCRIPTION)

# Create a single shared info dict with message history and bug info
information = info_dict.InfoDict()
information.add_message_history(msg_history)

# Add bug info
bug_locations = [(buggy_file_path, [(202, 205)])]
project_name = "Closure"
bug_id = "8"
checkout_dir = os.getenv('CHECKOUT_DIR')
working_directory = os.path.join(checkout_dir, f"{project_name.lower()}{bug_id}")
information.add_bug_info(project_name, bug_id, bug_locations, working_directory)



####################################################################
# AGENTS/FUNCTIONALITIES THAT ARE CURRENTLY WORKING:
####################################################################

# Create agents after info is set up
basicagent = BasicAgent(information, "basic", BASIC_PROMPT)
apiagent = ApiAgent(information, "api", API_PROMPT)
testingagent = TestingAgent(information)

# Run agents in sequence
# mapping = apiagent.run()
# No need to add_message_history since curr_msg_history is the same as msg_history

mapping = basicagent.run()
# No need to add_message_history since curr_msg_history is the same as msg_history

print(f'Finished running basic agent with mapping: {mapping}')


# Use testing agent to run tests
test_result = testingagent.run(mapping)
if test_result is not None:
    print('One or more test suites failed, regenerating patch')
    
    regenerated_mapping = apiagent.regenerate_patch()
    print('Finished regenerating patch, testing it again.')
    testingagent.run(regenerated_mapping)
else:
    print("Patch passed the test suite and can be stored as a candidate.")
    # TODO: store the patch as a candidate