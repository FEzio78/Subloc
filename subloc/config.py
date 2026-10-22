"""App-wide settings shared by the window and the command line (config.json in the data folder)."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import default_data_dir


def data_dir() -> Path:
    """Where models, logs and settings live (see subloc.default_data_dir)."""
    return default_data_dir()


def models_dir() -> Path:
    return data_dir() / "models"


@dataclass
class Config:
    setup_done: bool = False
    ui_lang: str = "en"
    provider: str = "server"  # "builtin" (Subloc runs llama-server) | "server" (LM Studio, Ollama, any address)
    server_url: str = "http://localhost:1234"
    builtin_model: str = ""  # translator catalog id (catalog.TRANSLATORS) or a path to a .gguf file
    speech_model: str = "large-v3"
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Config":
        path = data_dir() / "config.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        path = data_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")
        tmp.replace(path)

    def builtin_model_path(self) -> Path | None:
        from .catalog import TRANSLATORS

        if self.builtin_model in TRANSLATORS:
            return models_dir() / "llm" / TRANSLATORS[self.builtin_model].file
        return Path(self.builtin_model) if self.builtin_model else None
