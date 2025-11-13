from abc import ABC, abstractmethod
from gpt_client import GPTClient
from message_history import MessageHistory
from info_dict import InfoDict
import sys
import os
import patch_utils as p_utils

# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
import retrieval_utils as r_utils

class PatchingAgent(ABC):
    def __init__(self, information: InfoDict, agent_role: str, agent_task: str):
        self.information = information
        self.gpt_client = GPTClient()
        self.gpt_client.initialize_agent()
        self.msg_history = self.information.get_info("message history")
        self.agent_role = agent_role
        self.agent_task = agent_task

    def run(self) -> dict[str, str]:
        # Get base prompt (context only, no message history)
        base_prompt = self.get_base_prompt()
        
        # Create full prompt for AI (base + message history)
        # Remove placeholder from base_prompt and add actual message history
        full_prompt = base_prompt.replace("\n\nFor reference, here is the past message history: {message_history}", "")
        if any(msg["role"] not in ["system"] for msg in self.msg_history.messages):
            history_text = self.msg_history.format_history()
            full_prompt += f"\n\nFor reference, here is the past message history:\n{history_text}"
        else:
            full_prompt += "\n\nFor reference, here is the past message history:\n(This is the first message in the conversation thread, no previous message history is available. Proceed with your task, ignoring this message.)"
        
        # Store only the base prompt (no message history) to avoid redundancy
        # If no message history, replace placeholder with appropriate text
        if not any(msg["role"] not in ["system"] for msg in self.msg_history.messages):
            base_prompt = base_prompt.replace("{message_history}", "(This is the first message in the conversation thread, no previous message history is available. Proceed with your task, ignoring this message.)")
        self.msg_history.add_prompt(base_prompt)
        
        # Send full prompt to AI (with message history)
        response = self.gpt_client.send_prompt(full_prompt)
        result_text = self.gpt_client.receive_response(response)
        
        # Save patches and get mapping of modified_source_name -> patch_file_path
        print(f"--------------------------------")
        print(f"result_text: {result_text}")
        print(f"--------------------------------")
        patch_mapping = self.save_patch(result_text)
        
        self.msg_history.add_agent(self.agent_role, result_text)

        return patch_mapping

    
    def regenerate_patch(self) -> dict[str, str]:
        """
        Regenerate the patch for the given bug.
        """
        # Get base prompt (no message history)
        base_prompt = self.get_regeneration_prompt()
        
        # Create full prompt for AI (base + message history)
        full_prompt = base_prompt.replace("\n\nFor reference, here is the past message history: {message_history}", "")
        history_text = self.msg_history.format_history()
        full_prompt += f"\n\nFor reference, here is the past message history:\n{history_text}"
        
        # Store only the base prompt (no message history) to avoid redundancy
        # Keep {message_history} placeholder as-is in stored version
        self.msg_history.add_prompt(base_prompt)
        
        # Send full prompt to AI (with message history)
        response = self.gpt_client.send_prompt(full_prompt)
        result_text = self.gpt_client.receive_response(response)
        
        # Save patches and get mapping
        patch_mapping = self.save_patch(result_text)
        
        # Add agent response to history
        self.msg_history.add_agent(self.agent_role, result_text)
        
        return patch_mapping
    
    
    def get_regeneration_prompt(self) -> str:
        """
        Get the base prompt for patch regeneration (without message history).
        """
        final_prompt = """Your task is to patch a bug in Java. Below is the complete message history from previous attempts to fix this bug, including the original bug context, your previous patch attempt, and the failing test information.

Review the message history and regenerate the patch. The previous patch failed the tests shown in the message history. Correct the patch so that it passes all failing tests.

All instructions and context are provided in the message history below. Follow the same format requirements as specified in the system instructions.

For reference, here is the past message history: {message_history}

As a reminder, return the patch in markdown format for each bug location, with the following syntax:
```java
[patch]
```
Do not use markdown format for anything that is not a patch. Only use markdown format for the patches.
The number of markdown blocks should equal the number of bug locations.
The patch should contain the full code for the bug location.
"""
        return final_prompt


    def get_base_prompt(self) -> str:
        final_prompt = f"""The task of the agent is: {self.agent_task}

You are given the following context information about the bug:\n"""
        final_prompt += self.format_context()
        
        # Add message history placeholder to base prompt (for storage consistency)
        final_prompt += "\n\nFor reference, here is the past message history: {message_history}"

        # Add reminder about markdown format
        final_prompt += f'''\n\nREMINDER:
        For every single bug location, return the patch for the entire buggy node in markdown format, with the following syntax:
        ```java
        [patch]
        ```
        Do not use markdown format for anything that is not a patch. Only use markdown format for the patches.
        '''
        
        return final_prompt
    

    def format_basic_bug_info(self, bug_in_file, bug_number: int, java_file_path: str, code: bytes) -> str:
        """Format basic bug information that's common across all agents"""
        bug_location, bug_code, buggy_node_info = bug_in_file
        buggy_node_location, buggy_node = buggy_node_info
        
        buggy_node = r_utils.get_node_text(buggy_node, code)
        
        result = f'Bug #{bug_number}:\n'
        result += f'File path: {java_file_path}\n'
        result += f'Bug line number(s): {bug_location}\n'
        result += f'Bug lines: {bug_code}'
        result += f'Buggy node line number(s): {buggy_node_location}\n'
        result += f'Buggy node: {buggy_node}\n'
        
        return result
    

    def save_patch(self, response: str) -> dict[str, str]:
        """
        Save patches to files and return mapping of modified_source_name -> patch_file_path.
        
        Args:
            response: The agent's response containing markdown code blocks
            
        Returns:
            dict[str, str]: Mapping from modified_source_name to patch_file_path
        """
        buggy_node_locations = self.information.get_info("bug files and locations")
        patch_mapping = p_utils.apply_all_patches(buggy_node_locations, response, self.get_agent_role())
        return patch_mapping

    @abstractmethod
    def format_context(self) -> str:
        """Abstract method - each agent must implement its own context formatting"""
        pass

    @abstractmethod
    def get_agent_role(self) -> str:
        """Abstract method - each agent must implement its own agent role"""
        pass
