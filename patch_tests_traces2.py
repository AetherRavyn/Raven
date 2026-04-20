import re

with open("test_orchestrator_filetool.py", "r") as f:
    content = f.read()

content = content.replace('text = captured[0].text or ""', 'payload = captured[0]\n        text = payload.text or ""')

def replace_asserts(match):
    inner = match.group(1)
    return f'self.assertTrue(any({inner} in line for line in botsignal._annotation_lines(payload)) or {inner} in (payload.text or ""))'

content = re.sub(r'self\.assertIn\((r?".*?\[(?:source|tool).*?\](?:.*?)?"),\s*text\)', replace_asserts, content)

with open("test_orchestrator_filetool.py", "w") as f:
    f.write(content)
