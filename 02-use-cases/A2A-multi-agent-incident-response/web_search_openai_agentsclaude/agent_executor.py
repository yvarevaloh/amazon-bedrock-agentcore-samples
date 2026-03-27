from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    InternalError,
    InvalidParamsError,
    Part,
    TaskState,
    TextPart,
)
from a2a.utils import new_agent_text_message, new_task
from a2a.utils.errors import ServerError
from agent import WebSearchAgent
import logging

logger = logging.getLogger(__name__)


class WebSearchAgentExecutor(AgentExecutor):
    def __init__(self):
        self._agent = None
        self._active_tasks = {}
        logger.info("WebSearchAgentExecutor initialized")

    async def _get_agent(self, session_id: str, actor_id: str):
        if self._agent is None:
            logger.info("Creating web search agent...")
            self._agent = WebSearchAgent(session_id=session_id, actor_id=actor_id)
            logger.info("Web search agent created successfully")
        return self._agent

    async def _execute_streaming(
        self, agent, user_message: str, updater: TaskUpdater, task_id: str, session_id: str
    ) -> None:
        accumulated_text = ""
        try:
            async for event in agent.stream(user_message, session_id):
                if not self._active_tasks.get(task_id, False):
                    logger.info(f"Task {task_id} was cancelled during streaming")
                    return
                if "error" in event:
                    raise Exception(event.get("content", "Unknown error"))
                content = event.get("content", "")
                if content and not event.get("is_task_complete", False):
                    accumulated_text += content
                    await updater.update_status(
                        TaskState.working,
                        new_agent_text_message(
                            accumulated_text, updater.context_id, updater.task_id
                        ),
                    )
            if accumulated_text:
                await updater.add_artifact(
                    [Part(root=TextPart(text=accumulated_text))], name="agent_response"
                )
            await updater.complete()
        except Exception as e:
            logger.error(f"Error in streaming execution: {e}", exc_info=True)
            raise

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        session_id = None
        actor_id = None
        if context.call_context:
            headers = context.call_context.state.get("headers", {})
            session_id = headers.get("x-amzn-bedrock-agentcore-runtime-session-id")
            actor_id = headers.get("x-amzn-bedrock-agentcore-runtime-custom-actorid")
        if not actor_id:
            raise ServerError(error=InvalidParamsError())
        if not session_id:
            raise ServerError(error=InvalidParamsError())

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        task_id = context.task_id

        try:
            user_message = context.get_user_input()
            if not user_message:
                raise ServerError(error=InvalidParamsError())

            agent = await self._get_agent(session_id, actor_id)
            self._active_tasks[task_id] = True
            await self._execute_streaming(agent, user_message, updater, task_id, session_id)
        except ServerError:
            raise
        except Exception as e:
            logger.error(f"Error executing task {task_id}: {e}", exc_info=True)
            raise ServerError(error=InternalError()) from e
        finally:
            self._active_tasks.pop(task_id, None)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id = context.task_id
        self._active_tasks[task_id] = False
        task = context.current_task
        if task:
            updater = TaskUpdater(event_queue, task.id, task.context_id)
            await updater.cancel()
