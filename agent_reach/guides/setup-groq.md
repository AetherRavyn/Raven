# Groq Whisper Setup Guide

## What It Does
Use Groq's Whisper API for speech-to-text when YouTube/Bilibili videos do not have subtitles. Groq provides a free tier.

## Steps the agent can do automatically

1. Check whether Groq is already configured:
```bash
agent-reach doctor | grep -i "groq\|whisper"
```

2. If the user provides a key, save it to the config:
```python
from agent_reach.config import Config
c = Config()
c.set("groq_api_key", "user-provided-key")
```

3. Test it (optional):
```bash
curl -s https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer user-provided-key" \
  -o /dev/null -w "%{http_code}"
```

200 = available

## Steps the user must do manually

Tell the user:

> Video speech-to-text requires a Groq API key (free).
>
> Steps:
> 1. Open https://console.groq.com
> 2. Register with a Google account or email address
> 3. Click "API Keys" on the left
> 4. Click "Create API Key"
> 5. Copy the generated key and send it to me
>
> Groq provides a free tier, and it is enough for normal use.

## Steps after receiving the key

1. Save it to the config: `config.set("groq_api_key", key)`
2. Test API availability
3. Reply: "✅ Speech-to-text is enabled! I can now extract content from videos that do not have subtitles."
