import os
import shutil
import sys
from autogen_core import AgentId, MessageContext, RoutedAgent, message_handler
from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage, AssistantMessage
from autogen_core.model_context import UnboundedChatCompletionContext

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from agents.data_structures.data_classes import (
    PatchingTask,
    PatchingResponse,
    TestingTask,
    TestingResponse,
    ContextRetrievalTask,
    ContextRetrievalResponse,
    SelectionTask,
    SelectionResponse,
    SummaryTask,
    SummaryResponse,
)
from agents.helpers import agent_helpers as helpers
from agents.data_structures.dicts import BugDict, ContextDict
from agents.helpers import patch_utils
from agents.helpers.function_call import create_context_retrieval_function
from agents.helpers import cr_functions as cr_funcs

from tools.test_suites import test_suites as ts

# TODO: maybe add something to track start and end time and calculate total time taken?

class AdminAgent(RoutedAgent):
    def __init__(self, receiver_instances: dict[str, list[AgentId]], system_message: SystemMessage, context_dict: ContextDict = None, runtime = None):
        super().__init__("Admin Agent")
        self.patching_instances = receiver_instances.get("patching", [])
        self.testing_instances = receiver_instances.get("testing", [])
        self.context_instances = receiver_instances.get("context", [])
        self.summary_instances = receiver_instances.get("summary", [])
        self.selection_instances = receiver_instances.get("selection", [])
        self.context_dict = context_dict
        self.runtime = runtime
        
        # LLM chat history for logging all messages that pass through AdminAgent
        self.chat_messages = UnboundedChatCompletionContext(initial_messages=[system_message])
    
    def get_chat_messages(self) -> UnboundedChatCompletionContext:
        """Get the LLM chat message history for logging/debugging"""
        return self.chat_messages

    @message_handler
    async def process_patching_tasks(self, message: PatchingTask, ctx: MessageContext) -> PatchingResponse:
        print(f"Patching task received by agent with patcher_id: {message.patcher_id}.")
        
        # If this is a context patching request, route to context patching handler
        if message.patcher_id == "context":
            return await self.process_context_patching_task(message, ctx)
        
        # Log incoming patching task (source is the sender, or "main" if None)
        sender_key = ctx.sender.key if ctx.sender else "main"
        await helpers.log_message(
            self.chat_messages,
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

        # For now, the task is predefined. Later, we will pass in some BugDict or similar object and construct the prompt
        patching_response = await self.send_message(message, patching_instance)
        
        # Log patching response (source is the patching agent that generated it)
        await helpers.log_message(
            self.chat_messages,
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
            self.chat_messages,
            f"TestingTask (patcher_id={message.patcher_id}): Run test suites on the patched files",
            role="user",
            source=sender_key
        )
        
        testing_response = await self.send_message(message, self.testing_instances[0])
        
        # Log testing response (source is the testing agent)
        await helpers.log_message(
            self.chat_messages,
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
            self.chat_messages,
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
            self.chat_messages,
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
            self.chat_messages,
            f"SummaryTask (retrieval_attempt={message.retrieval_attempt}): Summarize context retrieval results",
            role="user",
            source=sender_key
        )
        
        if not self.summary_instances:
            raise ValueError("No summary instances available")
        
        summary_response = await self.send_message(message, self.summary_instances[0])
        
        # Log summary response
        await helpers.log_message(
            self.chat_messages,
            f"SummaryResponse (retrieval_attempt={message.retrieval_attempt}): {summary_response.summary}",
            role="assistant",
            source="summary"
        )
        
        return summary_response
    
    @message_handler
    async def process_selection_task(self, message: SelectionTask, ctx: MessageContext) -> SelectionResponse:
        # Log incoming selection task (source is the sender, or "main" if None)
        sender_key = ctx.sender.key if ctx.sender else "main"
        await helpers.log_message(
            self.chat_messages,
            f"SelectionTask: select the best of {len(message.candidate_patches)} candidate patches",
            role="user",
            source=sender_key
        )

        if not self.selection_instances:
            raise ValueError("No selection instances available")

        selection_response = await self.send_message(message, self.selection_instances[0])

        # Log selection response
        await helpers.log_message(
            self.chat_messages,
            f"SelectionResponse: {selection_response.selected_patch_description}",
            role="assistant",
            source="selection"
        )

        return selection_response

    async def process_context_patching_task(self, message: PatchingTask, ctx: MessageContext) -> PatchingResponse:
        """
        Handle context patching: first retrieve context, then send patching task with context summary.
        Note: This is not a @message_handler because it's called from process_patching_tasks.
        """
        print(f"[context_patching] Starting context patching for agent: {message.patcher_id}")
        
        # Log incoming context patching task
        sender_key = ctx.sender.key if ctx.sender else "main"
        await helpers.log_message(
            self.chat_messages,
            f"ContextPatchingTask (patcher_id={message.patcher_id}): {message.message}",
            role="user",
            source=sender_key
        )
        
        # Step 1: Run context retrieval to get context summary for this patching attempt
        if not self.context_dict or not self.runtime:
            raise ValueError("context_dict and runtime must be provided to AdminAgent for context patching")
        
        # Use the patching attempt number as the attempt number for context retrieval
        # Each patching attempt gets its own context retrieval attempt (up to 3 rounds of retrieval)
        attempt_num = message.patching_attempt
        print(f"[context_patching] Running context retrieval for patching attempt {attempt_num} (context retrieval attempt {attempt_num})")
        context_summary = await helpers.run_single_attempt_context(
            attempt_num=attempt_num,
            admin_agent=self.id,
            runtime=self.runtime,
            context_dict=self.context_dict
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
            self.chat_messages,
            f"PatchingResponse (patcher_id={patching_response.patcher_id}): {patching_response.result}",
            role="assistant",
            source=patching_response.patcher_id
        )
        
        return patching_response


class PatchingAgent(RoutedAgent):
    # Class variable to store instances by their key (shared across all instances)
    instances_dict = {}
    # Class variable to store all candidate patch info (i.e., the dict returned by save_candidate_patch)
    #  across all runs, for all patching agent instances
    candidate_patches = []
    
    def __init__(self, model_client: ChatCompletionClient, bug_dict: BugDict, role_descriptions: dict[str, str]):
        super().__init__("Patching Agent")
        # create OpenAI chat completion client
        self.model_client = model_client

        self.bug_dict = bug_dict
        
        # role_descriptions can be a string or a dict mapping agent keys to role description strings
        # If it's a dict, look up the role description based on self.id.key (set by super().__init__)
        agent_key = self.id.key
        if agent_key in role_descriptions:
            self.role_description = role_descriptions[agent_key]
        else:
            raise ValueError(f"Agent key '{agent_key}' not found in role_descriptions dict. Available keys: {list(role_descriptions.keys())}")
        
        # Create system message with the role description
        # For context patching agent, context_summary will be added as a UserMessage in on_task
        self.system_message = helpers.get_system_message(bug_dict, self.role_description)
        
        # Each agent instance has its own LLM chat history (manages messages automatically)
        self.chat_messages = UnboundedChatCompletionContext(initial_messages=[self.system_message])

    @message_handler
    # When runtime.send_message is called with an argument of type Task, this on_task method is called
    # The response of send_message is a TaskResponse object
    async def on_task(self, message: PatchingTask, ctx: MessageContext) -> PatchingResponse:
        # Store this instance in the class dictionary (shared across all instances)
        if self.id.key not in PatchingAgent.instances_dict:
            PatchingAgent.instances_dict[self.id.key] = self
        
        # If context_summary is provided, recreate the system message with context summary included
        # This is for context patching agent
        if message.context_summary:
            # Get existing messages to preserve conversation history
            existing_messages = await self.chat_messages.get_messages()
            
            # Recreate system message with context summary
            self.system_message = helpers.get_system_message(
                self.bug_dict, 
                self.role_description, 
                context_summary=message.context_summary
            )
            
            # Recreate context with new system message, preserving all non-system messages
            # Filter out the old system message and keep everything else
            other_messages = [msg for msg in existing_messages if not isinstance(msg, SystemMessage)]
            self.chat_messages = UnboundedChatCompletionContext(initial_messages=[self.system_message] + other_messages)
        
        # Create UserMessage for this request
        # Use the actual sender's key (e.g., "admin_agent") instead of receiver's key
        sender_key = ctx.sender.key if ctx.sender else "unknown"
        # Format message consistently with AdminAgent's logging format
        formatted_content = f"PatchingTask (patcher_id={message.patcher_id}): {message.message}"
        user_message = UserMessage(content=formatted_content, source=sender_key)
        
        # Add user message to context (context automatically tracks it)
        await self.chat_messages.add_message(user_message)
        
        # Get all messages from context (includes system + all history automatically)
        messages = await self.chat_messages.get_messages()
        
        # Call LLM with full conversation history
        llm_result = await self.model_client.create(
            messages=messages,
            cancellation_token=ctx.cancellation_token,
        )
        
        result_text = llm_result.content
        # Save patches and get mapping of modified_source_name -> (patch_file_path, patched_nodes)
        print(f"--------------------------------")
        print(f"result_text: {result_text}")
        print(f"--------------------------------")
        patch_mapping = self.save_patch(result_text, patching_attempt=message.patching_attempt)

        # Add assistant response to context (for next round)
        assistant_message = AssistantMessage(content=result_text, source=self.id.key)
        await self.chat_messages.add_message(assistant_message)

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
            result_message = f"One or more test suites failed, or was unable to run. Here are the testing results: {test_str_result}"
        
        # Use the general log_message utility function
        await helpers.log_message(
            self.chat_messages,
            f"Feedback from test suites: {result_message}",
            role="user",
            source=source
        )

    def save_patch(self, response: str, patching_attempt: int) -> dict[str, tuple[str, list[str]]]:
        """
        Save patches to the directory for generated patches and return mapping of
        modified_source_name -> (patch_file_path, patched_nodes).
        
        Args:
            response: The agent's response containing markdown code blocks
            patching_attempt: Patch attempt number (1, 2, 3, ...) appended to each filename

        Returns:
            dict mapping modified_source_name -> (patch_file_path, patched_nodes)
        """
        bug_files_and_locations = self.bug_dict.get_info("bug files and locations")
        unique_node_locations_per_file = self.bug_dict.get_info("unique node locations per file")
        generated_patches_dir = os.path.join(
            self.bug_dict.get_info("generated patches path"),
            self.id.key,
        )
        os.makedirs(generated_patches_dir, exist_ok=True)
        try:
            patch_mapping = patch_utils.apply_all_patches(
                bug_files_and_locations,
                response,
                unique_node_locations_per_file,
                generated_patches_dir=generated_patches_dir,
                patching_attempt=patching_attempt,
            )
        except Exception as e:
            print(f"[ERROR] Failed to apply patches for {self.id.key}: {e}")
            patch_mapping = {}

        return patch_mapping
    
    def save_candidate_patch(self, patch_mapping: dict[str, tuple[str, list[str]]]):
        """
        Given a patch mapping of a patch that has passed all test suites, save the full patched files
        under candidate_patches/{bug project and id}/{patcher id}/
        Stores full patch info in the PatchingAgent.candidate_patches list.
        Full patch info includes: type of patching agent, modified source name, corresponding short filename,
        path to entire patched file, and list of patched nodes per file
        """
        def get_short_filename(modified_source_name: str) -> str:
            """
            Given the full modified source name, return the short filename (without the package name)
            e.g., "com.google.javascript.jscomp.TypeCheck" -> "TypeCheck.java"
            """
            return modified_source_name.rsplit(".", 1)[-1] + ".java"
        # 1) Save full patched files in agent-specific directory
        # create the directory for the specific patching agent
        candidate_dir = os.path.join(
            self.bug_dict.get_info("candidate patches path"),
            self.id.key,
        )
        os.makedirs(candidate_dir, exist_ok=True)
        # save files
        for modified_source_name, (patch_file_path, patched_nodes) in patch_mapping.items():
            filename = get_short_filename(modified_source_name)
            shutil.copy2(patch_file_path, os.path.join(candidate_dir, filename))
        
        # 2) Store full patch info as a dict
        patch_info = {}
        # store which agent generated the patch
        patch_info["patcher id"] = self.id.key
        patch_info["files"] = {}
        # populate patch_info["files"] with full patch info for each file (i.e., modified source name)
        for modified_source_name, (patch_file_path, patched_nodes) in patch_mapping.items():
            patch_info["files"][modified_source_name] = {
                "filename": get_short_filename(modified_source_name),
                "patch file path": patch_file_path,
                "patched nodes": patched_nodes,
            }
        self.candidate_patches.append(patch_info)


# TODO: for the purposes of keeping the prompt short, remove the failing test function.
# Just the failing line +/- 5-ish lines should be enough
class TestingAgent(RoutedAgent):
    def __init__(self, bug_dict: BugDict):
        super().__init__("Testing Agent")
        self.bug_dict = bug_dict
    
    @message_handler
    async def on_task(self, message: TestingTask, ctx: MessageContext) -> TestingResponse:   
        # full_mapping is the mapping of modified_source_name -> (patch_file_path, patched_nodes)
        full_mapping = message.mapping
        # extract the mapping of modified_source_name -> patch_file_path
        file_mapping = {modified_source_name: patch_file_path for modified_source_name, (patch_file_path, _) in full_mapping.items()}

        project_name = self.bug_dict.get_info("project name")
        bug_id = self.bug_dict.get_info("bug id")
        # create separate checkout directory for each patching agent
        # to ensure there is no conflict when running tests in parallel
        agent_checkout_dir = os.path.join(
            self.bug_dict.get_info("defects4j checkout root"),
            message.patcher_id,
        )
        reference_dir = self.bug_dict.get_info("defects4j reference checkout path")
        test_result = ts.run_defects4j_test(
            project_name, bug_id, agent_checkout_dir, file_mapping, reference_dir
        )

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
                test_info_string, test_info_list = ts.get_failing_test_info(agent_checkout_dir, project_name, test_result['failing_tests'])
                failing_test_info_string += test_info_string
                failing_test_info_string += '\n'

        if all_tests_passed:
            return TestingResponse(patcher_id=message.patcher_id, success=True, str_result="All test suites passed.", list_result=[])
        else:
            return TestingResponse(patcher_id=message.patcher_id, success=False, str_result=failing_test_info_string, list_result=test_info_list)


class ContextRetrievalAgent(RoutedAgent):
    def __init__(self, model_client: ChatCompletionClient, context_dict: ContextDict, role_description: str, past_summary: str, bug_dict: BugDict):
        super().__init__("Context Retrieval Agent")
        self.context_dict = context_dict
        self.bug_dict = bug_dict
        self.model_client = model_client

        # Initialize CPG if Joern configuration is available
        self.initialize_cpg()

        # Build system message with bug information (if available) and past context
        system_message_content = role_description + "\n\n"
        system_message_content += "You are given the following context information about the bug:\n"
        system_message_content += helpers.format_bug_info(bug_dict) + "\n\n"
        system_message_content += helpers.format_past_context(context_dict, past_summary, bug_dict)
        
        system_message = SystemMessage(content=system_message_content)
        self.chat_messages = UnboundedChatCompletionContext(initial_messages=[system_message])
    
    def initialize_cpg(self):
        """Initialize Joern CPG for the project if it doesn't already exist."""
        import os
        from tools.context_retrieval.parsing_retrieval_funcs.joern_session import JoernSession
        
        # Get Joern configuration from BugDict
        joern_executable = self.bug_dict.get_info("joern executable")
        
        # Get project info
        project_name = self.bug_dict.get_info("project name")
        bug_id = self.bug_dict.get_info("bug id")
        reference_checkout_dir = self.bug_dict.get_info("defects4j reference checkout path")
        
        # Get the first Java file path (for JoernSession initialization)
        bug_locations = self.bug_dict.get_info("bug files and locations")
        if not bug_locations:
            return

        joern_workspace_path = self.bug_dict.get_info("joern workspace path")
        
        # Check if CPG already exists
        cpg_path = os.path.join(joern_workspace_path, "cpg.bin.zip")
        if os.path.exists(cpg_path):
            print(f"[CPG] CPG already exists at {cpg_path}, skipping creation")
            return
        
        # Create CPG
        print(f"[CPG] CPG not found at {cpg_path}, creating it...")
        joern_session = JoernSession(
            joern_executable,
            joern_workspace_path,
            self.bug_dict.get_info("joern working dir"),
        )
        success = joern_session.create_cpg_from_defects4j(
            project_name=project_name,
            bug_id=bug_id,
            reference_checkout_dir=reference_checkout_dir,
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
                self.context_dict.add_round2_functions()

            # Call LLM for this round
            messages = await self.chat_messages.get_messages()
            llm_result = await self.model_client.create(
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

            if not helpers.is_valid_format(file_functions):
                await self.chat_messages.add_message(UserMessage(
                    content=(
                        f"Error in Round {round}: Function requests were returned in the wrong format. "
                        f"See the example in the system prompt: each file path must map to a list of function calls, "
                        f"e.g. \"file.java\": [{{\"comment_retrieval\": {{\"start_line\": 1, \"end_line\": 2}}}}]. "
                        f"Your reasoning was: {reasoning}."
                    ),
                    source="system",
                ))
                print(f"[WARNING] Round {round} - Invalid file_functions format: {file_functions}")
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
            available_functions_dict = self.context_dict.get_available_functions()
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
                        self.context_dict.remove_function(function_name, file_path)
            
            # Add state summary at the END of the round (after results are stored)
            # Format current round results as string and append to all_retrieval_results
            # Pass only the current round's results (as a list with one element) and the round number
            current_round_results_string = helpers.format_current_context([current_round_results], reasoning, self.context_dict, round_num=round)
            await self.chat_messages.add_message(UserMessage(content=current_round_results_string, source="system"))
            all_retrieval_results += current_round_results_string
            
            # Check if any functions are still available - if not, break early
            available_functions_dict = self.context_dict.get_available_functions()
            # Check if any file has any available functions
            has_available = any(funcs for funcs in available_functions_dict.values())
            
            if not has_available:
                # No functions available - break early
                await self.chat_messages.add_message(UserMessage(
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
        
        # Get class name for functions that need it (e.g., get_callers)
        # Use tree-sitter when line numbers are available for accurate class detection
        class_name = None
        if start_line is not None and end_line is not None:
            try:
                from tools.context_retrieval.parsing_retrieval_funcs import tree_sitter_utils
                bug_location = (start_line, end_line)
                class_name = tree_sitter_utils.extract_class_name_from_file(file_path, bug_location)
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
            return cr_funcs.top_k_code_snippets(file_path, start_line, end_line, class_name, self.bug_dict, self.context_dict)
        elif function_name == "similar_function_name":
            if class_name is None:
                return f"ERROR: similar_function_name requires class_name but could not extract it from {file_path} at lines {start_line}-{end_line}"
            _, formatted_results_str = cr_funcs.top_k_class_signatures(file_path, start_line, end_line, class_name, self.bug_dict, self.context_dict)
            return formatted_results_str
        elif function_name == "all_funcs_in_class":
            if start_line is None or end_line is None:
                return f"ERROR: all_funcs_in_class requires start_line and end_line arguments. Provided: start_line={start_line}, end_line={end_line}"
            return cr_funcs.all_funcs_in_class(file_path, start_line, end_line, self.bug_dict)
        elif function_name == "one_hop_api_retrieval":
            if start_line is None or end_line is None or variable is None:
                return f"ERROR: one_hop_api_retrieval requires start_line, end_line, and var arguments. Provided: start_line={start_line}, end_line={end_line}, var={variable}"
            return cr_funcs.one_hop_api_retrieval(file_path, start_line, end_line, variable, self.bug_dict)
        elif function_name == "get_callers":
            if start_line is None or end_line is None:
                return f"ERROR: get_callers requires start_line and end_line arguments. Provided: start_line={start_line}, end_line={end_line}"
            if class_name is None:
                return f"ERROR: get_callers requires class_name but could not extract it from {file_path} at lines {start_line}-{end_line}"
            return cr_funcs.get_callers(file_path, start_line, end_line, self.bug_dict, class_name)
        else:
            return f"Unknown function: {function_name} for {file_path}"

class SelectionAgent(RoutedAgent):
    """Agent that selects the best candidate patch among those that passed all test suites."""

    def __init__(self, model_client: ChatCompletionClient, role_description: str, bug_dict: BugDict):
        super().__init__("Selection Agent")
        self.model_client = model_client
        self.bug_dict = bug_dict

        # Build system message: role description + bug info, same pattern as the other agents
        system_message_content = role_description + "\n\n"
        system_message_content += "You are given the following context information about the bug:\n"
        system_message_content += helpers.format_bug_info(bug_dict)
        system_message = SystemMessage(content=system_message_content)

        self.chat_messages = UnboundedChatCompletionContext(initial_messages=[system_message])

    def format_candidates(self, candidate_patches: list) -> str:
        """
        Each candidate patch is a dict resulting from PatchingAgent's save_candidate_patch
        List out the patched nodes in a prompt
        Only the patched nodes are included, not the entire patched files, to keep the prompt short
        """
        result = "Here are the candidate patches:\n\n"
        for patch_info in candidate_patches:
            result += f"{'=' * 60}\n"
            result += f"Candidate patch generated by the following agent: {patch_info['patcher id']}\n"
            result += f"{'=' * 60}\n"
            for modified_source_name, file_info in patch_info["files"].items():
                result += f"File: {modified_source_name}\n"
                for node_number, patched_node in enumerate(file_info["patched nodes"], 1):
                    result += f"Patched node #{node_number}:\n"
                    result += f"```java\n{patched_node}\n```\n"
            result += "\n"
        return result

    def save_final_patch(self, patch_info: dict):
        """
        Copy the winning candidate's full patched files into the final patch folder.
        """
        save_dir = self.bug_dict.get_info("final patch path")

        files = patch_info["files"]
        for file_info in files.values():
            # name for patched file: e.g. Lang27_NumberUtils_patch.java
            bug_label = f"{self.bug_dict.get_info('project name')}{self.bug_dict.get_info('bug id')}"
            patch_filename = f"{bug_label}_{file_info['filename'].replace('.java', '')}_patch.java"
            full_filepath = os.path.join(save_dir, patch_filename)
            # copy contents of original patched file under candidate_patches to the final_patch directory
            shutil.copy2(file_info["patch file path"], full_filepath)
            print(f"[selection] Saved final patch to {full_filepath}")

    @message_handler
    async def on_task(self, message: SelectionTask, ctx: MessageContext) -> SelectionResponse:
        """Select the best candidate patch and save its full patched files as the final patch."""
        candidate_patches = message.candidate_patches
        # TODO: figure out what to do in the scenario where no test suites have been passed
        if not candidate_patches:
            print("[selection] No candidate patches passed the test suites, nothing to select.")
            return SelectionResponse(selected_patch_description="No candidate patches passed the test suites, nothing to select.")

        # get the names of only the agents that generated the candidate patches
        candidate_agent_names = [patch_info["patcher id"] for patch_info in candidate_patches]

        if len(candidate_patches) == 1:
            # Only one candidate passed, so there is nothing to compare
            print(f"[selection] Only one candidate ({candidate_agent_names[0]}), selecting it by default.")
            # TODO
            selected_agent_name = candidate_agent_names[0]

        else:
            # Build the prompt: prompt + list of candidate patches
            formatted_task = f"SelectionTask: {message.message}"
            formatted_task += f"\nThe agents that generated the candidate patches are: {', '.join(candidate_agent_names)}."
            formatted_task += f"\nThe candidate patches are:\n{self.format_candidates(candidate_patches)}"
            formatted_task += "\nRemember to respond with the name of the agent that generated the best candidate patch in the first line, and nothing else."
            instruction_message = UserMessage(content=formatted_task, source="system")
            await self.chat_messages.add_message(instruction_message)

            messages = await self.chat_messages.get_messages()
            llm_result = await self.model_client.create(
                messages=messages,
                cancellation_token=ctx.cancellation_token,
            )
            result_text = llm_result.content

            # Add assistant response to context (for logging)
            assistant_message = AssistantMessage(content=result_text, source=self.id.key)
            await self.chat_messages.add_message(assistant_message)

            # TODO: figure out a better way to enforce the agent to respond with exactly what's expected,
            # or maybe try to parse for any agent name in the response as a fallback
            # Parse the best agent: the first line should be exactly one of (basic, context...)
            first_line = result_text.strip().splitlines()[0].strip().strip("\"'`")
            if first_line in candidate_agent_names:
                selected_agent_name = first_line
                print(f"[selection] Selected candidate patch generated by the following agent: {selected_agent_name}")
            else:
                return SelectionResponse(selected_patch_description=f"Could not parse first line '{first_line}' as a patcher id.")

        # Save the selected agent's full patched files under the final patch folder
        final_patch_info = next(patch_info for patch_info in candidate_patches if patch_info["patcher id"] == selected_agent_name)
        self.save_final_patch(final_patch_info)

        # format the selected patch nicely as a string
        final_patch_description = f"Selected patch generated by the following agent: {final_patch_info['patcher id']}"
        final_patch_description += f"\nFinal patch location: {self.bug_dict.get_info('final patch path')}"

        return SelectionResponse(selected_patch_description=final_patch_description)


class SummaryAgent(RoutedAgent):
    """Agent that summarizes context retrieval results."""
    
    def __init__(self, model_client: ChatCompletionClient, role_description: str):
        super().__init__("Summary Agent")
        self.model_client = model_client

        system_message = SystemMessage(content=role_description)
        self.chat_messages = UnboundedChatCompletionContext(initial_messages=[system_message])
    
    @message_handler
    async def on_task(self, message: SummaryTask, ctx: MessageContext) -> SummaryResponse:
        """Summarize context retrieval results for the CURRENT attempt only."""
        
        # Build the user instruction: the summarization prompt from the task + the function results to summarize
        instruction_content = message.message
        instruction_content += f"\n\nHere is the information for the current retrieval attempt:\n\n{message.function_results}"

        instruction_message = UserMessage(
            content=instruction_content,
            source="system"
        )
        await self.chat_messages.add_message(instruction_message)
        
        # Get all messages (including system message and added messages)
        messages = await self.chat_messages.get_messages()
        
        # Call LLM
        llm_result = await self.model_client.create(
            messages=messages,
            cancellation_token=ctx.cancellation_token,
        )
        
        summary = llm_result.content
        
        # Add assistant response to context
        assistant_message = AssistantMessage(content=summary, source=self.id.key)
        await self.chat_messages.add_message(assistant_message)
        
        return SummaryResponse(summary=summary)