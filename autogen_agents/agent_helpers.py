import asyncio
import sys
import os
from typing import Tuple
from autogen_core import AgentId, SingleThreadedAgentRuntime
from autogen_core.models import SystemMessage, UserMessage, AssistantMessage
from autogen_core.model_context import UnboundedChatCompletionContext
from data_classes import PatchingTask, TestingTask, TestingResponse
from info_dict import InfoDict

# Add the context_retrieval directory to the path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'context_retrieval'))
import isolate_bug as ib
import retrieval_utils as r_utils


########################################################
# Helper functions for running one round of patching and testing
########################################################
# For now, run 5 rounds. may need to change later.
async def run_patch_test_loop(patcher_id: str, message: str, admin_agent: AgentId, runtime: SingleThreadedAgentRuntime, num_rounds=2):
    print(f"[{patcher_id}] Loop started!")
    round = 1
    last_test_response = None

    while (round <= num_rounds):
        # Create patching task (initial or regeneration)
        if (round == 1):
            patching_task = PatchingTask(patcher_id=patcher_id, message=message)
        else:
            # Use previous test response to create regeneration prompt
            if last_test_response.success:
                print(f"[{patcher_id}] Test passed! Saving patch as a candidate.")
                # save the patch as a candidate
                break
            else:
                # Reprompt to regenerate the patch
                patching_task = PatchingTask(patcher_id=patcher_id, message=f"Based on the previous messages and failing test information, regenerate the patch.")
        
        # Send single patching task to AdminAgent
        patching_response = await runtime.send_message(patching_task, recipient=admin_agent)
        print(f"[{patcher_id}] Round {round} - Patching result: {patching_response.result}")

        # Test the patch
        testing_task = TestingTask(
            patcher_id=patcher_id,
            mapping=patching_response.mapping
        )
        testing_response = await runtime.send_message(testing_task, recipient=admin_agent)
        
        # Add test result to PatchingAgent's context for future regeneration
        # Import here to avoid circular dependency
        from agents import PatchingAgent
        if patcher_id in PatchingAgent._instances_dict:
            await PatchingAgent._instances_dict[patcher_id].add_test_result(
                testing_response.result, 
                testing_response.success,
                source="testing"  # TestingAgent's key
            )
        
        if testing_response.success:
            print(f"[{patcher_id}] Test passed: {testing_response.result}")
            break
        else:
            last_test_response = testing_response
        
        round += 1
    
    # Return the number of rounds completed
    # If we broke early, round is the correct number. If we completed all rounds, round is num_rounds + 1
    return round if round <= num_rounds else num_rounds


########################################################
# Helper functions for getting and formatting information
########################################################

def get_system_message(information: InfoDict, role_description: str) -> SystemMessage:
        msg = f"""{role_description}

You are given the following context information about the bug:\n"""
        msg += format_bug_info(information)

        # Add reminder about markdown format
        msg += f'''\n\nREMINDER:
        For every unique buggy node (method/class), return ONE patch for the entire buggy node in markdown format, enclosed in the following syntax:
        ```java

        ```
        IMPORTANT: If multiple bug locations are within the same method/class node, provide only ONE patch for that entire node (not one per bug location).
        The number of markdown code blocks should equal the number of unique buggy nodes, not the number of bug locations.
        Do not use markdown format for anything that is not a patch. Only use markdown format for the patches.
        Additionally, briefly explain your reasoning for the patch.
        '''
        
        return SystemMessage(content=msg)

def format_bug_info(information: InfoDict) -> str:
    """Format bare minimum bug information without additional analysis"""
    bug_locations = information.get_info("bug files and locations")
    result = ''
    bug_number = 1  # Track bug number sequentially across all files and nodes

    # Reset stored node locations (will be populated during formatting)
    information.info_dict["unique node locations per file"] = []

    # Iterate through each file
    # Structure: (file_path, modified_source_name, bug_locations_list)
    for buggy_file_info in bug_locations:
        # Use the helper method to format bugs grouped by unique nodes
        # Returns: (formatted_string, next_bug_number)
        formatted_bugs, next_bug_number = format_bugs_grouped_by_node(buggy_file_info, information, bug_number)
        result += formatted_bugs
        bug_number = next_bug_number  # Continue bug numbering across files
        
    return result

