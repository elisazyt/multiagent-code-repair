import os
import sys
from typing import Optional
from openai import AsyncOpenAI
from autogen_core import AgentId, MessageContext, RoutedAgent, message_handler
from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage, AssistantMessage
from autogen_core.model_context import UnboundedChatCompletionContext

from data_classes import PatchingTask, PatchingResponse, TestingTask, TestingResponse, ContextRetrievalTask, ContextRetrievalResponse, SummaryTask, SummaryResponse
import agent_helpers as helpers

from info_dict import InfoDict, ContextDict
import patch_utils as p_utils

from function_call import create_context_retrieval_function

import cr_functions as cr_funcs

# Add parent directory to path to import test_suites
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Add the context_retrieval directory to the path
sys.path.append(os.path.join(parent_dir, 'context_retrieval'))
sys.path.insert(0, parent_dir)
from test_suites import test_suites as ts


class AdminAgent(RoutedAgent):
    def __init__(self, receiver_instances: dict[str, list[AgentId]], system_message: SystemMessage, context_info: ContextDict = None, runtime = None):
        super().__init__("Admin Agent")
        self.patching_instances = receiver_instances.get("patching", [])
        self.testing_instances = receiver_instances.get("testing", [])
        self.context_instances = receiver_instances.get("context", [])
        self.summary_instances = receiver_instances.get("summary", [])
        self.context_info = context_info
        self._runtime = runtime  # Store as private attribute since runtime is a read-only property
        
        # Context for logging all messages that pass through AdminAgent
        # Initialize with system message as the first message
        self._context = UnboundedChatCompletionContext(initial_messages=[system_message])
    
    def get_context(self) -> UnboundedChatCompletionContext:
        """Get the message context for logging/debugging"""
        return self._context

    @message_handler
    async def process_patching_tasks(self, message: PatchingTask, ctx: MessageContext) -> PatchingResponse:
        print(f"Patching task received by agent with patcher_id: {message.patcher_id}.")
        
        # If this is a context patching request, route to context patching handler
        if message.patcher_id == "context":
            return await self.process_context_patching_task(message, ctx)
        
        # Log incoming patching task (source is the sender, or "main" if None)
        sender_key = ctx.sender.key if ctx.sender else "main"
        await helpers.log_message(
            self._context,
            f"PatchingTask (patcher_id={message.patcher_id}): {message.message}",
            role="user",
            source=sender_key
        )

        # Find the corresponding patching instance based on patcher_id
        # patcher_id in PatchingTask is used for two purposes:
        # 1. Routing: to find which AgentId to send the message to (i.e., the patching instance)
        # 2. Tracking: to include in the response so we know which agent generated it (i.e., when generating the PatchingResponse)
        patching_instance = None
        for instance in self.patching_instances:
            if (instance.key == message.patcher_id):
                patching_instance = instance
                break
        if not patching_instance:
            raise ValueError(f"No patching instance found for patcher_id: {message.patcher_id}")

        # For now, the task is predefined. Later, we will pass in some InfoDict or similar object and construct the prompt
        patching_response = await self.send_message(message, patching_instance)
        
        # Log patching response (source is the patching agent that generated it)
        await helpers.log_message(
            self._context,
            f"PatchingResponse (patcher_id={patching_response.patcher_id}): {patching_response.result}",
            role="assistant",
            source=patching_response.patcher_id
        )
        
        return patching_response
    
    @message_handler
    async def process_testing_task(self, message: TestingTask, ctx: MessageContext) -> TestingResponse:
        # Log incoming testing task (source is the sender, or "main" if None)
        sender_key = ctx.sender.key if ctx.sender else "main"
        await helpers.log_message(
            self._context,
            f"TestingTask (patcher_id={message.patcher_id}): Test the patch with mapping {message.mapping}",
            role="user",
            source=sender_key
        )
        
        testing_response = await self.send_message(message, self.testing_instances[0])
        
        # Log testing response (source is the testing agent)
        await helpers.log_message(
            self._context,
            f"TestingResponse (patcher_id={testing_response.patcher_id}, success={testing_response.success}): {testing_response.str_result}",
            role="assistant",
            source="testing"
        )
        
        # Just return the testing response - run_patch_test_loop handles regeneration logic
        return testing_response
    
    @message_handler
    async def process_context_retrieval_task(self, message: ContextRetrievalTask, ctx: MessageContext) -> ContextRetrievalResponse:
        # Log incoming context retrieval task (source is the sender, or "main" if None)
        sender_key = ctx.sender.key if ctx.sender else "main"
        await helpers.log_message(
            self._context,
            f"ContextRetrievalTask (retrieval_attempt={message.retrieval_attempt}): Retrieve context for bug fixing",
            role="user",
            source=sender_key
        )
        
        if not self.context_instances:
            raise ValueError("No context retrieval instances available")
        
        context_response = await self.send_message(message, self.context_instances[0])
        
        # Log context retrieval response (the full, raw response)
        # Note: this will later be condensed into a summary when we send it in a prompt to the patching agent
        await helpers.log_message(
            self._context,
            f"ContextRetrievalResponse (retrieval_attempt={context_response.retrieval_attempt}): {context_response.function_results}...",
            role="assistant",
            source="context"
        )
        
        return context_response
    
    @message_handler
    async def process_summary_task(self, message: SummaryTask, ctx: MessageContext) -> SummaryResponse:
        # Log incoming summary task (source is the sender, or "main" if None)
        sender_key = ctx.sender.key if ctx.sender else "main"
        await helpers.log_message(
            self._context,
            f"SummaryTask (retrieval_attempt={message.retrieval_attempt}): Summarize context retrieval results",
            role="user",
            source=sender_key
        )
        
        if not self.summary_instances:
            raise ValueError("No summary instances available")
        
        summary_response = await self.send_message(message, self.summary_instances[0])
        
        # Log summary response
        await helpers.log_message(
            self._context,
            f"SummaryResponse (retrieval_attempt={message.retrieval_attempt}): {summary_response.summary}",
            role="assistant",
            source="summary"
        )
        
        return summary_response
    
    async def process_context_patching_task(self, message: PatchingTask, ctx: MessageContext) -> PatchingResponse:
        """
        Handle context patching: first retrieve context, then send patching task with context summary.
        Note: This is not a @message_handler because it's called from process_patching_tasks.
        """
        print(f"[context_patching] Starting context patching for agent: {message.patcher_id}")
        
        # Log incoming context patching task
        sender_key = ctx.sender.key if ctx.sender else "main"
        await helpers.log_message(
            self._context,
            f"ContextPatchingTask (patcher_id={message.patcher_id}): {message.message}",
            role="user",
            source=sender_key
        )
        
        # Step 1: Run context retrieval to get context summary for this patching attempt
        if not self.context_info or not self._runtime:
            raise ValueError("context_info and runtime must be provided to AdminAgent for context patching")
        
        # Use the patching attempt number as the attempt number for context retrieval
        # Each patching attempt gets its own context retrieval attempt (up to 3 rounds of retrieval)
        attempt_num = message.patching_attempt
        print(f"[context_patching] Running context retrieval for patching attempt {attempt_num} (context retrieval attempt {attempt_num})")
        context_summary = await helpers.run_single_attempt_context(
            attempt_num=attempt_num,
            admin_agent=self.id,
            runtime=self._runtime,
            context_info=self.context_info
        )
        print(f"[context_patching] Context retrieval completed for attempt {attempt_num}. Summary length: {len(context_summary)} characters")
        
        # Step 2: Create a new PatchingTask with the context summary included
        patching_task_with_context = PatchingTask(
            patcher_id=message.patcher_id,
            message=message.message,
            context_summary=context_summary
        )
        
        # Step 3: Find the context patching instance
        context_patching_instance = None
        for instance in self.patching_instances:
            if instance.key == message.patcher_id:
                context_patching_instance = instance
                break
        if not context_patching_instance:
            raise ValueError(f"No patching instance found for patcher_id: {message.patcher_id}")
        
        # Step 4: Send the patching task with context to the context patching agent
        patching_response = await self.send_message(patching_task_with_context, context_patching_instance)
        
        # Log patching response
        await helpers.log_message(
            self._context,
            f"PatchingResponse (patcher_id={patching_response.patcher_id}): {patching_response.result}",
            role="assistant",
            source=patching_response.patcher_id
        )
        
        return patching_response


