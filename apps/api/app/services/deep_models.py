from typing import Final

DEFAULT_DEEP_SYNTHESIS_MODEL: Final = "openai/gpt-5.6-luna"

CURATED_DEEP_SYNTHESIS_MODELS: Final[frozenset[str]] = frozenset(
    {
        DEFAULT_DEEP_SYNTHESIS_MODEL,
        "openai/gpt-5.4-nano",
        "openai/gpt-5.4-mini",
        "openai/gpt-oss-120b",
        "deepseek/deepseek-v4-flash-0731",
        "qwen/qwen3.5-35b-a3b",
        "z-ai/glm-5.2",
    }
)


def is_curated_deep_synthesis_model(value: object) -> bool:
    return isinstance(value, str) and value in CURATED_DEEP_SYNTHESIS_MODELS
