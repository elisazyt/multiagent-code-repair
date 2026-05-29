import asyncio
import os
from dotenv import load_dotenv
from autogen_core import AgentId, SingleThreadedAgentRuntime
from autogen_core.models import SystemMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient
from agents import AdminAgent, PatchingAgent, TestingAgent, ContextRetrievalAgent, SummaryAgent
from agent_helpers import run_patch_test_loop, save_message_thread, run_single_attempt_context
from info_dict import InfoDict, ContextDict
from data_classes import ContextRetrievalTask

from prompt_templates import BASIC_PROMPT, COT_PROMPT, PATTERN_PROMPT

# Load environment variables from .env file
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)


async def main():
    runtime = SingleThreadedAgentRuntime()

    receiver_instances = {
        "patching": [AgentId("patching", "basic"), AgentId("patching", "cot"), AgentId("patching", "context"), AgentId("patching", "pattern")], 
        "testing": [AgentId("testing", "testing")],
        "context": [AgentId("context", "context")],
        "summary": [AgentId("summary", "summary")]
    }

    # Create model client for PatchingAgent
    model_client = OpenAIChatCompletionClient(
        model=os.environ.get("GPT_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("OPENAI_API_KEY")
    )

    # Create system messages for each agent type
    admin_system_message = SystemMessage(content="Admin Agent - Message Log")
    
    # Create InfoDict for closure4 bug (shared by all patching agents)
    closure4_path = os.path.join(project_root, "ALL_TESTS", "closure4.java")
    
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
        bug_id="4",
        bug_locations=[(closure4_path, [(190, 190), (202, 202)])],
        working_directory=working_directory
    )
    
    # Add Joern configuration
    joern_executable = os.getenv('JOERN_EXECUTABLE')
    joern_directory = os.getenv('JOERN_DIRECTORY')
    if joern_executable and joern_directory:
        information.add_joern_config(joern_executable, joern_directory)
    
    # Create ContextDict initialized from InfoDict
    context_info = ContextDict(info_dict=information)
    
    # Role descriptions for different patching agents
    role_descriptions = {
        "basic": "You are a basic patching agent. Generate patches for bugs in Java code.",
        "cot": "You are a chain-of-thought patching agent. Generate patches for bugs in Java code using step-by-step reasoning.",
        "context": "You are a context-aware patching agent. Generate patches for bugs in Java code using context information retrieved by the context retrieval agent.",
        "pattern": "You are a pattern-based patching agent. Generate patches for bugs in Java code using common repair patterns."
    }
    
    # Role description for context retrieval agent
    context_role_description = """You are a context retrieval agent. Your job is to retrieve relevant context information 
    for bug fixing. You can request context retrieval functions for specific files. Only request functions that are 
    actually needed to understand and fix the bug."""

    # Store reference to AdminAgent and ContextAgent instances so we can access their context later
    admin_agent_instance_ref = None
    context_agent_instance_ref = None
    
    def admin_agent_factory():
        nonlocal admin_agent_instance_ref
        admin = AdminAgent(receiver_instances, admin_system_message, context_info=context_info, runtime=runtime)
        admin_agent_instance_ref = admin
        return admin
    
    # Factory for ContextRetrievalAgent
    def context_agent_factory():
        nonlocal context_agent_instance_ref
        context_agent = ContextRetrievalAgent(
            model_client=model_client,
            context_info=context_info,
            role_description=context_role_description,
            past_summary="",
            information=information
        )
        context_agent_instance_ref = context_agent
        return context_agent

    # Register the classes
    await AdminAgent.register(runtime, "admin", admin_agent_factory)
    await PatchingAgent.register(runtime, "patching", lambda: PatchingAgent(model_client, information, role_descriptions))
    await TestingAgent.register(runtime, "testing", lambda: TestingAgent(information))
    await ContextRetrievalAgent.register(runtime, "context", context_agent_factory)
    await SummaryAgent.register(runtime, "summary", lambda: SummaryAgent(model_client))

    runtime.start()

    # Create an AdminAgent identifier (not the instance itself)
    admin_agent = AgentId("admin", "admin_agent")

    # Run all agents' loops in parallel
    # Note: Context retrieval will be run automatically when the context patching agent needs it
    basic_rounds, cot_rounds, context_rounds, pattern_rounds = await asyncio.gather(
        run_patch_test_loop("basic", BASIC_PROMPT, admin_agent, context_info, runtime),
        run_patch_test_loop("cot", COT_PROMPT, admin_agent, context_info, runtime),
        run_patch_test_loop("context", "Generate a patch for the bug using the context information provided.", admin_agent, context_info, runtime),
        run_patch_test_loop("pattern", PATTERN_PROMPT, admin_agent, context_info, runtime)
    )
    
    print(f"\nFinal results:")
    print(f"Basic agent completed in {basic_rounds} rounds")
    print(f"Cot agent completed in {cot_rounds} rounds")
    print(f"Context agent completed in {context_rounds} rounds")
    print(f"Pattern agent completed in {pattern_rounds} rounds")

    # Save the basic PatchingAgent's message thread
    if "basic" in PatchingAgent._instances_dict:
        basic_agent = PatchingAgent._instances_dict["basic"]
        await save_message_thread(
            basic_agent._context, 
            agent_id=basic_agent.id.key,
            information=basic_agent.information
        )
    
    # Save the cot PatchingAgent's message thread if it exists
    if "cot" in PatchingAgent._instances_dict:
        cot_agent = PatchingAgent._instances_dict["cot"]
        await save_message_thread(
            cot_agent._context, 
            agent_id=cot_agent.id.key,
            information=cot_agent.information
        )
    
    # Save the context PatchingAgent's message thread if it exists
    if "context" in PatchingAgent._instances_dict:
        context_agent = PatchingAgent._instances_dict["context"]
        await save_message_thread(
            context_agent._context, 
            agent_id=context_agent.id.key,
            information=context_agent.information
        )
    
    # Save the pattern PatchingAgent's message thread if it exists
    if "pattern" in PatchingAgent._instances_dict:
        pattern_agent = PatchingAgent._instances_dict["pattern"]
        await save_message_thread(
            pattern_agent._context, 
            agent_id=pattern_agent.id.key,
            information=pattern_agent.information
        )
    
    # Save the AdminAgent's message thread
    if admin_agent_instance_ref[0] is not None:
        admin_agent = admin_agent_instance_ref[0]
        await save_message_thread(
            admin_agent._context,
            agent_id=admin_agent.id.key,
            information=information
        )
    
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