class PatchingAgent(RoutedAgent):
    # Class variable to store instances by their key (shared across all instances)
    _instances_dict = {}
    
    def __init__(self, model_client: ChatCompletionClient, information: InfoDict, role_description: dict[str, str]):
        super().__init__("Patching Agent")
        # create OpenAI chat completion client
        self._model_client = model_client

        self.information = information
        
        # role_description can be a string or a dict mapping agent keys to role description strings
        # If it's a dict, look up the role description based on self.id.key (set by super().__init__)
        agent_key = self.id.key
        if agent_key in role_description:
            self._role_description = role_description[agent_key]
        else:
            raise ValueError(f"Agent key '{agent_key}' not found in role_descriptions dict. Available keys: {list(role_description.keys())}")
        
        # Create system message with the role description
        # For context patching agent, context_summary will be added as a UserMessage in on_task
        self._system_message = helpers.get_system_message(information, self._role_description)
        
        # Each agent instance has its own conversation context (manages history automatically)
        # Initialize with system message as the first message
        self._context = UnboundedChatCompletionContext(initial_messages=[self._system_message])

    @message_handler
    # When runtime.send_message is called with an argument of type Task, this on_task method is called
    # The response of send_message is a TaskResponse object
    async def on_task(self, message: PatchingTask, ctx: MessageContext) -> PatchingResponse:
        # Store this instance in the class dictionary (shared across all instances)
        if self.id.key not in PatchingAgent._instances_dict:
            PatchingAgent._instances_dict[self.id.key] = self
        
        # If context_summary is provided, recreate the system message with context summary included
        # This is for context patching agent
        if message.context_summary:
            # Get existing messages to preserve conversation history
            existing_messages = await self._context.get_messages()
            
            # Recreate system message with context summary
            self._system_message = helpers.get_system_message(
                self.information, 
                self._role_description, 
                context_summary=message.context_summary
            )
            
            # Recreate context with new system message, preserving all non-system messages
            # Filter out the old system message and keep everything else
            other_messages = [msg for msg in existing_messages if not isinstance(msg, SystemMessage)]
            self._context = UnboundedChatCompletionContext(initial_messages=[self._system_message] + other_messages)
        
        # Create UserMessage for this request
        # Use the actual sender's key (e.g., "admin_agent") instead of receiver's key
        sender_key = ctx.sender.key if ctx.sender else "unknown"
        # Format message consistently with AdminAgent's logging format
        formatted_content = f"PatchingTask (patcher_id={message.patcher_id}): {message.message}"
        user_message = UserMessage(content=formatted_content, source=sender_key)
        
        # Add user message to context (context automatically tracks it)
        await self._context.add_message(user_message)
        
        # Get all messages from context (includes system + all history automatically)
        messages = await self._context.get_messages()
        
        # Call LLM with full conversation history
        llm_result = await self._model_client.create(
            messages=messages,
            cancellation_token=ctx.cancellation_token,
        )
        
        result_text = llm_result.content
        # Save patches and get mapping of modified_source_name -> patch_file_path
        print(f"--------------------------------")
        print(f"result_text: {result_text}")
        print(f"--------------------------------")
        patch_mapping = self.save_patch(result_text)
        
        # Add assistant response to context (for next round)
        assistant_message = AssistantMessage(content=result_text, source=self.id.key)
        await self._context.add_message(assistant_message)

        # Return the patch mapping - AdminAgent will handle sending to TestingAgent
        return PatchingResponse(patcher_id=self.id.key, result=result_text, mapping=patch_mapping)
    
    # When TestingAgent sends a test result, add it to the conversation context
    # This does not happen automatically, so we need to add it manually
    async def add_test_result(self, test_str_result: str, success: bool, source: str = "testing"):
        """Add a test result to the conversation context"""
        # Format the test result message
        if success:
            result_message = f"All test suites passed. Here are the testing results: {test_str_result}"
        else:
            result_message = f"One or more test suites failed. Here are the testing results: {test_str_result}"
        
        # Use the general log_message utility function
        await helpers.log_message(
            self._context,
            f"Feedback from test suites: {result_message}",
            role="user",
            source=source
        )

    # TODO: consider making this a helper function rather than an instance method
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
        # Use self.id.key (e.g., "basic", "cot") as the agent role for patch file naming
        patch_mapping = p_utils.apply_all_patches(bug_files_and_locations, response, self.id.key, unique_node_locations_per_file)
        return patch_mapping


