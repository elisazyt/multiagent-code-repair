import asyncio
import os
from dataclasses import dataclass

from autogen_core import AgentId, MessageContext, RoutedAgent, SingleThreadedAgentRuntime, message_handler
from autogen_core.models import ChatCompletionClient, UserMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient


@dataclass
class Message:
    content: str


class AskerAgent(RoutedAgent):
    """Kicks off the conversation by forwarding a prompt to the AnswererAgent."""

    def __init__(self, answerer_id: AgentId):
        super().__init__("Asker Agent")
        self.answerer_id = answerer_id

    @message_handler
    async def on_message(self, message: Message, ctx: MessageContext) -> Message:
        return await self.send_message(message, self.answerer_id)


class AnswererAgent(RoutedAgent):
    """Calls the LLM once and returns its reply."""

    def __init__(self, model_client: ChatCompletionClient):
        super().__init__("Answerer Agent")
        self.model_client = model_client

    @message_handler
    async def on_message(self, message: Message, ctx: MessageContext) -> Message:
        result = await self.model_client.create([UserMessage(content=message.content, source="asker")])
        return Message(content=result.content)


async def run_convo():
    runtime = SingleThreadedAgentRuntime()

    model_client = OpenAIChatCompletionClient(
        model=os.environ.get("GPT_MODEL", "gpt-4o-mini"),
        api_key=os.environ.get("OPENAI_API_KEY"),
    )

    await AnswererAgent.register(runtime, "answerer", lambda: AnswererAgent(model_client))
    await AskerAgent.register(runtime, "asker", lambda: AskerAgent(AgentId("answerer", "default")))

    runtime.start()

    prompt = "In one sentence, what is a multi-agent system?"
    response = await runtime.send_message(Message(content=prompt), AgentId("asker", "default"))

    await runtime.stop_when_idle()
    usage = model_client.total_usage()
    await model_client.close()

    return prompt, response.content, usage


if __name__ == "__main__":
    prompt, answer, usage = asyncio.run(run_convo())

    print(f"Asker: {prompt}")
    print(f"Answerer: {answer}")
    print(
        f"\nTokens used — prompt: {usage.prompt_tokens}, "
        f"completion: {usage.completion_tokens}, "
        f"total: {usage.prompt_tokens + usage.completion_tokens}"
    )