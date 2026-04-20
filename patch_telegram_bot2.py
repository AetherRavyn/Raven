import re

with open("app/telegram/bot.py", "r") as f:
    content = f.read()

chunker_code = """
    @staticmethod
    def _chunk_text(text: str, limit: int) -> list[str]:
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            # Try to break at a newline within the limit window
            cut = text.rfind("\n", 0, limit)
            if cut <= 0:
                # Fall back to space
                cut = text.rfind(" ", 0, limit)
            if cut <= 0:
                # Hard cut
                cut = limit
            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")
        return chunks
"""

old_send = """            # Chunking logic for long text messages
            chunks = []
            if len(message_text) > TELEGRAM_TEXT_LIMIT:
                # Naive chunking by exactly TELEGRAM_TEXT_LIMIT characters
                for i in range(0, len(message_text), TELEGRAM_TEXT_LIMIT):
                    chunks.append(message_text[i:i + TELEGRAM_TEXT_LIMIT])
            else:
                chunks = [message_text]
                
            for chunk in chunks:
                rendered_text, parse_mode = to_telegram_html(chunk)"""

new_send = """            # Use smart chunking for long text messages
            chunks = TelegramBot._chunk_text(message_text, TELEGRAM_TEXT_LIMIT)
            for chunk in chunks:
                rendered_text, parse_mode = to_telegram_html(chunk)"""

if "def _chunk_text" not in content:
    # Add chunker to TelegramBot class
    # Find `def _send_telegram` and insert chunker_code right before it
    content = content.replace("    def register_output_sender(", chunker_code + "\n    def register_output_sender(")

if "Naive chunking" in content:
    content = content.replace(old_send, new_send)
    with open("app/telegram/bot.py", "w") as f:
        f.write(content)
    print("Telegram patched with smarter chunking")
else:
    print("Failed to patch Telegram")
