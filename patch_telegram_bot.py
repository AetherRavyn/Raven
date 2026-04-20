import re

with open("app/telegram/bot.py", "r") as f:
    content = f.read()

old_logic = """        message_text = payload.text or payload.caption or ""
        if len(message_text) > TELEGRAM_TEXT_LIMIT and not payload.file_path:
            fd, temp_file_path = tempfile.mkstemp(
                prefix="saras_output_", suffix=".txt", text=True
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(message_text)
            message_text = "Output exceeded message limit. Sent as file attachment."

        file_path = payload.file_path or temp_file_path
        caption_text = (payload.caption or message_text or "")[:TELEGRAM_CAPTION_LIMIT]"""

new_logic = """        message_text = payload.text or payload.caption or ""
        temp_file_path = None
        
        # If there's an actual file to send or the message is insanely huge (> 20000 chars), fallback to file
        if len(message_text) > 20000 and not payload.file_path:
            fd, temp_file_path = tempfile.mkstemp(
                prefix="saras_output_", suffix=".txt", text=True
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(message_text)
            message_text = "Output was extremely long. Sent as file attachment."

        file_path = payload.file_path or temp_file_path
        caption_text = (payload.caption or message_text or "")[:TELEGRAM_CAPTION_LIMIT]"""

old_send = """        try:
            rendered_text, parse_mode = to_telegram_html(message_text)
            send_kwargs = {**kwargs}
            if parse_mode:
                send_kwargs["parse_mode"] = parse_mode
            await app.bot.send_message(
                chat_id=chat_id,
                text=rendered_text,
                **send_kwargs,
            )
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)"""

new_send = """        try:
            # Chunking logic for long text messages
            chunks = []
            if len(message_text) > TELEGRAM_TEXT_LIMIT:
                # Naive chunking by exactly TELEGRAM_TEXT_LIMIT characters
                for i in range(0, len(message_text), TELEGRAM_TEXT_LIMIT):
                    chunks.append(message_text[i:i + TELEGRAM_TEXT_LIMIT])
            else:
                chunks = [message_text]
                
            for chunk in chunks:
                rendered_text, parse_mode = to_telegram_html(chunk)
                send_kwargs = {**kwargs}
                if parse_mode:
                    send_kwargs["parse_mode"] = parse_mode
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=rendered_text,
                    **send_kwargs,
                )
                import asyncio
                await asyncio.sleep(0.5) # Slight delay to prevent rate limit on multi-chunk messages
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)"""

content = content.replace(old_logic, new_logic)
content = content.replace(old_send, new_send)

with open("app/telegram/bot.py", "w") as f:
    f.write(content)
print("Telegram patched")
