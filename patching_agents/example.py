import info_dict
from context_agent import ContextAgent
from basic_agent import BasicAgent
from api_agent import ApiAgent
import message_history
import os

# TODO: figure out the order in which the prompt and message history are provided.
# TODO: find a way to make the system description more prominent, i.e. make it clear that it is the system task

SYSTEM_DESCRIPTION = """
The task is to generate a patch for the buggy Java code.

Do not assume any methods exist unless they are explicitly called or defined.
If the patch calls a new method, it should be explicitly defined and fully implemented,
without any placeholder logic.

All buggy locations should be fixed. Refactoring and commenting should not be considered fixes.

The user cannot modify your code, so do not suggest incomplete code which requires others to modify.
Suggest the full code instead of partial code or code changes.
"""

BASIC_PROMPT = "Carry out the given task."

API_PROMPT = f"""
You are an agent that retrieves and uses the correct APIs to carry out the task, if APIs are needed.
You should use the retrieved APIs instead of creating your own functions whenever possible."""


buggy_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'test_programs', 'chart15.java')

# Create shared message history
msg_history = message_history.MessageHistory('message_histories', 'chart15')

# Delete existing file to start fresh
if os.path.exists(msg_history.history_file):
    os.remove(msg_history.history_file)

msg_history.add_system_message(SYSTEM_DESCRIPTION)

# Create info dicts with shared message history
api_information = info_dict.InfoDict()
basic_information = info_dict.InfoDict()

api_information.create_info_dict("api", API_PROMPT, [(buggy_file_path, [(1379, 1379), (2051, 2052)])], msg_history)
basic_information.create_info_dict("basic", BASIC_PROMPT, [(buggy_file_path, [(1379, 1379), (2051, 2052)])], msg_history)

# Create agents after info dicts are set up
apiagent = ApiAgent(api_information)
basicagent = BasicAgent(basic_information)

# Run agents in sequence
result, curr_msg_history = apiagent.run()
# No need to add_message_history since curr_msg_history is the same as msg_history

result, curr_msg_history = basicagent.run()
# No need to add_message_history since curr_msg_history is the same as msg_history

print(msg_history)