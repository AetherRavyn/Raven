import re

with open("app/discord/discordapp.py", "r") as f:
    content = f.read()

target = """        # If there is an explicit file or the text exceeds the limit, send as
        # a file attachment so nothing is lost.
        if len(content_text) > DISCORD_CONTENT_LIMIT and not payload.file_path:
            fd, temp_file_path = tempfile.mkstemp(
                prefix="saras_output_", suffix=".txt", text=True
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content_text)
            content_text = "Output exceeded message limit. Sent as file attachment."

        file_path = payload.file_path or temp_file_path"""

replacement = """        # If there is an explicit file or the text is extremely large, send as
        # a file attachment so nothing is lost.
        temp_file_path = None
        if len(content_text) > 20000 and not payload.file_path:
            fd, temp_file_path = tempfile.mkstemp(
                prefix="saras_output_", suffix=".txt", text=True
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content_text)
            content_text = "Output was extremely long. Sent as file attachment."

        file_path = payload.file_path or temp_file_path"""

if target in content:
    content = content.replace(target, replacement)
    with open("app/discord/discordapp.py", "w") as f:
        f.write(content)
    print("Discord patched")
else:
    print("Discord patch failed")
