# Reddit Proxy Setup Guide

## What It Does
Reddit blocks many server IPs, and direct access returns 403. An ISP proxy (Residential/ISP Proxy) is required to read full Reddit posts and comments.

**Note:** Even without a proxy, Reddit content can still be found through Exa search (you only need the Exa API key). The proxy is only for reading full posts and comments.

## Steps the agent can do automatically

1. Check the current status:
```bash
agent-reach doctor | grep "Reddit"
```

2. If the user provides a proxy, test connectivity:
```bash
curl -s --proxy "user-provided-proxy" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  "https://www.reddit.com/r/test.json?limit=1" \
  -o /dev/null -w "%{http_code}"
```

200 = usable, 403 = proxy blocked, anything else = configuration error

3. Write the configuration:
```python
from agent_reach.config import Config
c = Config()
c.set("reddit_proxy", "http://username:password@ip:port")
```

## Steps the user must do manually

Tell the user:

> To read full Reddit posts and comments, you need an ISP proxy (about $3-10/month).
>
> Recommended proxy providers (pick one):
> 1. **Smartproxy** (https://smartproxy.com) — ISP proxy, billed by traffic
> 2. **Bright Data** (https://brightdata.com) — large provider, ISP proxy
> 3. **IPRoyal** (https://iproyal.com) — inexpensive, good for beginners
> 4. **ProxyEmpire** (https://proxyempire.io) — has Reddit-specific proxies
>
> When buying, choose:
> - Type: **ISP Proxy** (do not choose Datacenter, it will get blocked)
> - Region: **United States**
> - Protocol: **HTTP**
>
> After purchase, you will get a proxy address in a format like:
> `http://username:password@IP-address:port`
>
> Send that address to me.
>
> ⚠️ If you do not want to spend money, you can skip this. I can still find Reddit content through search engines, but I will not be able to read the full posts and comments.

## Steps after receiving a proxy

1. Test the proxy with curl to see whether reddit.com returns 200
2. If successful, write the config: `config.set("reddit_proxy", proxy_url)`
3. Reply: "✅ Full Reddit reading is enabled! I can now read Reddit posts and all comments."
4. If it fails, tell the user: "❌ This proxy cannot access Reddit. Please check whether the proxy is valid or try another one."
