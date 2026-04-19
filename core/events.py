"""
Jarvis Event Bus
=================
Central async event bus for decoupled module communication.

Usage:
    from core.events import bus, Event

    # Subscribe
    async def on_wake(data):
        print("Wake word detected!")
    bus.on(Event.WAKE_WORD, on_wake)

    # Emit
    await bus.emit(Event.WAKE_WORD, {"confidence": 0.95})

    # Synchronous handlers are also supported
    def on_state(data):
        print(f"State: {data['state']}")
    bus.on(Event.STATE_CHANGE, on_state)
"""

import asyncio
import logging
import inspect
from enum import Enum, auto
from typing import Any, Callable, Coroutine, Union

logger = logging.getLogger("jarvis.events")

# Type alias for event handlers
Handler = Union[Callable[..., Any], Callable[..., Coroutine]]


class Event(Enum):
    """All event types flowing through the system."""

    # --- Audio pipeline ---
    WAKE_WORD = auto()          # Wake word detected
    SPEECH_START = auto()       # User started speaking
    SPEECH_END = auto()         # User stopped speaking (VAD)
    SPEECH_TEXT = auto()        # Transcribed text ready
    SPEECH_FAILED = auto()      # STT failed

    # --- Brain ---
    INTENT_PARSED = auto()      # Intent determined by LLM/rules
    LLM_RESPONSE = auto()       # Raw LLM response
    LLM_ERROR = auto()          # LLM failed

    # --- Actions ---
    ACTION_START = auto()       # Action execution started
    ACTION_COMPLETE = auto()    # Action finished successfully
    ACTION_FAILED = auto()      # Action failed
    AUTH_REQUIRED = auto()      # Voice auth needed for this action
    AUTH_RESULT = auto()        # Voice auth success/failure

    # --- State ---
    STATE_CHANGE = auto()       # State machine transition
    FOLLOW_UP_TIMEOUT = auto()  # Follow-up window expired

    # --- UI ---
    UI_UPDATE = auto()          # Push update to UI overlay
    UI_NOTIFICATION = auto()    # Show a notification

    # --- Voice output ---
    TTS_START = auto()          # TTS playback started
    TTS_DONE = auto()           # TTS playback finished

    # --- System ---
    SHUTDOWN = auto()           # Graceful shutdown requested
    ERROR = auto()              # General error


class EventBus:
    """
    Async-compatible event bus with support for both sync and async handlers.
    
    Thread-safe for emitting from non-async contexts via emit_sync().
    Handlers are called in registration order.
    Exceptions in handlers are caught and logged (never crash the bus).
    """

    def __init__(self):
        self._handlers: dict[Event, list[Handler]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def on(self, event: Event, handler: Handler) -> None:
        """Register a handler for an event type."""
        if event not in self._handlers:
            self._handlers[event] = []

        if handler not in self._handlers[event]:
            self._handlers[event].append(handler)
            logger.debug("Registered handler %s for %s", handler.__qualname__, event.name)

    def off(self, event: Event, handler: Handler) -> None:
        """Unregister a handler."""
        if event in self._handlers:
            self._handlers[event] = [h for h in self._handlers[event] if h != handler]

    async def emit(self, event: Event, data: dict[str, Any] | None = None) -> None:
        """
        Emit an event to all registered handlers.
        
        Async handlers are awaited. Sync handlers are called directly.
        All handlers receive the data dict as keyword arguments.
        """
        handlers = self._handlers.get(event, [])

        if not handlers:
            logger.debug("Event %s emitted with no handlers", event.name)
            return

        data = data or {}
        logger.debug("Emitting %s to %d handler(s)", event.name, len(handlers))

        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception:
                logger.exception(
                    "Handler %s failed for event %s",
                    handler.__qualname__,
                    event.name,
                )

    def emit_sync(self, event: Event, data: dict[str, Any] | None = None) -> None:
        """
        Emit an event from a synchronous (non-async) context.
        
        If an event loop is running, schedules the emit as a task.
        Otherwise, runs synchronously (only sync handlers will work).
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(event, data))
        except RuntimeError:
            # No event loop running — call sync handlers only
            data = data or {}
            for handler in self._handlers.get(event, []):
                if not inspect.iscoroutinefunction(handler):
                    try:
                        handler(data)
                    except Exception:
                        logger.exception(
                            "Sync handler %s failed for event %s",
                            handler.__qualname__,
                            event.name,
                        )

    def clear(self) -> None:
        """Remove all handlers (for testing)."""
        self._handlers.clear()

    @property
    def handler_count(self) -> int:
        """Total number of registered handlers across all events."""
        return sum(len(h) for h in self._handlers.values())


# Global singleton — import this everywhere
bus = EventBus()
