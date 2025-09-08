from abc import ABC, abstractmethod
from gpt_client import GPTClient
from message_history import MessageHistory
from info_dict import InfoDict
import sys
import os

# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
import retrieval_utils as utils

class AbstractAgent(ABC):
    def __init__(self, information: InfoDict):
        self.information = information
        self.gpt_client = GPTClient()
        self.gpt_client.initialize_agent()
        self.msg_history = self.information.get_info("message history")

    def run(self) -> tuple[str, MessageHistory]:
        # Get base prompt (context only, no message history)
        base_prompt = self.get_base_prompt()
        
        # Create full prompt for AI (base + message history)
        # Remove placeholder from base_prompt and add actual message history
        full_prompt = base_prompt.replace("\n\nFor reference, here is the past message history: {message_history}", "")
        if self.msg_history.messages:
            history_text = self.msg_history.format_history()
            full_prompt += f"\n\nFor reference, here is the past message history:\n{history_text}"
        else:
            full_prompt += "\n\nFor reference, here is the past message history:\n(This is the first message in the conversation thread, no previous message history is available.)"
        
        # Store only the base prompt (no message history) to avoid redundancy
        self.msg_history.add_prompt(self.information.get_info("agent role"), base_prompt)
        
        # Send full prompt to AI (with message history)
        result_text = self.gpt_client.receive_response(self.gpt_client.send_prompt(full_prompt))
        self.msg_history.add_agent(self.information.get_info("agent role"), result_text)
        return result_text, self.msg_history

    def get_base_prompt(self) -> str:
        agent_task = self.information.get_info("agent task")
        final_prompt = f"""The task of the agent is: {agent_task}

You are given the following context information about the bug:\n"""
        final_prompt += self.format_context()
        
        # Add message history placeholder to base prompt (for storage consistency)
        final_prompt += "\n\nFor reference, here is the past message history: {message_history}"
        
        return final_prompt
    
    def format_basic_bug_info(self, bug_in_file, bug_number: int, java_file_path: str, code: bytes) -> str:
        """Format basic bug information that's common across all agents"""
        bug_location, bug_code, buggy_node_info = bug_in_file
        buggy_node_location, buggy_node = buggy_node_info
        
        buggy_node = utils.get_node_text(buggy_node, code)
        
        result = f'Bug #{bug_number}:\n'
        result += f'File path: {java_file_path}\n'
        result += f'Bug line number(s): {bug_location}\n'
        result += f'Bug lines: {bug_code}'
        result += f'Buggy node line number(s): {buggy_node_location}\n'
        result += f'Buggy node: {buggy_node}\n'
        
        return result
    
    @abstractmethod
    def format_context(self) -> str:
        """Abstract method - each agent must implement its own context formatting"""
        pass
