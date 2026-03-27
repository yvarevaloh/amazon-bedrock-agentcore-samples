from a2a.client import ClientConfig, ClientFactory
from a2a.types import TransportProtocol
from bedrock_agentcore.identity.auth import requires_access_token
from strands import Agent, tool
from strands.agent.a2a_agent import A2AAgent
from strands.models.anthropic import AnthropicModel
from prompt import SYSTEM_PROMPT
from urllib.parse import quote
import httpx
import os
import uuid

IS_DOCKER = os.getenv("DOCKER_CONTAINER", "0") == "1"
ANTHROPIC_MODEL_ID = os.getenv("ANTHROPIC_MODEL_ID", "claude-sonnet-4-20250514")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

if IS_DOCKER:
    from utils import get_ssm_parameter, get_aws_info
else:
    from host_adk_agentclaude.utils import get_ssm_parameter, get_aws_info


# AWS and agent configuration
account_id, region = get_aws_info()

MONITOR_AGENT_ID = get_ssm_parameter("/monitoragent/agentcore/runtime-id")
MONITOR_PROVIDER_NAME = get_ssm_parameter("/monitoragent/agentcore/provider-name")
MONITOR_AGENT_ARN = (
    f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{MONITOR_AGENT_ID}"
)

WEBSEARCH_AGENT_ID = get_ssm_parameter("/websearchagent/agentcore/runtime-id")
WEBSEARCH_PROVIDER_NAME = get_ssm_parameter("/websearchagent/agentcore/provider-name")
WEBSEARCH_AGENT_ARN = (
    f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/{WEBSEARCH_AGENT_ID}"
)


def _create_client_factory(provider_name: str, session_id: str, actor_id: str):
    """Create a lazy client factory that creates fresh httpx clients on demand."""

    def _get_authenticated_client() -> httpx.AsyncClient:
        @requires_access_token(
            provider_name=provider_name,
            scopes=[],
            auth_flow="M2M",
            into="bearer_token",
            force_authentication=True,
        )
        def _create_client(bearer_token: str = str()) -> httpx.AsyncClient:
            headers = {
                "Authorization": f"Bearer {bearer_token}",
                "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
                "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actorid": actor_id,
            }
            return httpx.AsyncClient(
                timeout=httpx.Timeout(timeout=300.0),
                headers=headers,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )

        return _create_client()

    class LazyClientFactory:
        def __init__(self):
            initial_client = _get_authenticated_client()
            base_config = ClientConfig(
                httpx_client=initial_client,
                streaming=False,
                supported_transports=[TransportProtocol.jsonrpc],
            )
            self._base_factory = ClientFactory(config=base_config)

        @property
        def _config(self):
            return self._base_factory._config

        @property
        def _registry(self):
            return self._base_factory._registry

        @property
        def _consumers(self):
            return self._base_factory._consumers

        def register(self, label, generator):
            return self._base_factory.register(label, generator)

        def create(self, agent_card):
            httpx_client = _get_authenticated_client()
            fresh_config = ClientConfig(
                httpx_client=httpx_client,
                streaming=False,
                supported_transports=[TransportProtocol.jsonrpc],
            )
            fresh_factory = ClientFactory(config=fresh_config)
            return fresh_factory.create(agent_card)

    return LazyClientFactory()


def _build_a2a_agent_url(agent_arn: str) -> str:
    return (
        f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
        f"{quote(agent_arn, safe='')}/invocations"
    )


def get_root_agent(session_id: str, actor_id: str):
    # Create A2A remote agents
    monitor_url = _build_a2a_agent_url(MONITOR_AGENT_ARN)
    monitor_a2a = A2AAgent(
        endpoint=monitor_url,
        name="monitor_agent",
        description="Agent that handles monitoring tasks.",
        a2a_client_factory=_create_client_factory(
            provider_name=MONITOR_PROVIDER_NAME,
            session_id=session_id,
            actor_id=actor_id,
        ),
    )

    websearch_url = _build_a2a_agent_url(WEBSEARCH_AGENT_ARN)
    websearch_a2a = A2AAgent(
        endpoint=websearch_url,
        name="websearch_agent",
        description="Web search agent for finding AWS solutions, documentation, and best practices.",
        a2a_client_factory=_create_client_factory(
            provider_name=WEBSEARCH_PROVIDER_NAME,
            session_id=session_id,
            actor_id=actor_id,
        ),
    )

    # Wrap A2A agents as tools for the orchestrator
    @tool
    def monitor_agent(query: str) -> str:
        """Delegate monitoring tasks to the monitor agent. Handles CloudWatch metrics, logs, alarms, and monitoring data for EC2/Lambda/RDS.

        Args:
            query: The monitoring question or task to delegate.

        Returns:
            The monitor agent's response.
        """
        result = monitor_a2a(query)
        return str(result.message)

    @tool
    def websearch_agent(query: str) -> str:
        """Delegate web search tasks to the websearch agent. Finds AWS troubleshooting guides, documentation, best practices, and solutions.

        Args:
            query: The search question or topic to look up.

        Returns:
            The websearch agent's response.
        """
        result = websearch_a2a(query)
        return str(result.message)

    # Create Anthropic model
    model = AnthropicModel(
        client_args={"api_key": ANTHROPIC_API_KEY},
        model_id=ANTHROPIC_MODEL_ID,
        max_tokens=4096,
    )

    # Create root orchestrator agent
    root_agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[monitor_agent, websearch_agent],
        callback_handler=None,
    )

    return root_agent


async def get_agent_and_card(session_id: str, actor_id: str):
    """Lazy initialization of the root agent."""
    root_agent = get_root_agent(session_id=session_id, actor_id=actor_id)

    # Return agent info (Strands doesn't have agent cards like ADK,
    # but we return metadata for compatibility)
    agents_info = {
        "monitor_agent": {
            "agent_card_url": _build_a2a_agent_url(MONITOR_AGENT_ARN)
            + "/.well-known/agent-card.json"
        },
        "websearch_agent": {
            "agent_card_url": _build_a2a_agent_url(WEBSEARCH_AGENT_ARN)
            + "/.well-known/agent-card.json"
        },
    }

    return root_agent, agents_info


if not IS_DOCKER:
    session_id = str(uuid.uuid4())
    actor_id = "webadk"
    root_agent = get_root_agent(session_id=session_id, actor_id=actor_id)
