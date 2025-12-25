from abc import ABC, abstractmethod
from typing import Tuple
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
        For every unique buggy node (method/class), return ONE patch for the entire buggy node in markdown format, enclosed in the following syntax:
        ```java

        ```
        IMPORTANT: If multiple bug locations are within the same method/class node, provide only ONE patch for that entire node (not one per bug location).
        The number of markdown code blocks should equal the number of unique buggy nodes, not the number of bug locations.
        Do not use markdown format for anything that is not a patch. Only use markdown format for the patches.
        Additionally, briefly explain your reasoning for the patch.
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
    
    def format_bugs_grouped_by_node(self, bugs_in_file, java_file_path: str, code: bytes, start_number: int = 1) -> Tuple[str, int]:
        """
        Format bugs grouped by unique buggy nodes. Returns (formatted_string, next_bug_number).
        Also stores unique node locations in InfoDict to avoid recomputing later.
        
        Args:
            bugs_in_file: List of (bug_location, bug_code, buggy_node_info) tuples
            java_file_path: Path to the Java file
            code: File contents as bytes
            start_number: Starting bug number
            
        Returns:
            Tuple of (formatted_string, next_bug_number)
        """
        result = ''
        node_number = 1
        bug_number = start_number  # Track bug number separately, incrementing across all nodes
        
        # Group bugs by unique buggy node
        unique_nodes = {}  # (start, end) -> list of (bug_location, bug_code, buggy_node_info)
        for bug_in_file in bugs_in_file:
            bug_location, bug_code, buggy_node_info = bug_in_file
            if buggy_node_info is None:
                continue
            buggy_node_location, buggy_node = buggy_node_info
            if buggy_node_location not in unique_nodes:
                unique_nodes[buggy_node_location] = []
            unique_nodes[buggy_node_location].append(bug_in_file)
        
        # Store unique node locations in InfoDict for later use in apply_all_patches
        # This avoids calling retrieve_buggy_lines_and_node again (which is slow)
        # Structure: List[List[Tuple[int, int]]] - one list per file, each containing sorted node locations
        # Initialize the list if this is the first file being processed
        if "unique node locations per file" not in self.information.info_dict:
            self.information.info_dict["unique node locations per file"] = []
        
        # Get sorted unique node locations for this file and append to the list
        unique_node_locations = sorted(unique_nodes.keys())
        self.information.info_dict["unique node locations per file"].append(unique_node_locations)
        
        # Format each unique node (showing all bug locations within it)
        for buggy_node_location in sorted(unique_nodes.keys()):
            bugs_in_node = unique_nodes[buggy_node_location]
            
            # Use the first bug's node info for formatting (they all have the same node)
            first_bug = bugs_in_node[0]
            bug_location, bug_code, buggy_node_info = first_bug
            buggy_node_location, buggy_node = buggy_node_info
            
            # Format the node info
            buggy_node_text = r_utils.get_node_text(buggy_node, code)
            
            # Show the buggy node first
            result += f'{"="*60}\n'
            result += f'Buggy Node #{node_number}:\n'
            result += f'{"="*60}\n'
            result += f'File path: {java_file_path}\n'
            result += f'Buggy node line number(s): {buggy_node_location}\n'
            result += f'\nBuggy node:\n{buggy_node_text}\n'
            
            # Then show all bug locations within this node
            result += f'\nBug locations within this node:\n'
            if len(bugs_in_node) > 1:
                result += f'Note: This node contains {len(bugs_in_node)} bug locations. Provide ONE patch for the entire node.\n\n'
            
            # Number bugs sequentially across all nodes
            for bug_loc, bug_code, _ in bugs_in_node:
                result += f'Bug #{bug_number}:\n'
                result += f'  Bug line number(s): {bug_loc}\n'
                result += f'  Bug lines: {bug_code}\n'
                bug_number += 1
            
            node_number += 1
            result += '\n'
        
        return result, bug_number
    

    def save_patch(self, response: str) -> dict[str, str]:
        """
        Save patches to files and return mapping of modified_source_name -> patch_file_path.
        
        Args:
            response: The agent's response containing markdown code blocks
            
        Returns:
            dict[str, str]: Mapping from modified_source_name to patch_file_path
        """
        bug_files_and_locations = self.information.get_info("bug files and locations")
        unique_node_locations_per_file = self.information.get_info("unique node locations per file")
        patch_mapping = p_utils.apply_all_patches(bug_files_and_locations, response, self.get_agent_role(), unique_node_locations_per_file)
        return patch_mapping

    @abstractmethod
    def format_context(self) -> str:
        """Abstract method - each agent must implement its own context formatting"""
        pass

    @abstractmethod
    def get_agent_role(self) -> str:
        """Abstract method - each agent must implement its own agent role"""
        pass
