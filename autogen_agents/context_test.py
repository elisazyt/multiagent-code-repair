import asyncio
import os
from dotenv import load_dotenv
from autogen_core import AgentId, MessageContext
from autogen_ext.models.openai import OpenAIChatCompletionClient
from agents import ContextRetrievalAgent
from data_classes import ContextRetrievalTask
from info_dict import InfoDict, ContextDict
from agent_helpers import save_message_thread

# Load environment variables from .env file
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)


async def test_context_retrieval():
    # Create model client
    model_client = OpenAIChatCompletionClient(
        model=os.environ.get("GPT_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("OPENAI_API_KEY")
    )
    
    # Create InfoDict with bug information
    closure8_path = os.path.join(project_root, "ALL_TESTS", "closure8.java")
    
    # Get checkout directory from .env file
    checkout_directory = os.getenv('CHECKOUT_DIR')
    if not checkout_directory:
        raise ValueError("CHECKOUT_DIR not set in .env file.")
    checkout_directory = os.path.abspath(checkout_directory)
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
    
    # Create ContextDict initialized from InfoDict
    context_info = ContextDict(info_dict=information)
    
    # Create ContextRetrievalAgent
    role_description = """You are a context retrieval agent. Your job is to retrieve relevant context information 
    for bug fixing. You can request context retrieval functions for specific files. Only request functions that are 
    actually needed to understand and fix the bug."""
    
    agent = ContextRetrievalAgent(
        description="test_context_agent",
        model_client=model_client,
        context_info=context_info,
        role_description=role_description,
        past_summary=""
    )
    
    # Create a test task
    task = ContextRetrievalTask(retrieval_attempt=1, repair_summary="")
    
    # Create MessageContext
    sender = AgentId("admin", "admin_agent")
    ctx = MessageContext(
        sender=sender,
        topic_id="test_topic",
        is_rpc=False,
        message_id="test_msg_1",
        cancellation_token=None
    )
    
    # Call the agent
    print("Testing ContextRetrievalAgent...")
    response = await agent.on_task(task, ctx)
    
    print(f"\nResponse received:")
    print(f"  Retrieval attempt: {response.retrieval_attempt}")
    print(f"  Function results length: {len(response.function_results)} characters")
    print(f"\nFunction results preview:\n{response.function_results[:500]}...")
    
    # Save the conversation history to a file
    await save_message_thread(
        agent._context,
        agent_id="context_test",
        information=information
    )
    
    await model_client.close()


if __name__ == "__main__":
    asyncio.run(test_context_retrieval())
