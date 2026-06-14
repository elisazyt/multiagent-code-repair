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
from tools.context_retrieval.parsing_retrieval_funcs import tree_sitter_utils as utils


########################################################
# Helper functions for running one round of agent interactions
########################################################
async def run_patch_test_loop(patcher_id: str, admin_agent: AgentId, runtime: SingleThreadedAgentRuntime,
                              num_rounds: int = 3, context_dict: ContextDict = None) -> int:
    """
    Run num_rounds rounds of patching and testing for a given PatchingAgent
    Default 3 rounds if user doesn't specify
    """
    print(f"[{patcher_id}] Loop started")
    round = 1

    # TODO: remove this?
    while (round <= num_rounds):
        # Create patching task (initial or regeneration)
        if (round == 1):
            patching_task = PatchingTask(patcher_id=patcher_id, message="Follow the instructions to generate a patch.", patching_attempt=round)
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
    
    Workflow:
    1. Send ContextRetrievalTask to AdminAgent
    2. AdminAgent routes to ContextRetrievalAgent
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
    # SummaryAgent will summarize all NUM_ROUNDS rounds from this attempt
    # function_results already contains reasoning and results for all rounds
    if context_response.function_results:
        summary_task = SummaryTask(
            function_results=context_response.function_results,  # String with reasoning and results
            retrieval_attempt=attempt_num,
            message="Summarize the current context retrieval attempt as described previously.",
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
        context_dict.add_retrieved_context_attempt(current_summary)
    
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

def get_patching_system_message(bug_dict: BugDict, patching_system_prompt: str, agent_specific_prompt: str, context_summary: str = "") -> SystemMessage:
    """
    Get the system message for a PatchingAgent
    agent_specific_prompt differs for every type of PatchingAgent
    context_summary is only provided for the context patching agent, it is a summary of the context retrieval results
    """
    # Let msg be the generic patching prompt, then replace the placeholders with the agent-specific content
    msg = patching_system_prompt
    msg = msg.replace("{agent_specific_prompt}", agent_specific_prompt)
    msg = msg.replace("{bug_info}", format_bug_info(bug_dict).rstrip())

    # Add context summary if provided (for context patching agent)
    if context_summary:
        context_summary_str = f"Additionally, a context retrieval agent has retrieved the following info about the bug:\n{context_summary.rstrip()}"
        msg = msg.replace("{context_summary}", context_summary_str)
    else:
        msg = msg.replace("{context_summary}", "")
    
    return SystemMessage(content=msg)

def get_context_retrieval_system_message(bug_dict: BugDict, context_dict: ContextDict, prompt_template: str,) -> SystemMessage:
    """
    Get the system message for a ContextRetrievalAgent using the provided prompt template
    First, provide bug info to the agent
    Then, format past context retrieval attempts (from previous patching attempts). This is called when
    initializing the ContextRetrievalAgent, as all prior attempt summaries should be provided at once
    """
    msg = prompt_template
    msg = msg.replace("{bug_info}", format_short_bug_info(bug_dict).rstrip())

    past_retrieval_attempts = context_dict.get_retrieved_context()
    if past_retrieval_attempts:
        past_retrieval_str = "".join(f"{attempt_summary}\n" for attempt_summary in past_retrieval_attempts)
    else:
        past_retrieval_str = "No past context retrieval attempts."
    msg = msg.replace("{past_retrieval_attempts}", past_retrieval_str)

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
    Helper for format_past_context
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

def format_initial_available_functions(context_dict: ContextDict) -> str:
    """
    Only call this for the attempt 1, round 1 since there are no previous retrieval attempts
    which list the remaining functions available to be called.
    """
    result = "=== Context retrieval attempt 1 ===\n\n"
    result += format_available_functions(context_dict)
    return result


def format_current_context(current_round_results: dict, reasoning: str, context_dict: ContextDict,
                           round_num: int, attempt_num: int) -> str:
    """
    Format results for the current round of context retrieval.
    This is called in on_task for the ContextRetrievalAgent, where we add it to the chat_messages.
    
    Args:
        all_retrieval_results: List of rounds, where each round is a dict of file_path -> dict of function_name -> results
            Example: [
                {
                    "file1.java": {"func1": "results...", "func2": "results..."},
                    "file2.java": {"func3": "results..."}
                },
                {
                    "file3.java": {"func4": "results..."}
                }
            ]
        reasoning: The LLM's reasoning for the current round of context retrieval
        context_dict: ContextDict to get available functions per file
        round_num: The actual round number (1-indexed)
    
    Returns:
        String summarizing the current round's results
    """
    result = ""
    if round_num == 1 and attempt_num > 1:
        result += f"=== Context retrieval attempt {attempt_num} ===\n\n"

    result += "It was determined that the following context retrieval functions needed to be called to fix the bug.\n"
    result += f"The reasoning for calling these functions was: {reasoning}\n"
    
    # format all function call results for each file, if it exists
    if not current_round_results:
        result += (
            f"\nNo results in context retrieval attempt {attempt_num}, round {round_num}, "
            f"because no valid functions were requested or all requested functions were invalid/already called.\n"
        )
    else:
        result += f"The following has been retrieved in context retrieval attempt {attempt_num}, round {round_num}:\n"
        for file_path, file_results in current_round_results.items():
            result += f"{file_path}:\n"
            for func_name, func_results in file_results.items():
                result += f"  - {func_name}: {func_results}\n"
        result += "\n"
    
    # Show remaining available functions per file
    result += format_available_functions(context_dict)

    return result

def format_available_functions(context_dict: ContextDict) -> str:
    """
    Format the remaining functions available to be called
    Helper for format_initial_available_functions and format_current_context
    """
    result = "For each file, the following context retrieval functions are available to call in the next round:\n"
    available_functions_dict = context_dict.get_available_functions()
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