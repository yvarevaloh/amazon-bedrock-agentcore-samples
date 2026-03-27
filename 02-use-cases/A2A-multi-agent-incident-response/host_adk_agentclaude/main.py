import logging
from dotenv import load_dotenv
from bedrock_agentcore import BedrockAgentCoreApp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

APP_NAME = "HostAgentA2A"

app = BedrockAgentCoreApp()

root_agent = None


@app.entrypoint
async def call_agent(payload: dict, context):
    global root_agent

    session_id = context.session_id
    logger.info(f"Received request with session_id: {session_id}")

    actor_id = context.request_headers[
        "x-amzn-bedrock-agentcore-runtime-custom-actorid"
    ]

    if not actor_id:
        raise Exception("Actor id is not set")

    if not session_id:
        raise Exception("Context session_id is not set")

    if not root_agent:
        from agent import get_agent_and_card

        logger.info("Initializing root agent and resolving agent cards...")
        try:
            root_agent, agents_cards = await get_agent_and_card(
                session_id=session_id, actor_id=actor_id
            )
            logger.info(
                f"Successfully initialized root agent. Agent cards: {list(agents_cards.keys())}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize root agent: {e}", exc_info=True)
            raise

        yield agents_cards

    query = payload.get("prompt")
    logger.info(f"Processing query: {query}")

    if not query:
        raise KeyError("'prompt' field is required in payload")

    # Strands Agent handles conversation state internally.
    # Invoke the agent and yield the result.
    result = await root_agent.invoke_async(query)
    yield result


if __name__ == "__main__":
    app.run()
