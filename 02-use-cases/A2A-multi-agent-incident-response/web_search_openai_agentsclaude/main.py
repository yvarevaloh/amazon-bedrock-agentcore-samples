from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from agent_executor import WebSearchAgentExecutor
from starlette.responses import JSONResponse
import logging
import os
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

runtime_url = os.getenv("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9000/")
host, port = "0.0.0.0", 9000

agent_card = AgentCard(
    name="WebSearch Agent",
    description="Web search agent that provides AWS documentation and solutions by searching for relevant information",
    url=runtime_url,
    version="0.3.0",
    defaultInputModes=["text/plain"],
    defaultOutputModes=["text/plain"],
    capabilities=AgentCapabilities(streaming=True, pushNotifications=False),
    skills=[
        AgentSkill(
            id="websearch",
            name="Web Search",
            description="Search AWS documentation and provide solutions for operational issues",
            tags=["websearch", "aws", "documentation", "solutions"],
            examples=[
                "Find documentation for fixing high CPU usage in EC2",
                "Search for solutions to RDS connection timeout issues",
            ],
        ),
    ],
)

request_handler = DefaultRequestHandler(
    agent_executor=WebSearchAgentExecutor(), task_store=InMemoryTaskStore()
)
server = A2AStarletteApplication(agent_card=agent_card, http_handler=request_handler)
app = server.build()


@app.route("/ping", methods=["GET"])
async def ping(request):
    return JSONResponse({"status": "healthy"})


logger.info(f"A2A Server configured at {runtime_url}")

if __name__ == "__main__":
    uvicorn.run(app, host=host, port=port)
