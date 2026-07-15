import argparse
import asyncio
import os
import sys
from dotenv import load_dotenv
from autogen_core import AgentId, SingleThreadedAgentRuntime
from autogen_ext.models.openai import OpenAIChatCompletionClient

load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.agents.agents import (
    AdminAgent,
    PatchingAgent,
    TestingAgent,
    ContextRetrievalAgent,
    SummaryAgent,
    SelectionAgent,
)
from src.agents.helpers.agent_helpers import run_patch_test_loop, save_all_message_threads
from src.agents.data_structures.data_classes import SelectionTask
from src.agents.data_structures.dicts import BugDict, ContextDict

# Note: these can be changed, but note that there are some parts of the prompt enclosed by {} which
# are placeholders for content that will be filled in when the agent is initialized
# Changing the prompt may break the program if the placeholders can't be correctly populated
from agents.prompts import (
    PATCHING_SYSTEM_PROMPT,
    BASIC_PROMPT,
    COT_PROMPT,
    PATTERN_PROMPT,
    CONTEXT_PROMPT,
    CONTEXT_RETRIEVAL_PROMPT,
    SUMMARY_PROMPT,
    SELECTION_PROMPT,
)

import time
"""
User-specified variables (via CLI arguments, otherwise use default):
"""
parser = argparse.ArgumentParser(description="Run the multi-agent program repair pipeline.")
parser.add_argument(
    "--results-root",
    default=os.path.join(project_root, "results"),
    help="Root folder for all results (chat logs, patches, checkouts, etc.). Default: <repo>/results",
)
parser.add_argument(
    "--project-name",
    default="Chart",
    help="Defects4J project name to patch. Must be one of the following: Chart, Closure, Lang, Math, Mockito, Time",
)
parser.add_argument(
    "--bug-id",
    default="1",
    help="Defects4J bug ID to patch. Should be a number"
)
parser.add_argument(
    "--num-patching-attempts",
    type=int,
    default=3,
    help="Number of patching attempts per agent, each attempt consists of calling the agent and testing the patch. Default: 3",
)
parser.add_argument(
    "--num-retrieval-rounds",
    type=int,
    default=2,
    help="Number of context retrieval rounds per attempt, specifically for the ContextRetrievalAgent. Default: 2",
)
args = parser.parse_args()

# one root folder with all the results that the user should specify. default is a folder in this repo
RESULTS_ROOT = args.results_root
# Number of patching attempts per agent, each attempt consists of calling the agent and testing the patch
NUM_PATCHING_ATTEMPTS = args.num_patching_attempts
# Number of context retrieval rounds per attempt, specifically for the ContextRetrievalAgent
NUM_RETRIEVAL_ROUNDS = args.num_retrieval_rounds
# project name and bug id to patch
PROJECT_NAME = args.project_name
BUG_ID = args.bug_id

"""
Construct all remaining paths, which are all subfolders of RESULTS_ROOT:
"""
# path to folder containing bm25 index and corresponding jsonl file
BM25_PATH = os.path.join(RESULTS_ROOT, "external_tools", "bm25_indexes")
# directory Joern runs from
JOERN_WORKING_DIR = os.path.dirname(os.path.realpath(os.environ.get("JOERN_EXECUTABLE")))
# path to folder containing Joern workspace for CPG generation/storage
JOERN_WORKSPACE_PATH = os.path.join(RESULTS_ROOT, "external_tools", "joern_workspace")
# path to folder where Defects4J projects are checked out, tests are run, etc.
DEFECTS4J_CHECKOUT_PATH = os.path.join(RESULTS_ROOT, "external_tools", "defects4j_checkouts")


