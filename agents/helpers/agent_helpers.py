"""
Helper functions for multi-agent workflows, formatting, logging, and other
functionalities that are not specific to any one agent instance.
"""

import sys
import os
from typing import Tuple
from autogen_core import AgentId, SingleThreadedAgentRuntime
from autogen_core.models import SystemMessage, UserMessage, AssistantMessage
from autogen_core.model_context import UnboundedChatCompletionContext

parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from agents.data_structures.data_classes import (
    PatchingTask,
    TestingTask,
    ContextRetrievalTask,
    SummaryTask,
)
from agents.data_structures.dicts import BugDict, ContextDict
from agents.prompt_templates import SUMMARY_PROMPT
from tools.context_retrieval.parsing_retrieval_funcs import tree_sitter_utils as utils


########################################################
# Helper functions for running one round of patching and testing
########################################################
# Default: run 3 rounds of patching and testing per agent
async def run_patch_test_loop(patcher_id: str, message: str, admin_agent: AgentId, runtime: SingleThreadedAgentRuntime, num_rounds=3, context_dict=None):
    print(f"[{patcher_id}] Loop started!")
    round = 1

    while (round <= num_rounds):
        # Create patching task (initial or regeneration)
        if (round == 1):
            patching_task = PatchingTask(patcher_id=patcher_id, message=message, patching_attempt=round)
        else:
            # Reprompt to regenerate the patch
            patching_task = PatchingTask(patcher_id=patcher_id, message=f"Based on the previous messages and failing test information, regenerate the patch.", patching_attempt=round)
        
        # Send single patching task to AdminAgent
        patching_response = await runtime.send_message(patching_task, recipient=admin_agent)
        print(f"[{patcher_id}] Round {round} - Patching result: {patching_response.result}")

        from agents.agents import PatchingAgent
        patcher_agent = PatchingAgent.instances_dict.get(patcher_id)

        # If there is no mapping, the patch wasn't applied correctly
        if not patching_response.mapping:
            patch_error = (
                "Patch was not applied. The response must contain exactly one ```java code block "
                "for each unique buggy node (see system prompt). Check that every block is "
                "enclosed in ``` and that you did not combine multiple nodes into one block."
            )
            print(f"[{patcher_id}] Round {round} - {patch_error}")
            if patcher_agent:
                await patcher_agent.add_test_result(patch_error, False, source="system")
        else:
            # Test the patch
            testing_task = TestingTask(
                patcher_id=patcher_id,
                mapping=patching_response.mapping,
            )
            testing_response = await runtime.send_message(testing_task, recipient=admin_agent)
            
            # Add test result to PatchingAgent's context for future regeneration
            await patcher_agent.add_test_result(
                testing_response.str_result,
                testing_response.success,
                source="testing",
            )

            if testing_response.success:
                print(f"[{patcher_id}] Test passed: {testing_response.str_result}")
                patcher_agent.save_candidate_patch(patching_response.mapping)
                break
            # Only the context retrieval agent passes in context_dict as an arg because it needs access to the
            # failing test info to construct the prompt for the next patching attempt, all other patching agents
            # don't need this so we set the default value context_dict=None
            elif context_dict is not None:
                context_dict.add_info("test info", testing_response.list_result)

        round += 1

    # Return the number of rounds completed
    # If we broke early, round is the correct number. If we completed all rounds, round is num_rounds + 1
    return round if round <= num_rounds else num_rounds


