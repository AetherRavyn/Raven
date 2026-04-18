# Twitter Advanced Setup Guide (bird CLI)

Basic Twitter reading is available for free through Jina Reader and needs no setup.

Advanced features require bird CLI (@steipete/bird):

- Search posts (`bird search`)
- Read full posts and conversation threads (`bird read`, `bird thread`)
- User timelines (`bird user-tweets`)

bird is a free, open-source tool (npm package `@steipete/bird`), but it needs your Twitter cookies.

## Quick Setup

1. Check whether bird is installed:

```bash
which bird && echo "installed" || echo "not installed"
```

2. Install bird:

```bash
npm install -g @steipete/bird
```

> Alternate package: `npm install -g @connormartin/bird`

3. Test whether it is configured correctly:

```bash
AUTH_TOKEN="xxx" CT0="yyy" bird search "test" -n 1
```

## Import Cookies (Cookie-Editor method, recommended)

1. Install the [Cookie-Editor](https://cookie-editor.com/) browser extension
2. Log in to x.com
3. Click the Cookie-Editor icon -> Export -> copy everything
4. Run the setup command:

```bash
agent-reach configure twitter-cookies "pasted cookie JSON"
```

This automatically extracts `auth_token` and `ct0`, then writes them to environment variables.

## Manual Cookie Configuration

If you already know `auth_token` and `ct0`:

1. Install bird if needed: `npm install -g @steipete/bird`

2. Set environment variables:

```bash
export AUTH_TOKEN="your_auth_token"
export CT0="your_ct0"
```

3. Test:

```bash
bird search "test" -n 1
```

## Proxy Configuration

> bird CLI also supports proxy configuration through environment variables:

```bash
export HTTP_PROXY="http://user:pass@host:port"
export HTTPS_PROXY="http://user:pass@host:port"
bird search "test" -n 1
```

You can also use a global proxy tool:

```bash
proxychains bird search "test" -n 1
```
