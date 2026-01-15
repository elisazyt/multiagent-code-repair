import os
from openai import AsyncOpenAI
from autogen_core import AgentId, MessageContext, RoutedAgent, message_handler
from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage, AssistantMessage
from autogen_core.model_context import UnboundedChatCompletionContext

from data_classes import PatchingTask, PatchingResponse, TestingTask, TestingResponse
from agent_helpers import log_message


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
        await log_message(
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
        await log_message(
            self._context,
            f"PatchingResponse (patcher_id={patching_response.patcher_id}): {patching_response.response}",
            role="assistant",
            source=patching_response.patcher_id
        )
        
        return patching_response
    
    @message_handler
    async def process_testing_task(self, message: TestingTask, ctx: MessageContext) -> TestingResponse:
        # Ensure system message is added once
        # Log incoming testing task (source is the sender, or "main" if None)
        sender_key = ctx.sender.key if ctx.sender else "main"
        await log_message(
            self._context,
            f"TestingTask (patcher_id={message.patcher_id}): {message.message}",
            role="user",
            source=sender_key
        )
        
        testing_response = await self.send_message(message, self.testing_instances[0])
        
        # Log testing response (source is the testing agent)
        await log_message(
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
    
    def __init__(self, description: str, model_client: ChatCompletionClient, system_message: SystemMessage):
        super().__init__(description)
        self._model_client = model_client
        self._system_message = system_message
        
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
        
        # Get assistant response
        generated_result = llm_result.content
        print(f"Generated result: {generated_result}")
        
        # Add assistant response to context (for next round)
        assistant_message = AssistantMessage(content=generated_result, source=self.id.key)
        await self._context.add_message(assistant_message)

        # Return the generated result - AdminAgent will handle sending to TestingAgent
        return PatchingResponse(patcher_id=message.patcher_id, response=generated_result)
    
    async def add_test_result(self, test_result: str, success: int, source: str = "testing"):
        """Add a test result to the conversation context"""
        # Format the test result message
        if success == 1:
            result_message = f"Test passed: {test_result}"
        elif success == 0:
            result_message = f"Test failed: {test_result}"
        else:  # success == 2
            result_message = f"Test didn't run/compile: {test_result}"
        
        # Use the general log_message utility function
        await log_message(
            self._context,
            f"Testing feedback: {result_message}",
            role="user",
            source=source
        )


class TestingAgent(RoutedAgent):
    def __init__(self, description: str):
        super().__init__(description)
        # Initialize OpenAI async client
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        self.client = AsyncOpenAI(api_key=api_key)
    
    @message_handler
    async def on_task(self, message: TestingTask, ctx: MessageContext) -> TestingResponse:        
        model = os.environ.get("GPT_MODEL", "gpt-4o-mini")
        
        response = await self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": message.message}]
        )
        
        result_text = f"Testing result: {response.choices[0].message.content}"

        # TODO: determine if test passed, failed, or didn't run/compile. temporarily set to 1 for testing.
        return TestingResponse(patcher_id=message.patcher_id, success=1, result=result_text)