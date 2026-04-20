import sys
sys.path.append('.')
from app.core.render import to_telegram_html

chunk = "Here is some code:\n```python\nprint('Hello "
res, mode = to_telegram_html(chunk)
print("CHUNK 1:")
print(res)

chunk2 = "World')\n```\nAnd more text **bold**!"
res2, mode2 = to_telegram_html(chunk2)
print("CHUNK 2:")
print(res2)