# TODO: for the purposes of keeping the prompt short, remove the failing test function.
# Just the failing line +/- 5-ish lines should be enough
class TestingAgent(RoutedAgent):
    def __init__(self, information: InfoDict):
        super().__init__("Testing Agent")
        self.information = information
    
    @message_handler
    async def on_task(self, message: TestingTask, ctx: MessageContext) -> TestingResponse:        
        mapping = message.mapping

        project_name = self.information.get_info("project name")
        bug_id = self.information.get_info("bug id")
        working_directory = self.information.get_info("working directory")
        test_result = ts.run_defects4j_test(project_name, bug_id, working_directory, mapping)

        failing_test_info_string = ""
        test_info_list = []
        all_tests_passed = True

        # test_result is a dict with keys 'success' and 'failing_tests'
        if 'error' in test_result:
            all_tests_passed = False
            failing_test_info_string = test_result['error']
        else:
            if test_result['success'] == False:
                all_tests_passed = False
                failing_test_info_string += 'Error: Test command did not run. Check for possible errors such as undefined function calls, compile errors, etc.'
            if len(test_result['failing_tests']) > 0:
                all_tests_passed = False
                # Reconstruct working_dir from checkout_dir, project_name, and bug_id
                checkout_dir = self.information.get_info("working directory")
                project_name = self.information.get_info("project name")
                bug_id = self.information.get_info("bug id")
                working_dir = os.path.join(checkout_dir, f"{project_name.lower()}{bug_id}")
                test_info_string, test_info_list = ts.get_failing_test_info(working_dir, project_name, test_result['failing_tests'])
                failing_test_info_string += test_info_string
                failing_test_info_string += '\n'
        
        if all_tests_passed:
            return TestingResponse(patcher_id=message.patcher_id, success=True, str_result="All test suites passed.", list_result=[])
        else:
            return TestingResponse(patcher_id=message.patcher_id, success=False, str_result=failing_test_info_string, list_result=test_info_list)


