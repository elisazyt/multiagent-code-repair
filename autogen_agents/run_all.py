import asyncio
import os
from dotenv import load_dotenv
from autogen_core import AgentId, SingleThreadedAgentRuntime
from autogen_core.models import SystemMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient
from agents import AdminAgent, PatchingAgent, TestingAgent
from agent_helpers import run_patch_test_loop, save_message_thread
from info_dict import InfoDict

from prompt_templates import BASIC_PROMPT, COT_PROMPT

# Load environment variables from .env file
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)


async def main():
    runtime = SingleThreadedAgentRuntime()

    receiver_instances = {"patching": [AgentId("patching", "basic"), AgentId("patching", "cot")], "testing": [AgentId("testing", "testing")]}

    # Create model client for PatchingAgent
    model_client = OpenAIChatCompletionClient(
        model=os.environ.get("GPT_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("OPENAI_API_KEY")
    )

    # Create system messages for each agent type
    admin_system_message = SystemMessage(content="Admin Agent - Message Log")
    
    # Create InfoDict for closure8 bug (shared by all patching agents)
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
    
    # Role descriptions for different patching agents
    role_descriptions = {
        "basic": "You are a basic patching agent. Generate patches for bugs in Java code.",
        "cot": "You are a chain-of-thought patching agent. Generate patches for bugs in Java code using step-by-step reasoning."
    }

    # Store reference to AdminAgent instance so we can access its context later
    admin_agent_instance_ref = [None]
    
    def admin_agent_factory():
        admin = AdminAgent("Admin Agent", receiver_instances, admin_system_message)
        admin_agent_instance_ref[0] = admin
        return admin
    
    # Single factory for PatchingAgent - will look up role_description based on agent key in __init__
    def patching_agent_factory():
        return PatchingAgent("Patching Agent", model_client, information, role_descriptions)

    # Register the classes
    await AdminAgent.register(runtime, "admin", admin_agent_factory)
    await PatchingAgent.register(runtime, "patching", patching_agent_factory)
    await TestingAgent.register(runtime, "testing", lambda: TestingAgent("Testing Agent", information))

    runtime.start()

    # Create an AdminAgent identifier (not the instance itself)
    admin_agent = AgentId("admin", "admin_agent")

    # Run both agents' loops in parallel
    basic_rounds, cot_rounds = await asyncio.gather(
        run_patch_test_loop("basic", BASIC_PROMPT, admin_agent, runtime),
        run_patch_test_loop("cot", COT_PROMPT, admin_agent, runtime)
    )
    
    print(f"\nFinal results:")
    print(f"Basic agent completed in {basic_rounds} rounds")
    print(f"Cot agent completed in {cot_rounds} rounds")

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
    
    # Save the AdminAgent's message thread
    if admin_agent_instance_ref[0] is not None:
        admin_agent = admin_agent_instance_ref[0]
        await save_message_thread(
            admin_agent._context,
            agent_id=admin_agent.id.key,
            information=information
        )

    await model_client.close()
    await runtime.stop_when_idle()


if __name__ == "__main__":
    asyncio.run(main())