async def run_single_attempt_context(attempt_num: int, admin_agent: AgentId, runtime: SingleThreadedAgentRuntime, context_dict: ContextDict) -> str:
    """
    Run a single ATTEMPT of context retrieval (consists of up to 3 rounds).
    
    Flow:
    1. Send ContextRetrievalTask to AdminAgent
    2. AdminAgent routes to ContextRetrievalAgent (does up to 3 rounds internally)
    3. ContextRetrievalAgent returns ContextRetrievalResponse (with function_results containing all rounds' results and reasoning)
    4. Send SummaryTask to AdminAgent (which routes to SummaryAgent)
    5. SummaryAgent returns SummaryResponse (summarizes all 3 rounds)
    6. Format final summary with past summaries prepended
    7. All messages are logged in AdminAgent's message history
    
    Args:
        attempt_num: The attempt number (1, 2, 3, etc.) - each attempt has up to 3 rounds
        admin_agent: AgentId for AdminAgent
        runtime: SingleThreadedAgentRuntime instance
        context_dict: ContextDict to get past summaries and store current summary
        
    Returns:
        The final summary string (with past summaries prepended)
    """
    print(f"[context] Starting context retrieval attempt {attempt_num}...")
    
    # Step 1: Send ContextRetrievalTask to AdminAgent
    # Note: retrieval_attempt in ContextRetrievalTask refers to the attempt number
    context_task = ContextRetrievalTask(retrieval_attempt=attempt_num)
    context_response = await runtime.send_message(context_task, recipient=admin_agent)
    print(f"[context] Attempt {attempt_num} - Context retrieval completed (all rounds done)")
    
    # Step 2: Get past summaries from ContextDict
    past_summaries = context_dict.get_retrieved_context()
    

    # Step 3: Send SummaryTask to AdminAgent (which will route to SummaryAgent)
    # SummaryAgent will summarize all 3 rounds from this attempt
    # function_results already contains reasoning and results for all rounds
    if context_response.function_results:
        summary_task = SummaryTask(
            function_results=context_response.function_results,  # String with reasoning and results
            retrieval_attempt=attempt_num,
            message=SUMMARY_PROMPT,
        )
        summary_response = await runtime.send_message(summary_task, recipient=admin_agent)
        current_summary = summary_response.summary
        print(f"[context] Attempt {attempt_num} - Summary completed")
    else:
        current_summary = "No context has been retrieved yet."
    
    # Step 4: Format final summary with past summaries prepended
    final_summary = ""
    
    # Add past summaries section if any exist
    if past_summaries:
        final_summary += "Below is a summary of past context retrieval attempts:\n"
        for i, past_summary in enumerate(past_summaries, 1):
            # Add attempt number to each past summary
            final_summary += f"\nAttempt {i}:\n{past_summary}\n"
        final_summary += "\n"
    else:
        final_summary += "Below is a summary of past context retrieval attempts:\nNo past context retrieval attempts.\n\n"
    
    # Add current attempt summary with "Current attempt:" prefix
    final_summary += "Here is a summary of the current context retrieval attempt:\n\n"
    final_summary += "Current attempt:\n"
    final_summary += current_summary  # This already has the formatted content (without "Current attempt:" prefix)
    
    # Step 5: Store only the current attempt summary (without past summaries and without "Current attempt:" prefix) 
    # in ContextDict for future attempts. This way, when we prepend past summaries later, we don't duplicate them.
    if context_response.function_results:
        context_dict.add_retrieved_context_round(current_summary)
    
    return final_summary


########################################################
# Helper function for validating function call format for context retrieval
########################################################
def is_valid_format(file_functions) -> bool:
    """True if file_functions matches {file_path: [{func_name: {args}}, ...]}."""
    if not isinstance(file_functions, dict) or not file_functions:
        return False
    for func_calls in file_functions.values():
        if not isinstance(func_calls, list) or not func_calls:
            return False
        for entry in func_calls:
            if not isinstance(entry, dict) or len(entry) != 1:
                return False
            _, args = next(iter(entry.items()))
            if not isinstance(args, dict):
                return False
    return True

########################################################
# Helper functions for getting and formatting information
########################################################

def get_system_message(bug_dict: BugDict, role_description: str, context_summary: str = "") -> SystemMessage:
        msg = f"""{role_description}

You are given the following context information about the bug:\n"""
        msg += format_bug_info(bug_dict)

        # Add context summary if provided (for context patching agent)
        if context_summary:
            msg += f"\n\nAdditionally, a context retrieval agent has retrieved the following info about the bug:\n{context_summary}\n"

        # Add reminder about markdown format
        msg += f'''\n\nREMINDER - CRITICAL FORMATTING REQUIREMENTS:
        
        You must return SEPARATE markdown code blocks for EACH unique buggy node. Each unique buggy node (method/class) must have its own distinct markdown code block.
        
        Format for each patch:
        ```java
        [patch code for this specific buggy node]
        ```
        
        CRITICAL RULES:
        1. If there are N unique buggy nodes, you MUST provide N separate markdown code blocks (one per node).
        2. DO NOT combine multiple buggy nodes into a single code block. Each node gets its own block.
        3. If multiple bug locations are within the same method/class node, provide only ONE patch for that entire node (not one per bug location).
        4. Each code block should contain the complete fixed code for that one buggy node only.
        5. Do not use markdown format for anything that is not a patch. Only use markdown format for the patches.
        
        Example: If you have 2 unique buggy nodes (e.g., methodA and methodB), you must provide:
        ```java
        [complete fixed code for methodA]
        ```
        
        ```java
        [complete fixed code for methodB]
        ```
        
        Additionally, briefly explain your reasoning for the patches.
        '''
        
        return SystemMessage(content=msg)

