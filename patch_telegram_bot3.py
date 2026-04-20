import re

with open("app/telegram/bot.py", "r") as f:
    content = f.read()

chunker_code = """
def _chunk_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to break at a newline within the limit window
        cut = text.rfind("\\n", 0, limit)
        if cut <= 0:
            # Fall back to space
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            # Hard cut
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\\n")
    return chunks

"""

if "def _chunk_text" not in content:
    # Add _chunk_text near the top, after imports
    content = content.replace("TELEGRAM_TEXT_LIMIT = 4096", "TELEGRAM_TEXT_LIMIT = 4096\n" + chunker_code)
    with open("app/telegram/bot.py", "w") as f:
        f.write(content)
    print("Added _chunk_text function")
