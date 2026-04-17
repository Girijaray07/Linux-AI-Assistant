"""
Jarvis — Main Entry Point
===========================
Initializes all modules, starts the async event loop,
and orchestrates the assistant lifecycle.

Run with: python -m core.main
"""

import asyncio
import signal
import sys
import logging
import logging.handlers
from pathlib import Path

from core import config
from core.events import bus, Event
from core.state_manager import StateManager, State


logger = logging.getLogger("jarvis")


def setup_logging() -> None:
    """Configure logging with file rotation and console output."""
    cfg = config.get("logging", default={})
    level = getattr(logging, cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = cfg.get("file", "")

    # Root logger
    root = logging.getLogger("jarvis")
    root.setLevel(level)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console_fmt = logging.Formatter(
        "%(asctime)s │ %(levelname)-7s │ %(name)-20s │ %(message)s",
        datefmt="%H:%M:%S",
    )
    console.setFormatter(console_fmt)
    root.addHandler(console)

    # File handler (if configured)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=cfg.get("max_size_mb", 10) * 1024 * 1024,
            backupCount=cfg.get("backup_count", 3),
        )
        file_handler.setLevel(logging.DEBUG)  # Always verbose in file
        file_fmt = logging.Formatter(
            "%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s"
        )
        file_handler.setFormatter(file_fmt)
        root.addHandler(file_handler)

    logger.info("Logging configured (level=%s)", cfg.get("level", "INFO"))


class Jarvis:
    """
    Main application orchestrator.
    
    Manages the lifecycle of all subsystems:
    - Audio pipeline (wake word + STT)
    - Brain (LLM + intent parser)
    - Actions (system control, media, apps, automation)
    - Voice output (TTS)
    - UI overlay (separate process)
    - Memory (SQLite)
    """

    def __init__(self):
        self.state_manager: StateManager | None = None
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._intent_router = None
        self._action_registry = None

    async def start(self) -> None:
        """Initialize all modules and start the main loop."""
        logger.info("=" * 60)
        logger.info("  🤖 Jarvis AI Assistant — Starting")
        logger.info("=" * 60)

        # Load config
        cfg = config.load_config()
        assistant_name = cfg.get("assistant", {}).get("name", "Jarvis")

        # Initialize state machine (auto-registers event handlers)
        self.state_manager = StateManager()
        logger.info("State machine ready: %s", self.state_manager)

        # -------------------------------------------------------
        # Module initialization (lazy — loaded when phase is built)
        # -------------------------------------------------------

        # Phase 2: Audio pipeline
        await self._init_audio()

        # Phase 3: Actions (must be BEFORE brain so registry is ready)
        await self._init_actions()

        # Phase 4: Brain / LLM
        await self._init_brain()

        # Phase 5: Connect brain ↔ actions (critical link)
        if self._intent_router and self._action_registry:
            # set_registry() provides BOTH the formatted text for LLM prompts
            # AND the live registry reference for output validation
            self._intent_router.set_registry(self._action_registry)
            logger.info("🔗 Brain connected to action registry (%d actions)",
                        self._action_registry.count)

        # Phase 6: Voice output
        await self._init_voice()

        # Phase 7: UI overlay (separate process)
        await self._init_ui()

        # Phase 8: Memory
        await self._init_memory()

        # -------------------------------------------------------
        self._running = True

        logger.info("✅ %s is ready and listening for wake word", assistant_name)
        logger.info("=" * 60)

        # Keep running until shutdown
        await self._run_forever()

    async def _init_audio(self) -> None:
        """Initialize audio pipeline (wake word + STT)."""
        try:
            from audio.listener import AudioPipeline
            pipeline = AudioPipeline()
            task = asyncio.create_task(pipeline.run())
            self._tasks.append(task)
            logger.info("🎤 Audio pipeline started")
        except ImportError:
            logger.warning("⏭️  Audio pipeline not yet implemented — skipping")
        except Exception:
            logger.exception("❌ Failed to start audio pipeline")

    async def _init_brain(self) -> None:
        """Initialize LLM and intent parser."""
        try:
            from brain.intent_parser import IntentRouter
            router = IntentRouter()
            bus.on(Event.SPEECH_TEXT, router.handle)
            self._intent_router = router
            logger.info("🧠 Brain / Intent router ready")
        except ImportError:
            logger.warning("⏭️  Brain not yet implemented — skipping")
        except Exception:
            logger.exception("❌ Failed to initialize brain")

    async def _init_actions(self) -> None:
        """Initialize action registry and handlers."""
        try:
            from actions.action_registry import ActionRegistry
            registry = ActionRegistry()
            registry.auto_register()
            bus.on(Event.INTENT_PARSED, registry.dispatch)
            self._action_registry = registry
            logger.info("⚙️  Action registry ready (%d actions)", registry.count)
        except ImportError:
            logger.warning("⏭️  Action registry not yet implemented — skipping")
        except Exception:
            logger.exception("❌ Failed to initialize actions")

    async def _init_voice(self) -> None:
        """Initialize TTS engine."""
        try:
            from voice.tts import TTSEngine
            tts = TTSEngine()
            bus.on(Event.ACTION_COMPLETE, tts.handle_response)
            logger.info("🔊 TTS engine ready")
        except ImportError:
            logger.warning("⏭️  TTS engine not yet implemented — skipping")
        except Exception:
            logger.exception("❌ Failed to initialize TTS")

    async def _init_ui(self) -> None:
        """Launch UI overlay as a separate process."""
        ui_cfg = config.get("ui", default={})
        if not ui_cfg.get("enabled", True):
            logger.info("🖥️  UI overlay disabled in config")
            return

        try:
            from ui.ui_bridge import UIBridge
            bridge = UIBridge()
            task = asyncio.create_task(bridge.run())
            self._tasks.append(task)
            logger.info("🖥️  UI overlay bridge started")
        except ImportError:
            logger.warning("⏭️  UI overlay not yet implemented — skipping")
        except Exception:
            logger.exception("❌ Failed to start UI overlay")

    async def _init_memory(self) -> None:
        """Initialize persistent memory system."""
        try:
            from brain.memory import MemorySystem
            memory = MemorySystem()
            await memory.initialize()
            bus.on(Event.ACTION_COMPLETE, memory.log_interaction)
            logger.info("💾 Memory system ready")
        except ImportError:
            logger.warning("⏭️  Memory system not yet implemented — skipping")
        except Exception:
            logger.exception("❌ Failed to initialize memory")

    async def _run_forever(self) -> None:
        """Keep the main loop alive until shutdown signal."""
        shutdown_event = asyncio.Event()

        def _signal_handler():
            logger.info("🛑 Shutdown signal received")
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

        # Wait for shutdown
        await shutdown_event.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        """Graceful shutdown of all subsystems."""
        logger.info("🛑 Shutting down Jarvis...")
        self._running = False

        # Emit shutdown event so modules can clean up
        await bus.emit(Event.SHUTDOWN, {})

        # Cancel all background tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to finish
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        logger.info("👋 Jarvis stopped. Goodbye.")


def main():
    """Entry point."""
    # Load config first (creates data directories)
    config.load_config()

    # Setup logging
    setup_logging()

    # Run
    jarvis = Jarvis()
    try:
        asyncio.run(jarvis.start())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()