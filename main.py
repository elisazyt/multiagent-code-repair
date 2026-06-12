import asyncio
import os
import sys
from autogen_core import AgentId, SingleThreadedAgentRuntime
from autogen_core.models import SystemMessage
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

from agents.prompt_templates import BASIC_PROMPT, COT_PROMPT, PATTERN_PROMPT, CONTEXT_PROMPT, SELECTION_PROMPT

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


async def main():
    runtime = SingleThreadedAgentRuntime()

    receiver_instances = {
        "patching": [
            AgentId("patching", "basic"),
            AgentId("patching", "cot"),
            AgentId("patching", "context"),
            AgentId("patching", "pattern"),
        ],
        "testing": [AgentId("testing", "testing")],
        "context": [AgentId("context", "context")],
        "summary": [AgentId("summary", "summary")],
        "selection": [AgentId("selection", "selection")],
    }

    # Create model client for PatchingAgent
    model_client = OpenAIChatCompletionClient(
        model=os.environ.get("GPT_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("OPENAI_API_KEY"),
    )

    # Create system messages for each agent type
    admin_system_message = SystemMessage(content="Admin Agent - Message Log")

    # Create BugDict for Closure 3 bug (shared by all patching agents)
    project_name = "Math"
    bug_id = "62"

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
            "org/apache/commons/math/optimization/univariate/MultiStartUnivariateRealOptimizer.java",
            [(146, 146), (160, 162)],
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

    # TODO: also import role descriptions the way we do prompts

    # Role descriptions for different patching agents
    role_descriptions = {
        "basic": "You are a basic patching agent. Generate patches for bugs in Java code.",
        "cot": "You are a chain-of-thought patching agent. Generate patches for bugs in Java code using step-by-step reasoning.",
        "context": "You are a context-aware patching agent. Generate patches for bugs in Java code using context information retrieved by the context retrieval agent.",
        "pattern": "You are a pattern-based patching agent. Generate patches for bugs in Java code using common repair patterns.",
    }

    # Role description for context retrieval agent
    context_role_description = """You are a context retrieval agent. Your job is to retrieve relevant context information 
    for bug fixing. You can request context retrieval functions for specific files. Only request functions that are 
    actually needed to understand and fix the bug."""

    selection_role_description = """You are a patch selection agent. Your job is to select the best candidate patch for a buggy Java program."""

    summary_role_description = """You are a summary agent. Your job is to summarize the context retrieval results."""

    # Store reference to AdminAgent and ContextAgent instances so we can access their context later
    admin_agent_instance_ref = None
    context_agent_instance_ref = None

    def admin_agent_factory():
        nonlocal admin_agent_instance_ref
        admin = AdminAgent(receiver_instances, admin_system_message, context_dict=context_dict, runtime=runtime)
        admin_agent_instance_ref = admin
        return admin

    # Factory for ContextRetrievalAgent
    def context_agent_factory():
        nonlocal context_agent_instance_ref
        context_agent = ContextRetrievalAgent(
            model_client=model_client,
            context_dict=context_dict,
            role_description=context_role_description,
            past_summary="",
            bug_dict=bug_dict,
        )
        context_agent_instance_ref = context_agent
        return context_agent

    # Register the classes
    await AdminAgent.register(runtime, "admin", admin_agent_factory)
    await PatchingAgent.register(
        runtime, "patching", lambda: PatchingAgent(model_client, bug_dict, role_descriptions)
    )
    await TestingAgent.register(runtime, "testing", lambda: TestingAgent(bug_dict))
    await ContextRetrievalAgent.register(runtime, "context", context_agent_factory)
    await SummaryAgent.register(runtime, "summary", lambda: SummaryAgent(model_client, summary_role_description))
    await SelectionAgent.register(
        runtime, "selection", lambda: SelectionAgent(model_client, selection_role_description, bug_dict)
    )

    runtime.start()

    # Create an AdminAgent identifier (not the instance itself)
    admin_agent = AgentId("admin", "admin_agent")

    try:
        # Run all agents' loops in parallel
        # Note: Context retrieval will be run automatically when the context patching agent needs it
        basic_rounds, cot_rounds, context_rounds, pattern_rounds = await asyncio.gather(
            run_patch_test_loop("basic", BASIC_PROMPT, admin_agent, runtime),
            run_patch_test_loop("cot", COT_PROMPT, admin_agent, runtime),
            run_patch_test_loop("context", CONTEXT_PROMPT, admin_agent, runtime, context_dict=context_dict),
            run_patch_test_loop("pattern", PATTERN_PROMPT, admin_agent, runtime),
        )

        print(f"\nFinal results:")
        print(f"Basic agent completed in {basic_rounds} rounds")
        print(f"Cot agent completed in {cot_rounds} rounds")
        print(f"Context agent completed in {context_rounds} rounds")
        print(f"Pattern agent completed in {pattern_rounds} rounds")

        # All loops are done: select the best candidate among all the patches that passed all test suites
        selection_task = SelectionTask(candidate_patches=PatchingAgent.candidate_patches, message=SELECTION_PROMPT)
        selection_response = await runtime.send_message(selection_task, recipient=admin_agent)
        print(selection_response.selected_patch_description)
    finally:
        # Regardless of whether the program ran all the way to completion, store the latest
        # message threads for each agent
        await save_all_message_threads(
            bug_dict,
            admin_agent_instance=admin_agent_instance_ref,
            context_agent_instance=context_agent_instance_ref,
        )
        await model_client.close()
        await runtime.stop_when_idle()

if __name__ == "__main__":
    asyncio.run(main())
