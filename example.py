import os
import sys

# Add patching_agents directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
patching_agents_path = os.path.join(current_dir, 'patching_agents')
sys.path.insert(0, patching_agents_path)

# Import from patching_agents
import info_dict
from basic_agent import BasicAgent
from api_agent import ApiAgent
from testing_agent import TestingAgent
import patch_utils as p_utils
import message_history

# Import from root directory
from prompt_templates import SYSTEM_DESCRIPTION, API_PROMPT, BASIC_PROMPT
from test_suites import test_suites as ts

# TODO: figure out the order in which the prompt and message history are provided.
# TODO: find a way to make the system description more prominent, i.e. make it clear that it is the system task


buggy_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ALL_TESTS', 'lang12.java')

# Create shared message history
msg_history = message_history.MessageHistory('message_histories', 'lang12')

# Delete existing file to start fresh
if os.path.exists(msg_history.history_file):
    os.remove(msg_history.history_file)

msg_history.add_system_message(SYSTEM_DESCRIPTION)

# Create a single shared info dict with message history and bug info
information = info_dict.InfoDict()
information.add_message_history(msg_history)

# Add bug info
bug_locations = [(buggy_file_path, [(231, 237)])]
working_directory = '' # TODO: set this to the working directory where the project will be checked out and tested
information.add_bug_info("Lang", "12", bug_locations, working_directory)

# Create agents after info is set up
apiagent = ApiAgent(information, "api", API_PROMPT)
basicagent = BasicAgent(information, "basic", BASIC_PROMPT)
testingagent = TestingAgent(information)

# Run agents in sequence
mapping = apiagent.run()
# No need to add_message_history since curr_msg_history is the same as msg_history

# mapping = basicagent.run()
# No need to add_message_history since curr_msg_history is the same as msg_history

print(f'''
########################################################
finished running api agent with mapping: {mapping}
########################################################
''')


# Use testing agent to run tests
test_result = testingagent.run(mapping)
if test_result is not None:
    print(f'''
    ########################################################
    Tests failed. Regenerating patch...
    ########################################################
    ''')
    
    regenerated_mapping = apiagent.regenerate_patch()
    print(f'''
    ########################################################
    Finished regenerating patch with mapping: {regenerated_mapping}
    ########################################################
    ''')
    testingagent.run(regenerated_mapping)
else:
    print("Patch passed the test suite and can be stored as a candidate.")
    # TODO: store the patch as a candidate