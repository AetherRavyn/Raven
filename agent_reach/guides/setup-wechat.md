# WeChat Official Account Setup Guide

## What It Does
Read WeChat Official Account articles. This requires Playwright to handle WeChat's anti-bot protections.

## Steps the agent can do automatically

1. Check whether Playwright is installed:
```bash
python3 -c "import playwright; print('installed')" 2>&1
```

2. Install Playwright and a browser:
```bash
pip install playwright
playwright install chromium
```

3. Test after installation:
```bash
curl -s "https://r.jina.ai/https://mp.weixin.qq.com/s/a-test-link" -H "Accept: text/markdown"
```

## Steps the user must do manually

Tell the user:

> WeChat Official Account setup is simple. It only needs a browser component, about 150 MB.
>
> I can install it for you, so you do not need to do anything. The installation usually takes 1 to 2 minutes.
>
> After that, you can read WeChat Official Account articles directly, with no login required.

## Agent workflow

1. Install Playwright: `pip install playwright`
2. Install Chromium: `playwright install chromium`
3. Test by reading a WeChat article
4. Reply: "✅ WeChat Official Account is configured! Send me any article link and I can read it."
5. If installation fails (for example, due to disk space): "❌ Browser component installation failed. Disk space may be low (about 150 MB required)."