async def main():
    print(f"Starting program...")
    start_time = time.perf_counter()
    runtime = SingleThreadedAgentRuntime()

    receiver_instances = {
        "patching": [
            AgentId("patching", "basic"),
            AgentId("patching", "cot"),
            AgentId("patching", "context"),
            AgentId("patching", "pattern"),
        ],
        "testing": [AgentId("testing", "testing")],
        "context_retrieval": [AgentId("context_retrieval", "context_retrieval")],
        "summary": [AgentId("summary", "summary")],
        "selection": [AgentId("selection", "selection")],
    }

    # Create model client (shared across all agents)
    model_client = OpenAIChatCompletionClient(
        model=os.environ.get("GPT_MODEL"),
        api_key=os.environ.get("OPENAI_API_KEY"),
    )

    # Create BugDict for the given bug (shared by all patching agents)

    bug_dict = BugDict()
    bug_dict.add_project_info(PROJECT_NAME, BUG_ID)
    bug_dict.add_paths(
        results_path=RESULTS_ROOT,
        bm25_path=BM25_PATH,
        joern_executable=os.environ.get("JOERN_EXECUTABLE"),
        joern_working_dir=JOERN_WORKING_DIR,
        joern_workspace_path=JOERN_WORKSPACE_PATH,
        defects4j_checkout_path=DEFECTS4J_CHECKOUT_PATH,
    )
    bug_dict.add_bug_locations()

    # Create ContextDict initialized from BugDict
    context_dict = ContextDict(bug_dict=bug_dict)
    bm25_path = bug_dict.get_info("bm25 path")
    jsonl_dir = os.path.join(bm25_path, "jsonl")
    index_dir = os.path.join(bm25_path, "index")

    # Default configs for BM25 search and UniXcoder retrieval. User can change the numerical configs
    # as desired, depending on task complexity, model capabilities, cost/token restrictions, etc
    context_dict.add_bm25_rag_config(
        k_signatures=5,
        jsonl_dir=jsonl_dir,
        index_dir=index_dir,
        k_code_snippets=5,
        window_size=20,
        batch_size=8,
    )

    agent_prompts = {
        "basic": BASIC_PROMPT,
        "cot": COT_PROMPT,
        "context": CONTEXT_PROMPT,
        "pattern": PATTERN_PROMPT,
        "context_retrieval": CONTEXT_RETRIEVAL_PROMPT,
        "summary": SUMMARY_PROMPT,
        "selection": SELECTION_PROMPT,
    }

    # Store reference to AdminAgent and ContextAgent instances so we can access their context later
    admin_agent_instance_ref = None
    context_agent_instance_ref = None

    def admin_agent_factory():
        nonlocal admin_agent_instance_ref
        admin = AdminAgent(receiver_instances, context_dict=context_dict, runtime=runtime)
        admin_agent_instance_ref = admin
        return admin

    # Factory for ContextRetrievalAgent
    def context_agent_factory():
        nonlocal context_agent_instance_ref
        context_agent = ContextRetrievalAgent(
            model_client=model_client,
            context_dict=context_dict,
            bug_dict=bug_dict,
            agent_prompts=agent_prompts,
            num_rounds=NUM_RETRIEVAL_ROUNDS,
        )
        context_agent_instance_ref = context_agent
        return context_agent

    # Register the classes
    await AdminAgent.register(runtime, "admin", admin_agent_factory)
    await PatchingAgent.register(runtime, "patching", lambda: PatchingAgent(model_client, bug_dict, PATCHING_SYSTEM_PROMPT, agent_prompts))
    await TestingAgent.register(runtime, "testing", lambda: TestingAgent(bug_dict))
    await ContextRetrievalAgent.register(runtime, "context_retrieval", context_agent_factory)
    await SummaryAgent.register(runtime, "summary", lambda: SummaryAgent(model_client, agent_prompts))
    await SelectionAgent.register(runtime, "selection", lambda: SelectionAgent(model_client, bug_dict, agent_prompts))

    runtime.start()

    # Create an AdminAgent identifier (not the instance itself)
    admin_agent = AgentId("admin", "admin_agent")

    try:
        # Run all agents' loops in parallel
        # Note: Context retrieval will be run automatically when the context patching agent needs it
        basic_attempts, cot_attempts, context_attempts, pattern_attempts = await asyncio.gather(
            run_patch_test_loop("basic", admin_agent, runtime, num_attempts=NUM_PATCHING_ATTEMPTS),
            run_patch_test_loop("cot", admin_agent, runtime, num_attempts=NUM_PATCHING_ATTEMPTS),
            run_patch_test_loop("context", admin_agent, runtime, num_attempts=NUM_PATCHING_ATTEMPTS, context_dict=context_dict),
            run_patch_test_loop("pattern", admin_agent, runtime, num_attempts=NUM_PATCHING_ATTEMPTS),
        )

        print(f"\nFinal results:")
        print(f"Basic agent completed in {basic_attempts} attempts")
        print(f"Cot agent completed in {cot_attempts} attempts")
        print(f"Context agent completed in {context_attempts} attempts")
        print(f"Pattern agent completed in {pattern_attempts} attempts")

        # All loops are done: select the best candidate among all the patches that passed all test suites
        selection_task = SelectionTask(
            candidate_patches=PatchingAgent.candidate_patches
        )
        await runtime.send_message(selection_task, recipient=admin_agent)
    finally:
        # Regardless of whether the program ran all the way to completion, store the latest
        # message threads for each agent
        await save_all_message_threads(
            bug_dict,
            admin_agent_instance=admin_agent_instance_ref,
            context_agent_instance=context_agent_instance_ref,
        )

        # Calculate total time
        elapsed_seconds = time.perf_counter() - start_time
        total_time = f"Total time taken: {elapsed_seconds:.1f} seconds"
        # Calculate token usage. Note that model_client is shared across all agents, so prompt_tokens
        # and completion_tokens are already the sum of the individual token usages across all agent instances
        usage = model_client.total_usage()
        total_tokens = usage.prompt_tokens + usage.completion_tokens

        # At the end of admin agent's chat messages, add the time and token usage
        admin_log_path = os.path.join(
            bug_dict.get_info("chat context path"),
            f"{bug_dict.get_info('project name')}{bug_dict.get_info('bug id')}_admin_agent.txt",
        )
        with open(admin_log_path, "a", encoding="utf-8") as f:
            f.write(f"{total_time}\n")
            f.write(
                f"Total tokens used: {total_tokens} "
                f"(prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens})\n"
            )

        await model_client.close()
        await runtime.stop_when_idle()
        print(f"Finished running program in {total_time} seconds. Used {total_tokens} total tokens")

if __name__ == "__main__":
    asyncio.run(main())
