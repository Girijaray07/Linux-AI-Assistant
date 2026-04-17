# 🎙️ Jarvis: Privacy-First, Offline AI Assistant for Linux

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-orange.svg)](https://www.kernel.org/)

**Jarvis** is a modular, high-performance, and privacy-centric AI assistant designed specifically for the Linux desktop (optimized for Fedora/GNOME). Unlike traditional assistants that rely on cloud APIs, Jarvis operates on an **offline-first** philosophy, performing speech recognition, intent parsing, and neural speech synthesis entirely on your local hardware.

---

## ✨ Key Features

- **🛡️ Privacy by Design**: All voice processing (STT), reasoning (LLM), and speech (TTS) happen locally. No audio data ever leaves your machine.
- **⚡ Hybrid Intent Engine**: A three-tier routing system that combines high-speed Regex/Semantic matching with a sophisticated LLM fallback (via Ollama).
- **🎤 Neural Voice Interface**: 
    - **STT**: Powered by `faster-whisper` for near-instant, high-accuracy transcription.
    - **TTS**: High-quality, interruptible neural speech synthesis using `Piper`.
- **🛠️ Desktop Integration**: Native GNOME extension and overlay for visual feedback and seamless system control.
- **🔒 Secure Auth**: Voiceprint authentication for sensitive operations like `sudo` or file deletion.
- **🔄 Event-Driven Architecture**: Fully asynchronous Core built on a central Event Bus, ensuring zero-latency response times.

---

## 🏗️ Technical Architecture

Jarvis follows a strictly decoupled, **Pub-Sub Event-Driven** design.

### The Lifecycle of a Request
1.  **Wake**: The `AudioPipeline` feeds 16kHz chunks to the `WakeWordDetector` (Vosk/openWakeWord).
2.  **Listen**: Upon trigger, the system shifts to `LISTENING` mode. An interruptible "Yeah?" acknowledgement plays while the microphone buffers speech.
3.  **Transcribe**: Silence detection (VAD) triggers `STTEngine` (Whisper) to convert audio to text.
4.  **Think**: The `IntentRouter` evaluates the text:
    - **Tier 1**: Semantic Fast Match (Keyword verbs).
    - **Tier 2**: Regex Path (System/Media controls).
    - **Tier 3**: Contextual LLM (Ollama/Phi-3) for complex natural language.
5.  **Act**: The `ActionRegistry` executes the resolved command (App launch, volume control, web search, etc.).
6.  **Speak**: `TTSEngine` provides verbal confirmation via neural synthesis.

---

## 🛠️ Tech Stack

- **Core**: Python 3.10+, `asyncio`
- **Audio**: `PyAudio`, `Vosk` / `openWakeWord`
- **STT**: `faster-whisper` (CTranslate2)
- **LLM**: `Ollama` (default: `phi3:mini`)
- **TTS**: `Piper` (ONNX Runtime)
- **UI**: GNOME Shell Extension (JavaScript), Python Overlay (Gtk/Qt)

---

## 🚀 Getting Started

### Prerequisites
- Linux (Fedora/GNOME recommended)
- Python 3.10 or higher
- [Ollama](https://ollama.com/) installed and running (`ollama run phi3:mini`)
- `piper-tts` and `ffmpeg` installed on your system.

### Installation
1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/jarvis.git
   cd jarvis
   ```

2. **Set up Virtual Environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Install GNOME Extension** (Optional):
   ```bash
   cd ui/gnome-extension
   ./install_extension.sh
   ```

4. **Configure**:
   Edit `jarvis.yaml` to match your hardware paths (especially TTS voice paths and Mic indices).

---

## ⚙️ Configuration (`jarvis.yaml`)

Jarvis is highly customizable via the central configuration file:

```yaml
assistant:
  wake_word: "jarvis"
  follow_up_timeout: 12  # Seconds to keep listening

stt:
  model_size: "base.en"  # tiny, base, small, medium
  fallback: "google"     # Cloud fallback if offline fails

llm:
  model: "phi3:mini"
  temperature: 0.2

security:
  voice_auth_enabled: true
  sensitive_actions: ["system.sudo", "file.delete"]
```

---

## 📁 Project Structure

```text
├── core/             # Application lifecycle & Event Bus
├── audio/            # Wake word & Microphone processing
├── brain/            # Intent parsing & LLM integration
├── actions/          # Extensible command modules (Apps, Media, Sys)
├── voice/            # STT and Neural TTS engines
├── ui/               # GNOME Extension & Desktop Overlay
├── data/             # Local models (Vosk, Wake Word)
└── tests/            # Pytest suite
```

---

## 🤝 Contributing

We welcome contributions! Whether it's adding new `actions/`, improving the `brain/` logic, or enhancing the `ui/`. 
1. Fork the repo.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes.
4. Push to the branch.
5. Open a Pull Request.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

---
*Built with ❤️ for the Linux Community.*
