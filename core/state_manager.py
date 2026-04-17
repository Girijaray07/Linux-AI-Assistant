"""
Jarvis State Machine
=====================
Manages assistant states and transitions with timeout handling.

States:
    IDLE       → Waiting for wake word. Minimal CPU.
    LISTENING  → Actively recording user speech.
    PROCESSING → AI is thinking / executing action.
    RESPONDING → Speaking the response via TTS.
    ERROR      → Something went wrong; auto-recovers to IDLE.

Transitions are guarded — invalid transitions are rejected and logged.
Wake-word detection triggers a non-blocking acknowledgment phrase via TTS.
"""

import asyncio
import logging
import time
from enum import Enum, auto
from typing import Optional

from core.events import bus, Event
from core import config

logger = logging.getLogger("jarvis.state")


class State(Enum):
    """Assistant states."""
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    RESPONDING = auto()
    ERROR = auto()


# Valid transitions: {from_state: [allowed_to_states]}
TRANSITIONS = {
    State.IDLE: [State.LISTENING],
    State.LISTENING: [State.PROCESSING, State.IDLE],
    State.PROCESSING: [State.RESPONDING, State.ERROR, State.IDLE],
    State.RESPONDING: [State.LISTENING, State.IDLE],
    State.ERROR: [State.IDLE],
}


