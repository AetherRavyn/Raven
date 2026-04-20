import re
import os

with open("test_orchestrator_filetool.py", "r") as f:
    content = f.read()

# Instead of checking text, we should check `payload.tool_traces` or `self._annotation_lines(payload)`
# Wait, actually since BotSignal has `_annotation_lines`, we can just call `botsignal._annotation_lines(payload)` in the tests!

def replace_asserts(match):
    full_assert = match.group(0)
    # self.assertIn("[tool:git_ops action:branch status:ok]", text)
    # becomes:
    # self.assertTrue(any("[tool:git_ops action:branch status:ok]" in line for line in botsignal._annotation_lines(payload)))
    inner = match.group(1) # The string being asserted
    # But wait, `text` might be `payload.text`. If the test uses `text`, we can just do:
    return f'self.assertTrue(any({inner} in line for line in botsignal._annotation_lines(payload)) or {inner} in (payload.text or ""))'

# We have lines like: `self.assertIn("[source:prompt]", text)`
# `self.assertIn("[tool:git_ops action:branch status:ok]", text)`
# Let's just do a regex replace.
content = re.sub(r'self\.assertIn\((r?".*?\[(?:source|tool).*?\](?:.*?)?"), text\)', replace_asserts, content)
content = re.sub(r'self\.assertIn\((r?".*?\[(?:source|tool).*?\](?:.*?)?"),\s*payload\.text or ""\)', replace_asserts, content)

content = re.sub(r'self\.assertNotIn\((r?".*?\[(?:source|tool).*?\](?:.*?)?"), text\)', 
                 lambda m: f'self.assertFalse(any({m.group(1)} in line for line in botsignal._annotation_lines(payload)) or {m.group(1)} in (payload.text or ""))', content)
                 
content = re.sub(r'self\.assertNotIn\((r?".*?\[(?:source|tool).*?\](?:.*?)?"),\s*payload\.text or ""\)', 
                 lambda m: f'self.assertFalse(any({m.group(1)} in line for line in botsignal._annotation_lines(payload)) or {m.group(1)} in (payload.text or ""))', content)

with open("test_orchestrator_filetool.py", "w") as f:
    f.write(content)
