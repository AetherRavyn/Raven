---
name: Finance Briefing
module_id: skill.bundled.finance_briefing
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "stock.*price|market.*summary"
    confidence: 0.85
  - pattern: "crypto.*price|bitcoin"
    confidence: 0.85
  - pattern: "portfolio|investments"
    confidence: 0.80
capabilities: [stock-quotes, crypto-prices, market-summary]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Finance Briefing

Get stock quotes, crypto prices, portfolio alerts, and market summaries.

## Procedure
1. Use `stock_quote` for stock prices and history
2. Use `crypto_price` for crypto market data
3. Use `crypto_alert` for price threshold alerts
4. Use `web_search` for financial news context
