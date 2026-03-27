import logging
import time
from typing import Dict, Optional
from bedrock_agentcore.memory import MemoryClient
from strands import tool

logger = logging.getLogger(__name__)


class AgentMemoryTools:
    def __init__(self, memory_id: str, client: MemoryClient, actor_id: str, session_id: str):
        self.memory_id = memory_id
        self.client = client
        self.actor_id = actor_id
        self.session_id = session_id
        self.namespaces = self._get_namespaces()

    def _get_namespaces(self) -> Dict:
        try:
            strategies = self.client.get_memory_strategies(self.memory_id)
            return {i["type"]: i["namespaces"][0] for i in strategies}
        except Exception as e:
            logger.error(f"Failed to get namespaces: {e}")
            return {}

    def create_memory_tools(self):
        memory_id = self.memory_id
        client = self.client
        actor_id = self.actor_id
        session_id = self.session_id
        namespaces = self.namespaces

        @tool
        def retrieve_monitoring_context(query: str, context_type: Optional[str] = None, top_k: int = 3) -> str:
            """Retrieve monitoring context from memory using semantic search.

            Args:
                query: The search query to find relevant context
                context_type: Optional specific context type to search
                top_k: Number of top results to return
            """
            try:
                all_context = []
                search_ns = {context_type: namespaces[context_type]} if context_type and context_type in namespaces else namespaces
                for ctx_type, namespace in search_ns.items():
                    memories = client.retrieve_memories(
                        memory_id=memory_id,
                        namespace=namespace.format(actorId=actor_id),
                        query=query,
                        top_k=top_k,
                    )
                    for memory in memories:
                        if isinstance(memory, dict):
                            content = memory.get("content", {})
                            if isinstance(content, dict):
                                text = content.get("text", "").strip()
                                if text:
                                    all_context.append(f"[{ctx_type.upper()}] {text}")
                return "\n".join(all_context) if all_context else "No relevant context found."
            except Exception as e:
                return f"Error retrieving context: {e}"

        @tool
        def save_interaction_to_memory(user_message: str, assistant_response: str) -> str:
            """Save a user-assistant interaction to memory.

            Args:
                user_message: The user's message/query
                assistant_response: The assistant's response
            """
            try:
                client.create_event(
                    memory_id=memory_id,
                    actor_id=actor_id,
                    session_id=session_id,
                    messages=[(user_message, "USER"), (assistant_response, "ASSISTANT")],
                )
                return "Interaction saved to memory successfully."
            except Exception as e:
                return f"Error saving interaction: {e}"

        @tool
        def get_recent_conversation_history(k_turns: int = 5) -> str:
            """Retrieve recent conversation history from memory.

            Args:
                k_turns: Number of recent conversation turns to retrieve
            """
            try:
                recent_turns = client.get_last_k_turns(
                    memory_id=memory_id, actor_id=actor_id, session_id=session_id, k=k_turns
                )
                if recent_turns:
                    messages = []
                    for turn in recent_turns:
                        for message in turn:
                            messages.append(f"{message['role']}: {message['content']['text']}")
                    return "\n".join(messages)
                return "No recent conversation history found."
            except Exception as e:
                return f"Error retrieving history: {e}"

        @tool
        def save_custom_memory(content: str, memory_type: str = "SemanticMemory") -> str:
            """Save custom content to a specific memory type.

            Args:
                content: The content to save to memory
                memory_type: The type of memory to save to
            """
            try:
                client.create_event(
                    memory_id=memory_id,
                    actor_id=actor_id,
                    session_id=f"{session_id}_custom_{int(time.time())}",
                    messages=[(content, "ASSISTANT")],
                )
                return f"Custom content saved to {memory_type} successfully."
            except Exception as e:
                return f"Error saving custom content: {e}"

        @tool
        def search_memory_by_namespace(query: str, namespace_type: str, top_k: int = 5) -> str:
            """Search memory within a specific namespace type.

            Args:
                query: The search query
                namespace_type: The namespace type to search in
                top_k: Number of results to return
            """
            try:
                if namespace_type not in namespaces:
                    return f"Invalid namespace type. Available: {', '.join(namespaces.keys())}"
                namespace = namespaces[namespace_type]
                memories = client.retrieve_memories(
                    memory_id=memory_id,
                    namespace=namespace.format(actorId=actor_id),
                    query=query,
                    top_k=top_k,
                )
                results = []
                for memory in memories:
                    if isinstance(memory, dict):
                        content = memory.get("content", {})
                        if isinstance(content, dict):
                            text = content.get("text", "").strip()
                            if text:
                                results.append(text)
                if results:
                    return f"Found {len(results)} results in {namespace_type}:\n" + "\n---\n".join(results)
                return f"No results found in {namespace_type} for query: {query}"
            except Exception as e:
                return f"Error searching memory: {e}"

        return [
            retrieve_monitoring_context,
            save_interaction_to_memory,
            get_recent_conversation_history,
            save_custom_memory,
            search_memory_by_namespace,
        ]


def create_memory_tools(memory_id: str, client: MemoryClient, actor_id: str, session_id: str):
    memory_tools = AgentMemoryTools(memory_id, client, actor_id, session_id)
    return memory_tools.create_memory_tools()
