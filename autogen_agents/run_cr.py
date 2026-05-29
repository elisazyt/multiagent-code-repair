import asyncio
import os
from dotenv import load_dotenv
from autogen_core import AgentId, SingleThreadedAgentRuntime
from autogen_ext.models.openai import OpenAIChatCompletionClient
from agents import ContextRetrievalAgent
from agent_helpers import save_message_thread
from info_dict import InfoDict, ContextDict
from data_classes import ContextRetrievalTask

# Load environment variables from .env file
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)


async def main():
    runtime = SingleThreadedAgentRuntime()

    # Create model client
    model_client = OpenAIChatCompletionClient(
        model=os.environ.get("GPT_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("OPENAI_API_KEY")
    )

    # Create InfoDict for closure8 bug
    closure8_path = os.path.join(project_root, "ALL_TESTS", "closure8.java")
    
    # Get checkout directory from .env file (where Defects4J projects will be checked out)
    checkout_directory = os.getenv('CHECKOUT_DIR')
    if not checkout_directory:
        raise ValueError("CHECKOUT_DIR not set in .env file. Please set it to the directory where Defects4J projects should be checked out.")
    checkout_directory = os.path.abspath(checkout_directory)
    
    # Create checkout directory if it doesn't exist
    os.makedirs(checkout_directory, exist_ok=True)
    
    # working_directory is where Defects4J checkouts will be stored
    working_directory = checkout_directory
    
    information = InfoDict()
    information.add_bug_info(
        project_name="Closure",
        bug_id="8",
        bug_locations=[(closure8_path, [(202, 205)])],
        working_directory=working_directory
    )
    
    # Add Joern configuration
    joern_executable = os.getenv('JOERN_EXECUTABLE')
    joern_directory = os.getenv('JOERN_DIRECTORY')
    if joern_executable and joern_directory:
        information.add_joern_config(joern_executable, joern_directory)
    
    # Create ContextDict initialized from InfoDict
    context_info = ContextDict(info_dict=information)
    
    # Role description for context retrieval agent
    context_role_description = """You are a context retrieval agent. Your job is to retrieve relevant context information 
    for bug fixing. You can request context retrieval functions for specific files. Only request functions that are 
    actually needed to understand and fix the bug."""

    # Store reference to ContextRetrievalAgent instance
    context_agent_instance_ref = [None]
    
    # Factory for ContextRetrievalAgent
    def context_agent_factory():
        context_agent = ContextRetrievalAgent(
            model_client=model_client,
            context_info=context_info,
            role_description=context_role_description,
            past_summary="",
            information=information
        )
        context_agent_instance_ref[0] = context_agent
        return context_agent

    # Register only the ContextRetrievalAgent
    await ContextRetrievalAgent.register(runtime, "context", context_agent_factory)

    runtime.start()

    # Create a ContextRetrievalAgent identifier
    context_agent_id = AgentId("context", "context")

    # Call context retrieval agent directly
    print("[context] Starting context retrieval...")
    context_task = ContextRetrievalTask(retrieval_attempt=1, repair_summary="")
    context_response = await runtime.send_message(context_task, recipient=context_agent_id)
    
    print(f"[context] Attempt 1 completed.")
    print(f"\nContext retrieval results:\n{context_response.function_results}")
    
    # Save the ContextRetrievalAgent's message thread
    if context_agent_instance_ref[0] is not None:
        context_agent = context_agent_instance_ref[0]
        await save_message_thread(
            context_agent._context,
            agent_id="context_retrieval",
            information=information
        )

    await model_client.close()
    await runtime.stop_when_idle()


if __name__ == "__main__":
    asyncio.run(main())