class StateManager:
    """
    Manages the assistant's lifecycle state with timeouts and event integration.
    
    The state manager:
    - Enforces valid state transitions
    - Emits STATE_CHANGE events on every transition
    - Handles follow-up timeout (LISTENING → IDLE after 12s silence)
    - Handles processing timeout (PROCESSING → IDLE after 30s)
    - Tracks timing for performance monitoring
    """

    def __init__(self):
        self._state: State = State.IDLE
        self._state_entered_at: float = time.monotonic()
        self._follow_up_task: Optional[asyncio.Task] = None
        self._processing_timeout_task: Optional[asyncio.Task] = None
        self._wake_ack_task: Optional[asyncio.Task] = None
        self._transition_history: list[tuple[State, State, float]] = []

        # Load timeouts from config
        cfg = config.get("assistant", default={})
        self._follow_up_timeout: float = cfg.get("follow_up_timeout", 12)
        self._command_timeout: float = cfg.get("command_timeout", 30)

        # Wire up event listeners
        bus.on(Event.WAKE_WORD, self._on_wake_word)
        bus.on(Event.SPEECH_TEXT, self._on_speech_text)
        bus.on(Event.SPEECH_FAILED, self._on_speech_failed)
        bus.on(Event.ACTION_COMPLETE, self._on_action_complete)
        bus.on(Event.ACTION_FAILED, self._on_action_failed)
        bus.on(Event.TTS_DONE, self._on_tts_done)

        logger.info(
            "State machine initialized (follow_up=%.0fs, cmd_timeout=%.0fs)",
            self._follow_up_timeout,
            self._command_timeout,
        )

    @property
    def state(self) -> State:
        """Current state."""
        return self._state

    @property
    def state_duration(self) -> float:
        """Seconds since entering the current state."""
        return time.monotonic() - self._state_entered_at

    async def transition(self, new_state: State, reason: str = "") -> bool:
        """
        Attempt a state transition.
        
        Returns True if transition succeeded, False if rejected.
        Emits STATE_CHANGE event on success.
        """
        old_state = self._state

        # Validate transition
        allowed = TRANSITIONS.get(old_state, [])
        if new_state not in allowed:
            logger.warning(
                "❌ Invalid transition: %s → %s (allowed: %s) reason=%s",
                old_state.name, new_state.name,
                [s.name for s in allowed], reason,
            )
            return False

        # Cancel any pending timeouts
        self._cancel_timeouts()

        # Execute transition
        self._state = new_state
        self._state_entered_at = time.monotonic()
        self._transition_history.append((old_state, new_state, time.monotonic()))

        # Trim history to last 100 transitions
        if len(self._transition_history) > 100:
            self._transition_history = self._transition_history[-50:]

        logger.info(
            "🔄 State: %s → %s (%s)",
            old_state.name, new_state.name, reason or "no reason",
        )

        # Emit state change event
        await bus.emit(Event.STATE_CHANGE, {
            "old_state": old_state,
            "new_state": new_state,
            "reason": reason,
            "timestamp": time.time(),
        })

        # Set up timeouts for the new state
        await self._setup_timeouts(new_state)

        return True

    async def force_idle(self, reason: str = "forced") -> None:
        """Force transition to IDLE from any state."""
        self._cancel_timeouts()
        old = self._state
        self._state = State.IDLE
        self._state_entered_at = time.monotonic()

        logger.info("⏹️ Force IDLE from %s (%s)", old.name, reason)

        await bus.emit(Event.STATE_CHANGE, {
            "old_state": old,
            "new_state": State.IDLE,
            "reason": reason,
            "timestamp": time.time(),
        })

    # ------------------------------------------------------------------
    # Event handlers (wired in __init__)
    # ------------------------------------------------------------------

    async def _on_wake_word(self, data: dict) -> None:
        """
        Wake word detected → start listening.

        Also fires a non-blocking TTS acknowledgment (e.g. "Yeah?", "I'm listening.")
        so the user gets immediate audio feedback while the mic is already recording.
        """
        if self._state == State.IDLE:
            await self.transition(State.LISTENING, "wake_word_detected")

            # Fire-and-forget acknowledgment — must not block audio pipeline
            self._wake_ack_task = asyncio.create_task(self._speak_wake_ack())

    async def _on_speech_text(self, data: dict) -> None:
        """Speech transcribed → start processing."""
        if self._state == State.LISTENING:
            await self.transition(State.PROCESSING, "speech_recognized")

    async def _on_speech_failed(self, data: dict) -> None:
        """Speech recognition failed → back to idle."""
        if self._state == State.LISTENING:
            await self.transition(State.IDLE, "speech_failed")

    async def _on_action_complete(self, data: dict) -> None:
        """Action completed → respond to user."""
        if self._state == State.PROCESSING:
            await self.transition(State.RESPONDING, "action_complete")

    async def _on_action_failed(self, data: dict) -> None:
        """Action failed → error state."""
        if self._state == State.PROCESSING:
            await self.transition(State.ERROR, "action_failed")
            # Auto-recover: ERROR → IDLE after brief pause
            await asyncio.sleep(1)
            await self.transition(State.IDLE, "error_recovery")

    async def _on_tts_done(self, data: dict) -> None:
        """
        TTS finished → enter follow-up LISTENING mode.
        
        User has 12 seconds to issue a follow-up command
        before Jarvis returns to IDLE.
        """
        if self._state == State.RESPONDING:
            await self.transition(State.LISTENING, "follow_up_mode")

    # ------------------------------------------------------------------
    # Wake-word acknowledgment
    # ------------------------------------------------------------------

    async def _speak_wake_ack(self) -> None:
        """
        Speak a short, randomly-chosen acknowledgment phrase.

        Runs as a fire-and-forget task so it never blocks the
        audio pipeline or STT buffering.
        """
        try:
            from voice.responses import get_wake_response

            phrase = get_wake_response()

            # Use the event bus to trigger TTS — avoids circular imports
            # and lets the TTS engine handle queueing / interruption.
            await bus.emit(Event.ACTION_COMPLETE, {
                "action": "wake_ack",
                "response": phrase,
                "result": None,
            })
        except Exception:
            # Never let the ack crash the state machine
            logger.exception("Wake acknowledgment failed (non-fatal)")

    # ------------------------------------------------------------------
    # Timeout management
    # ------------------------------------------------------------------

    async def _setup_timeouts(self, state: State) -> None:
        """Set up auto-timeout tasks for time-limited states."""
        if state == State.LISTENING:
            self._follow_up_task = asyncio.create_task(
                self._listening_timeout()
            )
        elif state == State.PROCESSING:
            self._processing_timeout_task = asyncio.create_task(
                self._processing_timeout()
            )

    async def _listening_timeout(self) -> None:
        """If no speech detected within timeout, return to IDLE."""
        try:
            await asyncio.sleep(self._follow_up_timeout)
            if self._state == State.LISTENING:
                logger.info("⏱️ Listening timeout (%.0fs)", self._follow_up_timeout)
                await bus.emit(Event.FOLLOW_UP_TIMEOUT, {})
                await self.transition(State.IDLE, "listening_timeout")
        except asyncio.CancelledError:
            pass  # Cancelled because user spoke or state changed

    async def _processing_timeout(self) -> None:
        """If processing takes too long, force IDLE."""
        try:
            await asyncio.sleep(self._command_timeout)
            if self._state == State.PROCESSING:
                logger.warning("⏱️ Processing timeout (%.0fs)", self._command_timeout)
                await self.force_idle("processing_timeout")
        except asyncio.CancelledError:
            pass

    def _cancel_timeouts(self) -> None:
        """Cancel any pending timeout tasks."""
        if self._follow_up_task and not self._follow_up_task.done():
            self._follow_up_task.cancel()
            self._follow_up_task = None

        if self._processing_timeout_task and not self._processing_timeout_task.done():
            self._processing_timeout_task.cancel()
            self._processing_timeout_task = None

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<StateManager state={self._state.name} uptime={self.state_duration:.1f}s>"
