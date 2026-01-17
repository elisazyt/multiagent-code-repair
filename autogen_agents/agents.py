import os
import sys
from openai import AsyncOpenAI
from autogen_core import AgentId, MessageContext, RoutedAgent, message_handler
from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage, AssistantMessage
from autogen_core.model_context import UnboundedChatCompletionContext

from data_classes import PatchingTask, PatchingResponse, TestingTask, TestingResponse
import agent_helpers as helpers

from info_dict import InfoDict
import patch_utils as p_utils

# Add parent directory to path to import test_suites
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_suites import test_suites as ts


class AdminAgent(RoutedAgent):
    def __init__(self, description: str, receiver_instances: dict[str, list[AgentId]], system_message: SystemMessage):
        super().__init__(description)
        self.patching_instances = receiver_instances["patching"]
        self.testing_instances = receiver_instances["testing"]
        
        # Context for logging all messages that pass through AdminAgent
        # Initialize with system message as the first message
        self._context = UnboundedChatCompletionContext(initial_messages=[system_message])
    
    def get_context(self) -> UnboundedChatCompletionContext:
        """Get the message context for logging/debugging"""
        return self._context

    @message_handler
    async def process_patching_tasks(self, message: PatchingTask, ctx: MessageContext) -> PatchingResponse:
        print(f"Patching task received by agent with patcher_id: {message.patcher_id}.")
        
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
            f"TestingResponse (patcher_id={testing_response.patcher_id}, success={testing_response.success}): {testing_response.result}",
            role="assistant",
            source="testing"
        )
        
        # Just return the testing response - run_patch_test_loop handles regeneration logic
        return testing_response


class PatchingAgent(RoutedAgent):
    # Class variable to store instances by their key (shared across all instances)
    _instances_dict = {}
    
    def __init__(self, description: str, model_client: ChatCompletionClient, information: InfoDict, role_description: dict[str, str]):
        super().__init__(description)
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
    async def add_test_result(self, test_result: str, success: bool, source: str = "testing"):
        """Add a test result to the conversation context"""
        # Format the test result message
        if success:
            result_message = f"All test suites passed. Here are the testing results: {test_result}"
        else:
            result_message = f"One or more test suites failed. Here are the testing results: {test_result}"
        
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


# TODO: can remove the OpenAI client since this agent doesn't need to make API calls
class TestingAgent(RoutedAgent):
    def __init__(self, description: str, information: InfoDict):
        super().__init__(description)
        self.information = information
    
    @message_handler
    async def on_task(self, message: TestingTask, ctx: MessageContext) -> TestingResponse:        
        mapping = message.mapping

        project_name = self.information.get_info("project name")
        bug_id = self.information.get_info("bug id")
        working_directory = self.information.get_info("working directory")
        test_result = ts.run_defects4j_test(project_name, bug_id, working_directory, mapping)

        failing_test_info_string = ""
        all_tests_passed = True

        # test_result is a dict with keys 'success' and 'failing_tests'
        if 'error' in test_result:
            all_tests_passed = False
            failing_test_info_string = test_result['error']
        else:
            if test_result['success'] == False:
                all_tests_passed = False
                failing_test_info_string += 'Error: Test command did not run. Check for possible errors such as compile errors.'
            if len(test_result['failing_tests']) > 0:
                all_tests_passed = False
                # Reconstruct working_dir from checkout_dir, project_name, and bug_id
                checkout_dir = self.information.get_info("working directory")
                project_name = self.information.get_info("project name")
                bug_id = self.information.get_info("bug id")
                working_dir = os.path.join(checkout_dir, f"{project_name.lower()}{bug_id}")
                failing_test_info_string += ts.get_failing_test_info(working_dir, project_name, test_result['failing_tests'])
                failing_test_info_string += '\n'
        
        if all_tests_passed:
            return TestingResponse(patcher_id=message.patcher_id, success=True, result="All test suites passed.")
        else:
            return TestingResponse(patcher_id=message.patcher_id, success=False, result=failing_test_info_string)