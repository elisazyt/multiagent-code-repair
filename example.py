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
from context_agent import ContextAgent
from testing_agent import TestingAgent
import patch_utils as p_utils
import message_history

# Import from root directory
from prompt_templates import SYSTEM_DESCRIPTION, API_PROMPT, BASIC_PROMPT, CONTEXT_PROMPT
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



####################################################################
# AGENTS/FUNCTIONALITIES THAT ARE CURRENTLY WORKING:
####################################################################

# Create agents after info is set up
basicagent = BasicAgent(information, "basic", BASIC_PROMPT)
apiagent = ApiAgent(information, "api", API_PROMPT)
testingagent = TestingAgent(information)

# Run agents in sequence
mapping = apiagent.run()
# No need to add_message_history since curr_msg_history is the same as msg_history

# mapping = basicagent.run()
# No need to add_message_history since curr_msg_history is the same as msg_history

print('Finished running api agent with mapping: {mapping}')


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



####################################################################
# AGENTS/FUNCTIONALITIES THAT ARE STILL BEING IMPLEMENTED:
####################################################################

# Add Joern configuration
joern_executable = '/usr/local/bin/joern'  # Path to Joern executable
joern_directory = ''  # Path to Joern directory
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
print("\nResult:")
print(result)