import asyncio
import os
import sys
from dotenv import load_dotenv
from autogen_core import AgentId, MessageContext
from autogen_ext.models.openai import OpenAIChatCompletionClient

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
agents_dir = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
for path in (agents_dir, os.path.join(agents_dir, 'helpers'), os.path.join(agents_dir, 'data_structures')):
    if path not in sys.path:
        sys.path.insert(0, path)

from agents import ContextRetrievalAgent
from data_classes import ContextRetrievalTask
from dicts import BugDict, ContextDict
from agent_helpers import save_message_thread

# Load environment variables from .env file
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)


async def test_context_retrieval():
    # Create model client
    model_client = OpenAIChatCompletionClient(
        model=os.environ.get("GPT_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("OPENAI_API_KEY")
    )
    
    # Create BugDict with bug information
    closure8_path = os.path.join(project_root, "tests", "ALL_TESTS", "closure8.java")

    bug_dict = BugDict()
    bug_dict.add_project_info("Closure", "8")
    results_path = os.path.join(project_root, "tests", "test_results")
    bm25_path = os.path.join(results_path, "external_tools", "bm25_indexes")
    joern_executable = os.environ.get("JOERN_EXECUTABLE", "/opt/homebrew/bin/joern")
    joern_working_dir = os.path.dirname(os.path.realpath(joern_executable))
    bug_dict.add_paths(
        results_path=results_path,
        bm25_path=bm25_path,
        joern_executable=joern_executable,
        joern_working_dir=joern_working_dir,
        joern_workspace_path=os.path.join(results_path, "external_tools", "joern_workspace"),
        defects4j_checkout_path=os.path.join(results_path, "external_tools", "defects4j_checkouts"),
    )
    bug_dict.add_bug_locations([(closure8_path, [(202, 205)])])

    context_dict = ContextDict(bug_dict=bug_dict)
    bm25_run = bug_dict.get_info("bm25 path")
    context_dict.add_bm25_rag_config(
        k_signatures=5,
        jsonl_dir=os.path.join(bm25_run, "jsonl"),
        index_dir=os.path.join(bm25_run, "index"),
        k_code_snippets=5,
        window_size=20,
        batch_size=8,
    )
    
    # Create ContextRetrievalAgent
    role_description = """You are a context retrieval agent. Your job is to retrieve relevant context information 
    for bug fixing. You can request context retrieval functions for specific files. Only request functions that are 
    actually needed to understand and fix the bug."""
    
    agent = ContextRetrievalAgent(
        model_client=model_client,
        context_dict=context_dict,
        role_description=role_description,
        past_summary="",
        bug_dict=bug_dict,
    )
    
    # Create a test task
    task = ContextRetrievalTask(retrieval_attempt=1)
    
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
        agent.chat_messages,
        agent_id="context_test",
        bug_dict=bug_dict
    )
    
    await model_client.close()


if __name__ == "__main__":
    asyncio.run(test_context_retrieval())
