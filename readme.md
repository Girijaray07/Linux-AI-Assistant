# Jarvis AI Assistant — Project Summary

This document provides a comprehensive overview of the `jarvis` project repository up to the current state. It serves as a context guide detailing the architecture, module responsibilities, control flows, and key configurations.

## Architecture Overview

Jarvis is a modular, offline-first, continuous-listening AI assistant for Linux desktops (designed specifically with Fedora/GNOME in mind). The application uses a completely async, **event-driven architecture** relying on an internal pub-sub Event Bus. This ensures decoupled modules, concurrent processing, and a highly responsive user experience. 

The system relies on a central **State Machine** (`StateManager`) that transitions across various modes: `IDLE`, `LISTENING`, `PROCESSING`, `RESPONDING`, and `ERROR`. 

### State Machine Flow
- **`IDLE`**: Awaiting wake word. The audio pipeline feeds 16kHz audio chunks solely to the wake word detector (minimal CPU footprint).
- **`LISTENING`**: Triggered by the wake word. The microphone actively buffers audio. A Voice Activity Detector (VAD) monitors RMS energy, and when significant silence follows speech, the buffer is dispatched to the Speech-to-Text (STT) engine. Co-currently, an asynchronous TTS acknowledgment ("Yeah?", "I'm listening") is triggered.
- **`PROCESSING`**: Audio is evaluated by the intent router (Regex fast-matches semantic natural language matches, or LLM evaluation). An action is triggered from the Action Registry.
- **`RESPONDING`**: The TTS engine speaks the response. The TTS is interruptible if the user speaks again. 
- **`ERROR`**: Failsafe state that auto-recovers to `IDLE`.

---

## Core Components (`core/`)

- **`main.py`**: The application orchestrator. Bootstraps configuration, initializes the `StateManager` and sub-modules lazily (Audio, Actions, Brain, Voice, UI, Memory). Starts the async event loop and manages graceful shutdown.
- **`events.py`**: The `EventBus` singleton. Manages the pub-sub system spanning `WAKE_WORD`, `SPEECH_TEXT`, `INTENT_PARSED`, `ACTION_COMPLETE`, `TTS_START`, `STATE_CHANGE` etc., allowing decoupled system updates.
- **`state_manager.py`**: A strict state machine overseeing timeout mechanics (e.g., returning to `IDLE` after 12s of conversational silence or 30s of dead processing). Triggers initial fire-and-forget randomized voice acknowledgments upon waking.

---

## Audio Pipeline (`audio/`)

- **`listener.py` (`AudioPipeline`)**: The continuous PyAudio capture loop. Handles device assignment, constant buffer rotation, RMS-energy calculation for VAD (dynamic noise floor thresholding), and feeds raw audio chunks to either the wake word module or the STT buffer depending on the system `State`.
- **`wake_word.py` (`WakeWordDetector`)**: Leverages `openwakeword` with the `hey_jarvis` ONNX model. Efficiently evaluates 1-second audio sliding windows at a configured sensitivity index to spot wake triggers without cloud latency.
- **`stt.py` (`STTEngine`)**: A hybrid engine. It prefers local, offline processing via `faster-whisper` (default: `base.en`). If local processing fails, it falls back to a network call using Google's Speech Recognition API. 

---

## The "Brain" (`brain/`)

- **`intent_parser.py` (`IntentRouter`)**: The routing layer for converting raw transcripts into executable actions. Work flows in three hierarchical layers:
  1. **Semantic Fast Match Layer**: Extremely fast keyword detection with specific verbs to open web tools directly (e.g., "login to my instagram", "search for Python tutorials", "open YouTube"). 
  2. **Regex Fast Path**: High-priority OS/media commands matched by Regex (e.g., "volume up", "pause music", "silent mode").
  3. **Contextual LLM Fallback**: If natural language routing fails, the prompt is injected alongside recent conversation history to the LLM. LLM output validation acts as a powerful safety gate by dropping hallucinatory actions / parameter leaks.
