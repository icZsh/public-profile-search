import html


def safe_text(value: str, *, max_length: int = 500) -> str:
    cleaned = " ".join(value.split())
    return html.escape(cleaned[:max_length], quote=True)
