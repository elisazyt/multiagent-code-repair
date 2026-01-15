import asyncio
import os
from autogen_core import AgentId, SingleThreadedAgentRuntime
from autogen_core.models import SystemMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient
from agents import AdminAgent, PatchingAgent, TestingAgent
from agent_helpers import run_patch_test_loop, print_message_thread


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
    patching_system_message = SystemMessage(
        content="You are a code patching agent. Generate patches for bugs in Java code."
    )

    # Store reference to AdminAgent instance so we can access its context later
    admin_agent_instance_ref = [None]
    
    def admin_agent_factory():
        admin = AdminAgent("Admin Agent", receiver_instances, admin_system_message)
        admin_agent_instance_ref[0] = admin
        return admin

    # Register the classes
    await AdminAgent.register(runtime, "admin", admin_agent_factory)
    await PatchingAgent.register(runtime, "patching", lambda: PatchingAgent("Patching Agent", model_client, patching_system_message))
    await TestingAgent.register(runtime, "testing", lambda: TestingAgent("Testing Agent"))

    runtime.start()

    # Create an AdminAgent identifier (not the instance itself)
    admin_agent = AgentId("admin", "admin_agent")

    # Run both agents' loops in parallel
    basic_rounds, cot_rounds = await asyncio.gather(
        run_patch_test_loop("basic", "Generate an English sentence.", admin_agent, runtime),
        run_patch_test_loop("cot", "Generate a 10 digit number.", admin_agent, runtime)
    )
    
    print(f"\nFinal results:")
    print(f"Basic agent completed in {basic_rounds} rounds")
    print(f"Cot agent completed in {cot_rounds} rounds")

    # Now we can access the actual instance and its context
    if admin_agent_instance_ref[0] is not None:
        await print_message_thread(admin_agent_instance_ref[0]._context, agent_id="admin agent")

    # Print the basic PatchingAgent's message thread
    if "basic" in PatchingAgent._instances_dict:
        await print_message_thread(PatchingAgent._instances_dict["basic"]._context, agent_id="basic patching agent")

    await model_client.close()
    await runtime.stop_when_idle()


if __name__ == "__main__":
    asyncio.run(main())