class ContextRetrievalAgent(RoutedAgent):
    def __init__(self, model_client: ChatCompletionClient, context_info: ContextDict, role_description: str, past_summary: str, information: InfoDict):
        super().__init__("Context Retrieval Agent")
        self.context_info = context_info
        self.information = information
        self._model_client = model_client

        # Initialize CPG if Joern configuration is available
        self._initialize_cpg()

        # Build system message with bug information (if available) and past context
        system_message_content = role_description + "\n\n"
        system_message_content += "You are given the following context information about the bug:\n"
        system_message_content += helpers.format_bug_info(information) + "\n\n"
        system_message_content += helpers.format_past_context(context_info, past_summary, information)
        
        system_message = SystemMessage(content=system_message_content)
        self._context = UnboundedChatCompletionContext(initial_messages=[system_message])
    
    def _initialize_cpg(self):
        """Initialize Joern CPG for the project if it doesn't already exist."""
        import os
        from context_retrieval.joern_session import JoernSession
        
        # Get Joern configuration from InfoDict
        joern_executable = self.information.get_info("joern executable")
        joern_directory = self.information.get_info("joern directory")
        joern_github_dir = os.getenv('JOERN_GITHUB_DIR')
        
        # Get project info
        project_name = self.information.get_info("project name")
        bug_id = self.information.get_info("bug id")
        checkout_dir = self.information.get_info("working directory")
        
        # Get the first Java file path (for JoernSession initialization)
        bug_locations = self.information.get_info("bug files and locations")
        if not bug_locations:
            return  # No bug locations, skip CPG creation
        
        first_file_path = bug_locations[0][0]  # (file_path, modified_source_name, bug_locations_list)
        cpg_project_name = f"{project_name}{bug_id}"
        
        # Check if we have all required configuration
        if not (joern_executable and joern_directory and joern_github_dir and checkout_dir):
            print(f"[CPG] WARNING: Joern configuration incomplete. CPG creation skipped.")
            if not joern_executable:
                print("  Missing: joern executable")
            if not joern_directory:
                print("  Missing: joern directory")
            if not joern_github_dir:
                print("  Missing: JOERN_GITHUB_DIR environment variable")
            if not checkout_dir:
                print("  Missing: working directory")
            return
        
        # Check if CPG already exists
        cpg_path = os.path.join(joern_directory, 'workspace', cpg_project_name, 'cpg.bin.zip')
        if os.path.exists(cpg_path):
            print(f"[CPG] CPG already exists at {cpg_path}, skipping creation")
            return
        
        # Create CPG
        print(f"[CPG] CPG not found at {cpg_path}, creating it...")
        joern_session = JoernSession(first_file_path, joern_executable, joern_directory)
        success = joern_session.create_cpg_from_defects4j(
            project_name=project_name,
            bug_id=bug_id,
            checkout_dir=checkout_dir,
            joern_github_dir=joern_github_dir
        )
        
        if not success:
            print(f"[CPG] WARNING: Failed to create CPG. Some context retrieval functions may not work.")
        else:
            print(f"[CPG] CPG created successfully at {cpg_path}")

    @message_handler
    async def on_task(self, message: ContextRetrievalTask, ctx: MessageContext) -> ContextRetrievalResponse:
        # Initialize tools, wrap in list since OpenAI API expects tools to be a list
        tools = [create_context_retrieval_function()]
        max_rounds = 3  # Each attempt consists of up to 3 rounds
        all_retrieval_results = ""  # String for logging (not used in final response)
        
        # Loop through rounds internally (up to 3 rounds per attempt)
        round = 1
        while round <= max_rounds:
            
            # Add round 2 functions (similar_lines_of_code, similar_function_name) at the start of round 2
            if round == 2:
                self.context_info.add_round2_functions()

            # Call LLM for this round
            messages = await self._context.get_messages()
            llm_result = await self._model_client.create(
                messages=messages,
                tools=tools,
                cancellation_token=ctx.cancellation_token,
            )
            
            # llm_result.content is either:
            # - str: LLM responded with text (e.g., "I have enough context")
            # - list[FunctionCall]: LLM called the request_context function (always a list when function is called)
            if isinstance(llm_result.content, str):
                # TODO: remove this once we have a better way to handle the case where the LLM does not call the function
                if "enough" in llm_result.content.lower():
                    break
                # Otherwise, continue to next round (might be an error message)
                round += 1
                continue
            
            # Parse function call - llm_result.content is a list[FunctionCall] when function is called
            # Each FunctionCall has:
            # - name: "request_context" (the function name from our schema)
            # - arguments: JSON string containing file_functions, reasoning, etc.
            import json
            
            # Get the single function call (our schema only defines one function, so list has one item)
            llm_result_content = llm_result.content[0]
            
            # Get arguments from function call (autogen's FunctionCall.arguments is always a JSON string)
            print(f"[DEBUG] Raw function call arguments: {llm_result_content.arguments}")
            try:
                args = json.loads(llm_result_content.arguments)
            except json.JSONDecodeError as e:
                print(f"[ERROR] Failed to parse JSON arguments: {e}")
                print(f"[ERROR] Raw arguments string: {llm_result_content.arguments}")
                round += 1
                continue
            
            # Extract file_functions dict: {file_path: [function_names]}
            file_functions = args.get("file_functions", {})
            reasoning = args.get("reasoning", "")  # LLM's reasoning for why it selected these functions
            #TODO: figure out better way to pass function arguments
            # TODO: figure out selected_methods and 2-hop expansion
            selected_methods = args.get("selected_methods", [])  # For 2-hop API expansion
            
            # Validate that file_functions was provided (it's required in the schema)
            if not file_functions:
                await self._context.add_message(UserMessage(
                    content=f"Error in Round {round}: The function call is missing the required 'file_functions' parameter. Your reasoning was: {reasoning}. "
                    f"If you do not want to retrieve any more context, respond with text (e.g., 'I have enough context') instead of calling the function. "
                    f"If you do want to retrieve context, please call the function again with 'file_functions' included.",
                    source="system"
                ))
                print(f"[WARNING] Round {round} - LLM called function but didn't provide 'file_functions' (required). Reasoning: {reasoning}")
                # Don't increment round - let LLM retry in the same round
                continue
            
            # Debug: Show what LLM actually requested vs what it said in reasoning
            all_requested = []
            for file_path, func_calls in file_functions.items():
                for func_call_dict in func_calls:
                    function_name = list(func_call_dict.keys())[0]
                    all_requested.append(function_name)
            print(f"[DEBUG] Round {round} - LLM reasoning said: {reasoning}")
            print(f"[DEBUG] Round {round} - LLM actually requested functions: {all_requested}")
            print(f"[DEBUG] Round {round} - Parsed file_functions dict: {file_functions}")
            
            # Validate file paths and functions
            available_functions_dict = self.context_info.get_available_functions()
            valid_file_paths = set(available_functions_dict.keys())
            
            # Process each file and its requested functions
            # current_round_results: Structure {file_path: {function_name: results}} for ALL files in this round
            current_round_results = {}
            for file_path, function_calls in file_functions.items():
                # Validate file path
                if file_path not in valid_file_paths:
                    print(f"Warning: LLM requested invalid file path '{file_path}'. Valid paths: {valid_file_paths}")
                    continue  # Skip invalid file paths
                
                # Extract function names and arguments from new structure
                # function_calls is a list of dicts: [{"function_name": {"start_line": ..., "end_line": ...}}, ...]
                valid_functions = available_functions_dict.get(file_path, [])
                current_round_results[file_path] = {}
                
                for func_call_dict in function_calls:
                    # Each func_call_dict has exactly one key (the function name)
                    function_name = list(func_call_dict.keys())[0]
                    function_args = func_call_dict[function_name]  # The arguments dict
                    
                    # Validate function name
                    if function_name not in valid_functions:
                        print(f"Warning: LLM requested invalid function '{function_name}' for {file_path}. Valid: {valid_functions}")
                        # Add error message instead of silently skipping
                        current_round_results[file_path][function_name] = f"ERROR: Function '{function_name}' has already been called in a previous round or is not available for this file."
                        continue  # Skip executing the function, but error message is already added
                    
                    # Execute function with its arguments
                    results = self.execute_functions(function_name, file_path, function_args)
                    current_round_results[file_path][function_name] = results
            
            # Remove only the functions that were actually executed (from current_round_results, not file_functions)
            # Skip functions that have error messages (they weren't actually executed)
            for file_path, executed_functions in current_round_results.items():
                for function_name, result in executed_functions.items():
                    # Only remove if it was successfully executed (not an error message)
                    if not isinstance(result, str) or not result.startswith("ERROR:"):
                        self.context_info.remove_function(function_name, file_path)
            
            # Add state summary at the END of the round (after results are stored)
            # Format current round results as string and append to all_retrieval_results
            # Pass only the current round's results (as a list with one element) and the round number
            current_round_results_string = helpers.format_current_context([current_round_results], reasoning, self.context_info, round_num=round)
            await self._context.add_message(UserMessage(content=current_round_results_string, source="system"))
            all_retrieval_results += current_round_results_string
            
            # Check if any functions are still available - if not, break early
            available_functions_dict = self.context_info.get_available_functions()
            # Check if any file has any available functions
            has_available = any(funcs for funcs in available_functions_dict.values())
            
            if not has_available:
                # No functions available - break early
                await self._context.add_message(UserMessage(
                    content="No more context retrieval functions are available. All functions have been called.",
                    source="system"
                ))
                break
            
            round += 1
        
        # After all rounds in this attempt, return response
        # SummaryAgent will be called separately in run_single_attempt_context
        # function_results already contains all the information SummaryAgent needs (reasoning + results)
        return ContextRetrievalResponse(
            retrieval_attempt=message.retrieval_attempt,  # This is the attempt number
            function_results=all_retrieval_results  # All rounds' results with reasoning (for SummaryAgent)
        )
    
    def execute_functions(self, function_name: str, file_path: str, function_args: dict = None):
        """Execute context retrieval functions.
        
        Args:
            function_name: Name of the function to execute (e.g., "comment_retrieval")
            file_path: Path to the Java file to retrieve context for
            function_args: Dict containing function arguments (e.g., {"start_line": 202, "end_line": 205})
        
        Returns:
            String result with retrieved context information
        """
        if function_args is None:
            function_args = {}
        
        # Extract arguments
        start_line = function_args.get("start_line")
        end_line = function_args.get("end_line")
        variable = function_args.get("var")
        
        # Get class name for functions that need it (e.g., get_callees)
        # Use tree-sitter when line numbers are available for accurate class detection
        class_name = None
        if start_line is not None and end_line is not None:
            try:
                import isolate_bug as ib
                bug_location = (start_line, end_line)
                class_name = ib.extract_class_name_from_file(file_path, bug_location)
            except ValueError as e:
                # If class name extraction fails, log warning but continue
                # Some functions don't require class_name, so we'll handle it per function
                print(f"Warning: Could not extract class name: {e}")
        
        # Functions from cr_functions.py
        if function_name == "comment_retrieval":
            return cr_funcs.comment_retrieval(file_path, start_line, end_line)
        elif function_name == "similar_lines_of_code":
            if class_name is None:
                return f"ERROR: similar_lines_of_code requires class_name but could not extract it from {file_path} at lines {start_line}-{end_line}"
            return cr_funcs.top_k_code_snippets(file_path, start_line, end_line, class_name, self.information, self.context_info)
        elif function_name == "similar_function_name":
            if class_name is None:
                return f"ERROR: similar_function_name requires class_name but could not extract it from {file_path} at lines {start_line}-{end_line}"
            _, formatted_results_str = cr_funcs.top_k_class_signatures(file_path, start_line, end_line, class_name, self.information, self.context_info)
            return formatted_results_str
        elif function_name == "all_variables_in_class":
            return f"all_variables_in_class called successfully for {file_path} with bug location ({start_line}, {end_line})"
        elif function_name == "test_failure_check":
            return f"test_failure_check called successfully for {file_path} (no arguments needed)"
        elif function_name == "one_hop_api_retrieval":
            if start_line is None or end_line is None or variable is None:
                return f"ERROR: one_hop_api_retrieval requires start_line, end_line, and var arguments. Provided: start_line={start_line}, end_line={end_line}, var={variable}"
            return cr_funcs.one_hop_api_retrieval(file_path, start_line, end_line, variable, self.information)
        elif function_name == "get_callers":
            if start_line is None or end_line is None:
                return f"ERROR: get_callers requires start_line and end_line arguments. Provided: start_line={start_line}, end_line={end_line}"
            if class_name is None:
                return f"ERROR: get_callers requires class_name but could not extract it from {file_path} at lines {start_line}-{end_line}"
            return cr_funcs.get_callers(file_path, start_line, end_line, self.information, class_name)
        elif function_name == "get_callees":
            if start_line is None or end_line is None:
                return f"ERROR: get_callees requires start_line and end_line arguments. Provided: start_line={start_line}, end_line={end_line}"
            if class_name is None:
                return f"ERROR: get_callees requires class_name but could not extract it from {file_path} at lines {start_line}-{end_line}"
            return cr_funcs.get_callees(file_path, start_line, end_line, self.information, class_name)
        else:
            return f"Unknown function: {function_name} for {file_path}"