def format_bug_info(bug_dict: BugDict) -> str:
    """Format bare minimum bug information without additional analysis"""
    bug_locations = bug_dict.get_info("bug files and locations")
    result = ''
    bug_number = 1  # Track bug number sequentially across all files and nodes

    # Reset stored node locations (will be populated during formatting)
    bug_dict.add_info("unique node locations per file", [])

    # Iterate through each file
    # Structure: (file_path, modified_source_name, bug_locations_list)
    for buggy_file_info in bug_locations:
        # Use the helper method to format bugs grouped by unique nodes
        # Returns: (formatted_string, next_bug_number)
        formatted_bugs, next_bug_number = format_bugs_grouped_by_node(buggy_file_info, bug_dict, bug_number)
        result += formatted_bugs
        bug_number = next_bug_number  # Continue bug numbering across files
        
    return result

def format_bugs_grouped_by_node(buggy_file_info, bug_dict: BugDict, start_number: int = 1) -> Tuple[str, int]:
    """
    Format all bugs in one file, grouped by unique buggy nodes. Returns (formatted_string, next_bug_number).
    Also stores unique node locations in BugDict to avoid recomputing later.
    
    Args:
        buggy_file_info: Tuple of (java_file_path, modified_source_name, bug_locations_list)
        bug_dict: BugDict object to store unique node locations
        start_number: Starting bug number
        
    Returns:
        Tuple of (formatted_string, next_bug_number)
    """
    # Extract file info from tuple
    java_file_path, _, bug_locations_list = buggy_file_info
    
    # Read file and retrieve bugs
    with open(java_file_path, 'rb') as f:
        code = f.read()
    bugs_in_file = utils.retrieve_buggy_lines_and_node(java_file_path, bug_locations_list)
    
    result = ''
    node_number = 1
    bug_number = start_number  # Track bug number separately, incrementing across all nodes
    
    # Group bugs by unique buggy node
    unique_nodes = {}  # (start, end) -> list of (bug_location, bug_code, buggy_node_info)
    for bug_in_file in bugs_in_file:
        _, bug_code, buggy_node_info = bug_in_file
        if buggy_node_info is None:
            continue
        buggy_node_location, buggy_node = buggy_node_info
        if buggy_node_location not in unique_nodes:
            unique_nodes[buggy_node_location] = []
        unique_nodes[buggy_node_location].append(bug_in_file)
    
    # Store unique node locations in BugDict for later use in apply_all_patches
    # This avoids calling retrieve_buggy_lines_and_node again (which is slow)
    # Structure: List[List[Tuple[int, int]]] - one list per file, each containing sorted node locations
    # Get sorted unique node locations for this file and append to the list
    unique_node_locations = sorted(unique_nodes.keys())
    bug_dict.get_info("unique node locations per file").append(unique_node_locations)
    
    # Format each unique node (showing all bug locations within it)
    for buggy_node_location in sorted(unique_nodes.keys()):
        bugs_in_node = unique_nodes[buggy_node_location]
        
        # Use the first bug's node info for formatting (they all have the same node)
        first_bug = bugs_in_node[0]
        _, bug_code, buggy_node_info = first_bug
        buggy_node_location, buggy_node = buggy_node_info
        
        # Format the node info
        buggy_node_text = utils.get_node_text(buggy_node, code)
        
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

def format_short_bug_info(bug_dict: BugDict) -> str:
    """
    Format only the bug locations for context retrieval instructions
    """
    bug_locations = bug_dict.get_info("bug files and locations")
    result = ""
    bug_number = 1
    
    for file_path, _, bug_locations_list in bug_locations:
        result += f"File: {file_path}\n"
        for start_line, end_line in bug_locations_list:
            result += f"    Bug location #{bug_number}: (start_line, end_line) = ({start_line}, {end_line})\n"
            bug_number += 1
        result += "\n"
    
    return result


