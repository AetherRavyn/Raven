import re

def chunk_markdown(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks = []
    lines = text.split('\n')
    
    current_chunk = []
    current_length = 0
    in_code_block = False
    code_language = ""

    def flush_chunk():
        nonlocal current_chunk, current_length
        if not current_chunk:
            return
            
        chunk_str = '\n'.join(current_chunk)
        if in_code_block:
            chunk_str += '\n```'
            
        chunks.append(chunk_str)
        current_chunk = []
        current_length = 0
        
        if in_code_block:
            current_chunk.append(f'```{code_language}')
            current_length = len(current_chunk[0]) + 1

    for line in lines:
        # Check if line toggles code block
        if line.strip().startswith('```'):
            if in_code_block:
                in_code_block = False
                code_language = ""
            else:
                in_code_block = True
                code_language = line.strip()[3:].strip()

        # If adding this line exceeds limit, flush
        if current_length + len(line) + 1 > limit and current_length > 0:
            flush_chunk()

        current_chunk.append(line)
        current_length += len(line) + 1

        # Fallback if a single line is insanely long
        while current_length > limit:
            # We have a single line that exceeds the limit (e.g. base64 string)
            # Just force flush it, it will break formatting but it's rare
            flush_chunk()

    if current_chunk:
        chunk_str = '\n'.join(current_chunk)
        if in_code_block and not chunk_str.strip().endswith('```'):
            chunk_str += '\n```'
        chunks.append(chunk_str)

    return chunks

test_str = "Some text\n" * 100 + "```python\nprint('hello')\n" * 200 + "```\n" + "More text" * 100
res = chunk_markdown(test_str, 500)
for i, c in enumerate(res):
    print(f"--- Chunk {i} ({len(c)} chars) ---")
    print(c[:50] + " ... " + c[-50:])