- **`llm.py` (`LLMClient`)**: Client to communicate with an external AI inference tool via Ollama HTTP APIs (configured by default to locally hosted `phi3:mini`). Requires STRICT JSON output mode.
- **`prompts.py`**: Defines `SYSTEM_PROMPT` designed to constrain the LLM into ONLY responding with a strict JSON interface (`action`, `params`, `response`). Contains heavily weighted few-shot examples prohibiting credential extraction or undefined functionalities.
- **`context.py` (`ContextManager`)**: Keeps track of recent conversational history (sliding window queue), and injects real-time information (Current Time, Active User Mode) into the prompt.

---

## Action Execution (`actions/`)

- **`action_registry.py` (`ActionRegistry`)**: The central hub where feature modules register actionable commands. The router cross-verifies LLM outputs via `.get_action_names()` to prevent unknown commands from executing. Contains a fuzzy-matching logic to gracefully resolve slight LLM typos (e.g., "play_music" -> "media.play").
- **`apps.py`**: Handles finding and opening applications via XDG Desktop Entries or explicit aliases, includes URL routing capabilities into browser setups.
- Additional internal modules support `media.py`, `system.py`, `web_search.py`, `automation.py` capabilities.

---

## Voice Output (`voice/`)

- **`tts.py` (`TTSEngine`)**: Asynchronous, highly responsive queue-based speech system. Prioritizes the neural `piper` local TTS engine (which applies a `sox` lowpass filtering layer for smoother playback). Features a hard interruptible fallback logic (e.g., if the user interrupts the response before it finishes via `SPEECH_START` or `WAKE_WORD`).
- **`responses.py`**: A centralized pooling system supplying randomly selected variations of wake acknowledgments (ranging from short snips like "Yeah?" (highly weighted) to conversational phrases like "How can I help?"). Ensures dynamic assistant personality. 

---

## User Interface (`ui/`)

- **`overlay.py` / `ui_bridge.py`**: A graphical desktop overlay capable of rendering notifications and internal system states (like LISTENING or PROCESSING indicators), communicating alongside the event bus on a separate process.

---

## Configuration (`jarvis.yaml`)

The entire assistant lifecycle logic is parameterized within the central `/jarvis.yaml` file:
- **Audio Tuning**: Chunk sizing, `energy_threshold` adjustments, OpenWakeWord sensitivity/cooldowns.
- **Model Adjustments**: Choosing active Whisper models (`base.en`), LLM parameters (`phi3:mini`, temperatures), and local pathings pointing towards `.onnx` TTS voices.
- **Security Checklists**: Voiceprint authentication and arrays isolating high risk processes (e.g `system.sudo`, `file.delete`) that force system auth thresholds.

---

## Expected Information Lifecycle (A typical request)

1. **WAKE**: User says "Hey Jarvis". `listener.py` captures chunk -> `wake_word.py` evaluates -> emits `WAKE_WORD` event.
2. **ACKNOWLEDGE**: `state_manager.py` catches `WAKE_WORD` -> shifts mode to `LISTENING` -> `asyncio.create_task` fires `responses.py` to play short TTS "Yeah?", keeping microphone un-blocked.
3. **TRANSCRIBE**: User says "Login to Instagram". `listener.py` spots Voice Activity, then records silence. Buffer passes to `stt.py` (`faster-whisper`), returning text.
4. **THINK**: Text hits `intent_parser.py`. The **Semantic Fast Match Layer** catches "Instagram" + "Login" keyword verbs.
5. **DO**: Intent routing constructs `{ "action": "app.open", "params": { "url": "..."} }` bypassing the LLM entirely -> sends to `action_registry.py`.
6. **ACT**: `apps.py` catches the parameters and leverages `subprocess` to launch the browser UI target URL. Event emits `ACTION_COMPLETE`.
7. **SPEAK**: Finally `tts.py` acknowledges the action completed with a final neural TTS output "Opening Instagram login page". Uptime gracefully falls back into `IDLE`.
