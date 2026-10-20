"""Models Subloc can install, and the recommended setup for a given PC.

Sizes and checksums are from the Hugging Face repositories (verified 2026-10-20); downloads are checked
against the sha256 below. Recommendations favour "works everywhere" over "fastest": a weak PC gets
small models that run (slowly) on the processor rather than nothing.
"""

from dataclasses import dataclass

from .hardware import Hardware


@dataclass(frozen=True)
class SpeechModel:
    id: str  # faster-whisper name
    label: str
    size_gb: float
    note: str


@dataclass(frozen=True)
class TranslatorModel:
    id: str
    label: str
    repo: str  # Hugging Face repository
    file: str
    size_gb: float
    sha256: str
    min_vram_gb: float  # to run fully on an NVIDIA card; below that it runs on the processor/Vulkan
    note: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/main/{self.file}"


SPEECH = {
    "large-v3": SpeechModel("large-v3", "Best", 3.09, "most accurate, needs an NVIDIA card to be quick"),
    "medium": SpeechModel("medium", "Balanced", 1.53, "good accuracy, fine on the processor for short videos"),
    "small": SpeechModel("small", "Light", 0.49, "runs on any PC; less accurate on fast or noisy speech"),
}

TRANSLATORS = {
    "gemma-4-26b": TranslatorModel(
        "gemma-4-26b",
        "Gemma 4 26B",
        "lmstudio-community/gemma-4-26B-A4B-it-GGUF",
        "gemma-4-26B-A4B-it-Q4_K_M.gguf",
        16.80,
        "e19514d9541344001cb7c8eaf88704b8bf2e5d8f4e9aac12402eed360cffdfc4",
        18.0,
        "best quality; needs a 20 GB+ graphics card",
    ),
    "gemma-4-e4b": TranslatorModel(
        "gemma-4-e4b",
        "Gemma 4 E4B",
        "lmstudio-community/gemma-4-E4B-it-GGUF",
        "gemma-4-E4B-it-Q4_K_M.gguf",
        5.34,
        "0ffb122c8b6921f13cbc34186e052524d0b5803b17f4867b7197a561400b3770",
        6.5,
        "very good; fast on 8 GB cards",
    ),
    "gemma-4-e2b": TranslatorModel(
        "gemma-4-e2b",
        "Gemma 4 E2B",
        "lmstudio-community/gemma-4-E2B-it-GGUF",
        "gemma-4-E2B-it-Q4_K_M.gguf",
        3.43,
        "71e6e8cb64a76da1a734fb8f6ba389d2784950d9902f5e87244fca0a15190c94",
        4.5,
        "runs on any PC (slower on the processor)",
    ),
}


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    speech: str
    translator: str
    speed: str  # honest expectation, shown to the user

    @property
    def download_gb(self) -> float:
        return SPEECH[self.speech].size_gb + TRANSLATORS[self.translator].size_gb


PRESETS = {
    "best": Preset("best", "Best", "large-v3", "gemma-4-26b", "a 1-hour episode in about 6–10 minutes"),
    "balanced": Preset("balanced", "Balanced", "large-v3", "gemma-4-e4b", "a 1-hour episode in about 10–20 minutes"),
    "light": Preset(
        "light", "Light", "small", "gemma-4-e2b", "a 1-hour episode in about 1–3 hours on a laptop processor"
    ),
}


def recommend(hw: Hardware) -> Preset:
    if hw.nvidia and hw.vram_gb >= 20:
        return PRESETS["best"]
    if hw.nvidia and hw.vram_gb >= 6:
        return PRESETS["balanced"]
    return PRESETS["light"]