def format_past_context(context_dict: ContextDict, repair_summary: str = "", bug_dict: BugDict = None) -> str:
    """Format past context retrieval attempts (from previous patching attempts) as a string for LLM"""
    retrieved = context_dict.get_retrieved_context()

    result = "Below is a summary of past repair attempts and the failed tests:\n"
    if repair_summary:
        result += repair_summary
        result += "\n\n"
    
    result += "Below is a summary of past context retrieval attempts:\n"
    if retrieved:
        for round_summary in retrieved:
            result += f"{round_summary}\n"
        result += "\n"
    
    # Show bug locations
    if bug_dict is not None:
        result += "\nHere are all the bug locations and their corresponding start and end lines, which can also be found above:\n"
        result += format_short_bug_info(bug_dict)
    
    # TODO: consolidate this into prompt_templates.py
    # Show available functions per file with clear instructions
    result += "\nHere are the functions you can call and their arguments:\n"
    result += "\nThese functions are available to call in every round:\n"
    result += "- comment_retrieval(start_line, end_line): retrieve comments before the bug location\n"
    result += "- all_funcs_in_class(start_line, end_line): retrieve all method signatures in the class containing the bug location\n"
    result += "- one_hop_api_retrieval(start_line, end_line, var): retrieve 1-hop APIs callable on the specified variable. Requires both the bug location (start_line, end_line) and the variable name (var). This function should only be called on suspicious variables.\n"
    result += "- get_callers(start_line, end_line): retrieve all callers of the function enclosing the bug location\n"
    result += "\nThese functions are only available from the second round onwards:\n"
    result += "- similar_lines_of_code(start_line, end_line): retrieve top k similar lines of code to the bug location\n"
    result += "- similar_function_name(start_line, end_line): retrieve top k functions with most similar name to the function containing the bug location\n"
    
    result += "The arguments must be labeled as one of \"start_line\", \"end_line\", or \"var\".\n"
    result += "\"start_line\" and \"end_line\" can be used to specify a bug location that you want to retrieve context for. It should match one of the bug locations listed above.\n"
    result += "\"var\" can be used to specify a variable that you want to retrieve context for.\n"
    result += "Note: For one_hop_api_retrieval, you MUST provide both start_line, end_line, AND var, as the function needs the bug location to find the variable in context.\n\n"
    
    result += "The function calls should be formatted as follows:\n"
    result += "{\n"
    result += "  \"file_functions\": {\n"
    result += "    \"file.java\": [\n"
    result += "      {\"function_1\": {\"start_line\": 1, \"end_line\": 2}},\n"
    result += "      {\"one_hop_api_retrieval\": {\"start_line\": 1, \"end_line\": 2, \"var\": \"variable_name\"}},\n"
    result += "      {\"function_3\": {}}\n"
    result += "    ]\n"
    result += "  },\n"
    result += "  \"reasoning\": \"...\"\n"
    result += "}\n\n"
    
    result += "IMPORTANT: If you do not want to retrieve any more context, respond with text (e.g., 'I have enough context') instead of calling the function.\n"
    result += "If you call the function, you MUST provide 'file_functions' with at least one function and the required arguments for each function.\n\n"
    
    result += "For each file, the remaining functions are available to call:\n"
    available_functions_dict = context_dict.get_available_functions()
    
    if not available_functions_dict:
        result += "  No files available for context retrieval.\n"
    else:
        for file_path in sorted(available_functions_dict.keys()):
            available_for_file = available_functions_dict[file_path]
            if available_for_file:
                result += f"  - {file_path}: {', '.join(available_for_file)}\n"
    
    result += "\nIMPORTANT: Only use file paths and function names listed above. Do not make up file paths or function names.\n"
    result += "Additionally, only choose the functions that are necessary for fixing the bug. Do not call all functions just because they are available.\n"

    result += "IMPORTANT: Make sure you format the function calls exactly as shown in the example above.\n"
    result += "It should be a dictionary with exactly two keys: 'file_functions' and 'reasoning'.\n"
    result += "The 'file_functions' key should be a dictionary with the file path as the key and the value should be a LIST of function calls, even if there is only one function call.\n"
    
    # TODO: Add instructions for extra params (e.g., specify which variables/methods to retrieve info on)
    return result


