import asyncio
import os
import sys
from autogen_core import AgentId, SingleThreadedAgentRuntime
from autogen_ext.models.openai import OpenAIChatCompletionClient

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from agents.agents import (
    AdminAgent,
    PatchingAgent,
    TestingAgent,
    ContextRetrievalAgent,
    SummaryAgent,
    SelectionAgent,
)
from agents.helpers.agent_helpers import run_patch_test_loop, save_all_message_threads
from agents.data_structures.data_classes import SelectionTask
from agents.data_structures.dicts import BugDict, ContextDict

# Note: these can be changed, but note that there are some parts of the prompt enclosed by {} which
# are placeholders for content that will be filled in when the agent is initialized
# Changing the prompt may break the program if the placeholders can't be correctly populated
from agents.prompt_templates import (
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

########################################################
# TODO: change these for actually running, these are just the test paths
########################################################

# path to folder containing chat_context, candidate_patches, final_patch, generated_patches
RESULTS_PATH = os.path.join(project_root, "tests", "test_results")

# path to folder containing bm25 index and corresponding jsonl file
BM25_PATH = os.path.join(project_root, "tests", "test_results", "external_tools", "bm25_indexes")

# path to Joern executable
JOERN_EXECUTABLE = "/opt/homebrew/bin/joern"

# directory Joern runs from
JOERN_WORKING_DIR = os.path.dirname(os.path.realpath(JOERN_EXECUTABLE))

# path to folder containing Joern workspace for CPG generation/storage
JOERN_WORKSPACE_PATH = os.path.join(project_root, "tests", "test_results", "external_tools", "joern_workspace")

# path to folder where Defects4J projects are checked out, tests are run, etc.
DEFECTS4J_CHECKOUT_PATH = os.path.join(project_root, "tests", "test_results", "external_tools", "defects4j_checkouts")

NUM_PATCHING_ROUNDS = 3

async def main():
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

    # Create model client for PatchingAgent
    model_client = OpenAIChatCompletionClient(
        model=os.environ.get("GPT_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("OPENAI_API_KEY"),
    )

    # Create BugDict for Closure 3 bug (shared by all patching agents)
    project_name = "Math"
    bug_id = "65"

    bug_dict = BugDict()
    bug_dict.add_project_info(project_name, bug_id)
    bug_dict.add_paths(
        results_path=RESULTS_PATH,
        bm25_path=BM25_PATH,
        joern_executable=JOERN_EXECUTABLE,
        joern_working_dir=JOERN_WORKING_DIR,
        joern_workspace_path=JOERN_WORKSPACE_PATH,
        defects4j_checkout_path=DEFECTS4J_CHECKOUT_PATH,
    )
    # TODO: figure out what the path should be
    bug_dict.add_bug_locations([
        (
            "org/apache/commons/math/optimization/general/AbstractLeastSquaresOptimizer.java",
            [(240, 245), (258, 258)],
        ),
    ])

    # Create ContextDict initialized from BugDict
    context_dict = ContextDict(bug_dict=bug_dict)
    bm25_path = bug_dict.get_info("bm25 path")
    jsonl_dir = os.path.join(bm25_path, "jsonl")
    index_dir = os.path.join(bm25_path, "index")
    # TODO: allow user to configure, these are default for now
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
            patching_system_prompt=PATCHING_SYSTEM_PROMPT,
            agent_prompts=agent_prompts,
        )
        context_agent_instance_ref = context_agent
        return context_agent

    # Register the classes
    await AdminAgent.register(runtime, "admin", admin_agent_factory)
    await PatchingAgent.register(runtime, "patching", lambda: PatchingAgent(model_client, bug_dict, agent_prompts))
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
        basic_rounds, cot_rounds, context_rounds, pattern_rounds = await asyncio.gather(
            run_patch_test_loop("basic", admin_agent, runtime, num_rounds=NUM_PATCHING_ROUNDS),
            run_patch_test_loop("cot", admin_agent, runtime, num_rounds=NUM_PATCHING_ROUNDS),
            run_patch_test_loop("context", admin_agent, runtime, num_rounds=NUM_PATCHING_ROUNDS, context_dict=context_dict),
            run_patch_test_loop("pattern", admin_agent, runtime, num_rounds=NUM_PATCHING_ROUNDS),
        )

        print(f"\nFinal results:")
        print(f"Basic agent completed in {basic_rounds} rounds")
        print(f"Cot agent completed in {cot_rounds} rounds")
        print(f"Context agent completed in {context_rounds} rounds")
        print(f"Pattern agent completed in {pattern_rounds} rounds")

        # All loops are done: select the best candidate among all the patches that passed all test suites
        selection_task = SelectionTask(
            candidate_patches=PatchingAgent.candidate_patches,
            message="Select the best candidate patch as described previously.",
        )
        selection_response = await runtime.send_message(selection_task, recipient=admin_agent)
        print(selection_response.selected_patch_description)
    finally:
        elapsed_seconds = time.perf_counter() - start_time
        total_time = f"Total time taken: {elapsed_seconds:.1f} seconds"

        # Regardless of whether the program ran all the way to completion, store the latest
        # message threads for each agent
        await save_all_message_threads(
            bug_dict,
            admin_agent_instance=admin_agent_instance_ref,
            context_agent_instance=context_agent_instance_ref,
        )

        # At the end of admin agent's chat messages, add the total time taken to run the whole program
        admin_log_path = os.path.join(
            bug_dict.get_info("chat context path"),
            f"{bug_dict.get_info('project name')}{bug_dict.get_info('bug id')}_admin_agent.txt",
        )
        with open(admin_log_path, "a", encoding="utf-8") as f:
            f.write(f"{total_time}\n")

        await model_client.close()
        await runtime.stop_when_idle()
        print(total_time)

if __name__ == "__main__":
    asyncio.run(main())
