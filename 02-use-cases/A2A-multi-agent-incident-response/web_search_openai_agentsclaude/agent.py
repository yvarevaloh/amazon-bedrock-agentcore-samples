import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from strands import Agent
from strands.models import BedrockModel
from prompt import SYSTEM_PROMPT
from tools import web_search, _get_memory_tools

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
MCP_REGION = os.getenv("MCP_REGION")
if not MCP_REGION:
    raise RuntimeError("Missing MCP_REGION environment variable")

MEMORY_ID = os.getenv("MEMORY_ID")
if not MEMORY_ID:
    raise RuntimeError("Missing MEMORY_ID environment variable")


class WebSearchAgent:
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self, session_id: str, actor_id: str):
        bedrock_model = BedrockModel(model_id=MODEL_ID, region_name=MCP_REGION)
        memory_tools = _get_memory_tools(
            memory_id=MEMORY_ID, session_id=session_id, actor_id=actor_id
        )
        agent_tools = [web_search] + memory_tools

        self.agent = Agent(
            name="WebSearch_Agent",
            description="Web search agent that provides AWS documentation and solutions",
            system_prompt=SYSTEM_PROMPT,
            model=bedrock_model,
            tools=agent_tools,
        )

    async def stream(self, query: str, session_id: str):
        response = str()
        try:
            async for event in self.agent.stream_async(query):
                if "data" in event:
                    response += event["data"]
                    yield {
                        "is_task_complete": "complete" in event,
                        "require_user_input": False,
                        "content": event["data"],
                    }
        except Exception as e:
            yield {
                "is_task_complete": False,
                "require_user_input": True,
                "content": f"Error: {e}",
            }
        finally:
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": response,
            }

    def invoke(self, query: str, session_id: str):
        return str(self.agent(query))