def format_current_context(all_retrieval_results: list, reasoning: str, context_dict: ContextDict, round_num: int = None) -> str:
    """Format current round's retrieval results (lightweight summary for LLM during retrieval rounds).
    
    Args:
        all_retrieval_results: List of rounds, where each round is a dict of file_path -> dict of function_name -> results
            Example: [
                {
                    "file1.java": {"comment_retrieval": "results...", "api_retrieval_1hop": "results..."},
                    "file2.java": {"api_retrieval_2hop": "results..."}
                },
                {
                    "file3.java": {"callgraph_retrieval": "results..."}
                }
            ]
            Round number = index + 1 (index 0 = round 1, index 1 = round 2, etc.)
        reasoning: The LLM's reasoning for the CURRENT round only
        context_dict: ContextDict to get available functions per file
        round_num: The actual round number (1-indexed). If None, calculates from list length.
    
    Returns:
        String summarizing the CURRENT round's results (not all previous rounds - those are in conversation history)
    """
    if not all_retrieval_results:
        return "No context retrieved yet in this session.\n"
    
    # Only show the MOST RECENT round (the current one)
    current_round_results = all_retrieval_results[-1]
    # Use provided round_num or calculate from list length
    current_round_num = round_num
    
    result = f"It was determined that the following context retrieval functions needed to be called to fix the bug.\n"
    if reasoning:
        result += f"The reasoning for calling these functions was: {reasoning}\n"
    
    # Handle empty rounds
    if not current_round_results:
        result += f"\nNo results in Round {current_round_num} because no valid functions were requested or all requested functions were invalid/already called.\n"
    else:
        result += f"The results of the context retrieval functions have been retrieved in round {current_round_num}:\n\n"
        # Format only the current round's results (no redundant header)
        for file_path, file_results in current_round_results.items():
            result += f"{file_path}:\n"
            for func_name, func_results in file_results.items():
                result += f"  - {func_name}: {func_results}\n"
        result += "\n"
    
    # Show remaining available functions per file
    result += "For each file, the remaining functions are available to call in the next round:\n"
    # Get the dict mapping file_path -> list of available functions
    available_functions_dict = context_dict.get_available_functions()  # Returns dict when file_path is None
    
    for file_path in sorted(available_functions_dict.keys()):
        available_for_file = available_functions_dict[file_path]
        if available_for_file:
            result += f"  - {file_path}: {', '.join(available_for_file)}\n"
    
    return result


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


async def save_message_thread(
    context: UnboundedChatCompletionContext, 
    agent_id: str,
    bug_dict: BugDict
):
    """
    Save the entire message thread from context to a .txt file.
    
    Args:
        context: The ChatCompletionContext to get messages from
        agent_id: The agent identifier (e.g., "basic", "cot", "admin_agent")
        bug_dict: BugDict to extract file name from (project name + bug id)
    """
    messages = await context.get_messages()
    
    # Get file name from BugDict: project_name + bug_id
    project_name = bug_dict.get_info("project name")
    bug_id = bug_dict.get_info("bug id")
    file_name = f"{project_name}{bug_id}"
    
    output_dir = bug_dict.get_info("chat context path")

    file_path = os.path.join(output_dir, f"{file_name}_{agent_id}.txt")
    
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


async def save_all_message_threads(
    bug_dict: BugDict,
    admin_agent_instance=None,
    context_agent_instance=None,
):
    """Save chat logs for all agents that have been instantiated so far."""
    from agents.agents import PatchingAgent

    for agent_id, patcher_agent in PatchingAgent.instances_dict.items():
        await save_message_thread(
            patcher_agent.chat_messages,
            agent_id=agent_id,
            bug_dict=bug_dict,
        )

    if admin_agent_instance is not None:
        await save_message_thread(
            admin_agent_instance.chat_messages,
            agent_id=admin_agent_instance.id.key,
            bug_dict=bug_dict,
        )

    if context_agent_instance is not None:
        await save_message_thread(
            context_agent_instance.chat_messages,
            agent_id="context_retrieval",
            bug_dict=bug_dict,
        )