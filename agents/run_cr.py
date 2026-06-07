import asyncio
import os
import sys
from dotenv import load_dotenv
from autogen_core import AgentId, SingleThreadedAgentRuntime
from autogen_ext.models.openai import OpenAIChatCompletionClient

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
agents_dir = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
for path in (agents_dir, os.path.join(agents_dir, 'helpers'), os.path.join(agents_dir, 'data_structures')):
    if path not in sys.path:
        sys.path.insert(0, path)

from agents import ContextRetrievalAgent
from agent_helpers import save_message_thread
from dicts import BugDict, ContextDict
from data_classes import ContextRetrievalTask

# Load environment variables from .env file
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)


async def main():
    runtime = SingleThreadedAgentRuntime()

    # Create model client
    model_client = OpenAIChatCompletionClient(
        model=os.environ.get("GPT_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("OPENAI_API_KEY")
    )

    # Create BugDict for closure8 bug
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
            context_dict=context_dict,
            role_description=context_role_description,
            past_summary="",
            bug_dict=bug_dict
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
    context_task = ContextRetrievalTask(retrieval_attempt=1)
    context_response = await runtime.send_message(context_task, recipient=context_agent_id)
    
    print(f"[context] Attempt 1 completed.")
    print(f"\nContext retrieval results:\n{context_response.function_results}")
    
    # Save the ContextRetrievalAgent's message thread
    if context_agent_instance_ref[0] is not None:
        context_agent = context_agent_instance_ref[0]
        await save_message_thread(
            context_agent.chat_messages,
            agent_id="context_retrieval",
            bug_dict=bug_dict
        )

    await model_client.close()
    await runtime.stop_when_idle()


if __name__ == "__main__":
    asyncio.run(main())
