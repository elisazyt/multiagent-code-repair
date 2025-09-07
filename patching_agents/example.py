import info_dict
from context_agent import ContextAgent
from basic_agent import BasicAgent
from api_agent import ApiAgent
import message_history
import os

SYSTEM_DESCRIPTION = """
The task is to generate a patch for the buggy Java code.

Do not assume any methods exist unless they are explicitly called or defined.
If the patch calls a new method, it should be explicitly defined and fully implemented,
without any placeholder logic.

All buggy locations should be fixed. Refactoring and commenting should not be considered fixes.

The user cannot modify your code, so do not suggest incomplete code which requires others to modify.
Suggest the full code instead of partial code or code changes.

Return the patch as a .java file.
"""

BASIC_PROMPT = "Carry out the given task."

API_PROMPT = f"""
You are an agent that focuses on retrieving and using the correct APIs to carry out the task, if APIs are needed.
You should use the retrieved APIs instead of creating your own functions whenever possible."""


buggy_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'test_programs', 'chart15.java')

information = info_dict.InfoDict()
msg_history = message_history.MessageHistory('../message_histories')
msg_history.add_system_message(SYSTEM_DESCRIPTION)
information.create_info_dict("api", API_PROMPT, [(buggy_file_path, [(1379, 1379), (2051, 2052)])], msg_history)

context_retriever = ContextAgent(information)

# basicagent = BasicAgent(information)
# contextagent = ContextAgent(information)
apiagent = ApiAgent(information)
# result, msg_history = basicagent.run(BASIC_PROMPT)
result, curr_msg_history = apiagent.run()
msg_history.add_message_history(curr_msg_history)
print(msg_history)