class SummaryAgent(RoutedAgent):
    """Agent that summarizes context retrieval results."""
    
    def __init__(self, model_client: ChatCompletionClient):
        super().__init__("Summary Agent")
        self._model_client = model_client
        
        # System message for SummaryAgent
        system_message = SystemMessage(content="""You are a summary agent. Your job is to summarize the CURRENT context retrieval attempt in a structured format.

You will receive:
1. Full message thread from context retrieval agent (contains all rounds' results, reasoning, and context including past repair attempts and failed tests).
The first system message is a summary of past retrieval attempts and failed tests, and should be ignored. The current attempt is all messages after the first system message.

Your task is to format the summary EXACTLY as follows (ONLY for the current attempt):

  file_path:
    - function_name: results
    - function_name: results
  file_path2:
    - function_name: results
    - function_name: results
  These functions were called to [one sentence describing the purpose based on the reasoning].

IMPORTANT FORMATTING NOTES:
- Do NOT include "Attempt X:" or "Current attempt:" - that will be added later
- Do NOT include past summaries - only summarize the current attempt
- Indent file paths with 2 spaces
- Indent function names with 4 spaces and use "- " prefix
- Show full results for all functions (including long lists like all_funcs_in_class)
- TODO: Later we will filter long lists to show only top k relevant items based on bug context
- End with "These functions were called to [one sentence]" describing the purpose

Format the summary clearly and concisely.""")
        
        self._context = UnboundedChatCompletionContext(initial_messages=[system_message])
    
    @message_handler
    async def on_task(self, message: SummaryTask, ctx: MessageContext) -> SummaryResponse:
        """Summarize context retrieval results for the CURRENT attempt only."""
        
        # Add instruction message with the formatted function results
        instruction_content = f"""Please summarize the CURRENT context retrieval attempt based on the following information:

{message.function_results}

CRITICAL: Each retrieval attempt contains multiple rounds. You must include ALL functions from ALL rounds in your summary.

Format the summary as follows:
- file_path:
  - function_name: results
  - function_name: results
- file_path2:
  - function_name: results
  - function_name: results
These functions were called to [1-2sentence describing the purpose based on the reasoning from ALL rounds].

IMPORTANT FORMATTING NOTES:
- Scan through the ENTIRE input above and find ALL "round X:" sections
- Include ALL functions from ALL rounds you find (round 1, round 2, round 3, etc.)
- Indent file paths with 2 spaces
- Indent function names with 4 spaces and use "- " prefix
- Show full results for all functions (including long lists like all_funcs_in_class)
- TODO: Later we will filter long lists to show only top k relevant items based on bug context
- End with "These functions were called to [1-2 sentences]" describing the purpose across all rounds"""
        
        instruction_message = UserMessage(
            content=instruction_content,
            source="system"
        )
        await self._context.add_message(instruction_message)
        
        # Get all messages (including system message and added messages)
        messages = await self._context.get_messages()
        
        # Call LLM
        llm_result = await self._model_client.create(
            messages=messages,
            cancellation_token=ctx.cancellation_token,
        )
        
        summary = llm_result.content
        
        # Add assistant response to context
        assistant_message = AssistantMessage(content=summary, source=self.id.key)
        await self._context.add_message(assistant_message)
        
        return SummaryResponse(summary=summary)