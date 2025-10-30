import info_dict
from basic_agent import BasicAgent
from api_agent import ApiAgent
from testing_agent import TestingAgent
import patch_utils as p_utils
import message_history
import os
import sys

# Add parent directory to path to import test_suites
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_suites import test_suites as ts

# TODO: figure out the order in which the prompt and message history are provided.
# TODO: find a way to make the system description more prominent, i.e. make it clear that it is the system task

SYSTEM_DESCRIPTION = """
TASK:
Generate a patch for the buggy Java code.

Do not assume any methods exist unless they are explicitly called or defined.
If the patch calls a new method, it should be explicitly defined and fully implemented,
without any placeholder logic.

All buggy locations should be fixed. Refactoring and commenting should not be considered fixes.

The user cannot modify your code, so do not suggest incomplete code which requires others to modify.
Suggest the full code instead of partial code or code changes.

RETURN FORMAT:
For every single bug location, return the patch in markdown format, with the following syntax:
```java
[patch]
```
Do not use markdown format for anything that is not a patch. Only use markdown format for the patches.
The number of markdown blocks should equal the number of bug locations.
The patch should contain the full code for the bug location.
"""

BASIC_PROMPT = "Carry out the given task given by the system description."

API_PROMPT = f"""
You are an agent that retrieves and uses any necessary APIs to carry out the task given by the system
description. Some bug fixes don't require API usage, so you should first analyze the context and determine
if new APIs are needed.

Whenever possible, use the retrieved APIs instead of creating your own functions."""


buggy_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ALL_TESTS', 'chart15.java')

# Create shared message history
msg_history = message_history.MessageHistory('message_histories', 'chart15')

# Delete existing file to start fresh
if os.path.exists(msg_history.history_file):
    os.remove(msg_history.history_file)

msg_history.add_system_message(SYSTEM_DESCRIPTION)

# Create a single shared info dict with message history and bug info
information = info_dict.InfoDict()
information.add_message_history(msg_history)

# Add bug info
bug_locations = [(buggy_file_path, [(1379, 1379), (2051, 2052)])]
# TODO: set working directory: working_directory = 
information.add_bug_info("Chart", "15", bug_locations, working_directory)

# Create agents after info is set up
apiagent = ApiAgent(information, "api", API_PROMPT)
basicagent = BasicAgent(information, "basic", BASIC_PROMPT)
testingagent = TestingAgent(information)

# Run agents in sequence
# mapping = apiagent.run()
# No need to add_message_history since curr_msg_history is the same as msg_history

mapping = basicagent.run()
# No need to add_message_history since curr_msg_history is the same as msg_history
print(f'''
########################################################
finished running basic agent with mapping: {mapping}
########################################################
''')


# Use testing agent to run tests
test_result = testingagent.run(mapping)
print(f'''
########################################################
finished running testing agent with test results: {test_result}
########################################################
''')