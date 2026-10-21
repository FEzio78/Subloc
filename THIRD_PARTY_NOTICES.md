# Third-party software

Subloc is licensed under the GNU GPL v3.0 or later (see `LICENSE` and the additional permission at the
end of this file). It builds on the following projects. Their licences apply to their parts.

## Libraries (installed by Python)

| Component | Licence | Used for |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | speech recognition |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT | running Whisper on the GPU/CPU |
| [Silero VAD](https://github.com/snakers4/silero-vad) (inside faster-whisper) | MIT | finding speech |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | MIT | running Silero VAD |
| [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/) | LGPL-3.0 | interface |
| [python-mpv](https://github.com/jaseg/python-mpv) | GPL-2.0-or-later / LGPL-2.1-or-later | player bindings |
| [httpx](https://github.com/encode/httpx) | BSD-3-Clause | talking to the translator, downloads |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | Apache-2.0 | model downloads |
| [tokenizers](https://github.com/huggingface/tokenizers) | Apache-2.0 | Whisper tokenizer |
| [NumPy](https://numpy.org) | BSD-3-Clause | audio handling |
| [Pillow](https://python-pillow.org) | MIT-CMU | images |
| [PyAV](https://github.com/PyAV-Org/PyAV) | BSD-3-Clause | dependency of faster-whisper |
| NVIDIA CUDA runtime, cuBLAS, cuDNN, NVRTC | NVIDIA proprietary (redistributable) | GPU acceleration |

## Programs (fetched by `tools/fetch_vendor.py`, bundled by the installer)

| Component | Licence | Used for |
|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server` | MIT | built-in translator |
| [mpv](https://mpv.io) (`libmpv`, build by shinchiro) | GPL-2.0-or-later | built-in player |
| [FFmpeg](https://ffmpeg.org) | GPL-2.0-or-later / LGPL-2.1-or-later (build-dependent) | reading video and audio, burn-in |

## Fonts

| Component | Licence |
|---|---|
| [IBM Plex Sans, Serif, Sans Arabic, Mono](https://github.com/IBM/plex) | SIL Open Font License 1.1 (`subloc/assets/fonts/OFL-LICENSE.txt`) |

## AI models (downloaded by the user during Setup, not part of Subloc)

| Model | Licence |
|---|---|
| [Whisper](https://github.com/openai/whisper) (via Systran's faster-whisper conversions) | MIT |
| [Gemma 4](https://ai.google.dev/gemma) (GGUF builds by lmstudio-community) | [Gemma Terms of Use](https://ai.google.dev/gemma/terms) |

---

## Additional permission under GNU GPL version 3 section 7

Copyright (C) 2026 the Subloc authors.

If you modify this Program, or any covered work, by linking or combining it with the NVIDIA CUDA
Toolkit libraries (including the CUDA runtime, cuBLAS, cuDNN and NVRTC), or a modified version of
those libraries, containing parts covered by the terms of the NVIDIA software licence agreements, the
licensors of this Program grant you additional permission to convey the resulting work.