def format_bugs_grouped_by_node(buggy_file_info, information: InfoDict, start_number: int = 1) -> Tuple[str, int]:
    """
    Format bugs grouped by unique buggy nodes. Returns (formatted_string, next_bug_number).
    Also stores unique node locations in InfoDict to avoid recomputing later.
    
    Args:
        buggy_file_info: Tuple of (java_file_path, modified_source_name, bug_locations_list)
        information: InfoDict object to store unique node locations
        start_number: Starting bug number
        
    Returns:
        Tuple of (formatted_string, next_bug_number)
    """
    # Extract file info from tuple
    java_file_path, modified_source_name, bug_locations_list = buggy_file_info
    
    # Read file and retrieve bugs
    with open(java_file_path, 'rb') as f:
        code = f.read()
    bugs_in_file = ib.retrieve_buggy_lines_and_node(java_file_path, bug_locations_list)
    
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
    if "unique node locations per file" not in information.info_dict:
        information.info_dict["unique node locations per file"] = []
    
    # Get sorted unique node locations for this file and append to the list
    unique_node_locations = sorted(unique_nodes.keys())
    information.info_dict["unique node locations per file"].append(unique_node_locations)
    
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


########################################################
# Helper functions for logging and printing message threads
########################################################

async def log_message(
    context: UnboundedChatCompletionContext,
    content: str,
    role: str,
    source: str
):
    """
    General utility function to log messages to a conversation context.
    
    Args:
        context: The ChatCompletionContext to add messages to
        content: The message content (string)
        role: Message role - "user" or "assistant"
        source: The source agent's key (e.g., "admin_agent", "basic", "testing")
    """
    # Create the appropriate message type based on role
    if role == "user":
        msg = UserMessage(content=content, source=source)
    elif role == "assistant":
        msg = AssistantMessage(content=content, source=source)
    else:
        # Default to UserMessage
        msg = UserMessage(content=content, source=source)
    
    await context.add_message(msg)


async def print_message_thread(context: UnboundedChatCompletionContext, agent_id: str = "Unknown"):
    """Helper method to print the entire message thread from context"""
    messages = await context.get_messages()
    print(f"\n{'='*80}")
    print(f"Full Message Thread (Agent: {agent_id}):")
    print(f"{'='*80}")
    for i, msg in enumerate(messages, 1):
        if isinstance(msg, SystemMessage):
            print(f"[{i}] System: {msg.content}")
        elif isinstance(msg, UserMessage):
            print(f"[{i}] User (source: {msg.source}): {msg.content}")
        elif isinstance(msg, AssistantMessage):
            print(f"[{i}] Assistant (source: {msg.source}): {msg.content}")
        else:
            print(f"[{i}] {type(msg).__name__}: {msg}")
    print(f"{'='*80}\n")


async def save_message_thread(
    context: UnboundedChatCompletionContext, 
    agent_id: str,
    information: InfoDict
):
    """
    Save the entire message thread from context to a .txt file.
    
    Args:
        context: The ChatCompletionContext to get messages from
        agent_id: The agent identifier (e.g., "basic", "cot", "admin_agent")
        information: InfoDict to extract file name from (project name + bug id)
    """
    messages = await context.get_messages()
    
    # Get file name from InfoDict: project_name + bug_id
    project_name = information.get_info("project name")
    bug_id = information.get_info("bug id")
    file_name = f"{project_name}{bug_id}"
    
    # Create autogen_chatcontext directory if it doesn't exist
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "autogen_chatcontext")
    os.makedirs(output_dir, exist_ok=True)
    
    # Create full file path with agent_id as suffix
    file_path = os.path.join(output_dir, f"{file_name}_context_{agent_id}.txt")
    
    # Write messages to file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(f"{'='*80}\n")
        f.write(f"Full Message Thread (Agent: {agent_id}):\n")
        f.write(f"{'='*80}\n")
        for i, msg in enumerate(messages, 1):
            if isinstance(msg, SystemMessage):
                f.write(f"[{i}] System: {msg.content}\n")
            elif isinstance(msg, UserMessage):
                f.write(f"[{i}] User (source: {msg.source}): {msg.content}\n")
            elif isinstance(msg, AssistantMessage):
                f.write(f"[{i}] Assistant (source: {msg.source}): {msg.content}\n")
            else:
                f.write(f"[{i}] {type(msg).__name__}: {msg}\n")
        f.write(f"{'='*80}\n")
    
    print(f"Message thread saved to: {file_path}")


if __name__ == "__main__":
    information = InfoDict()
    information.add_bug_info("test", "1", [("ALL_TESTS/closure8.java", [(202, 205)])], "revised_multiagent")
    print(get_system_message(information, "You are a basic patching agent. Generate patches for bugs in Java code."))