from datetime import datetime
from typing import Any, Dict, List
import pandas as pd
import yfinance as yf
from app.tools.base import BaseTool, ToolParameter, ToolSchema

INDICES = {
    "S&P 500": "^GSPC",
    "Dow Jones": "^DJI",
    "NASDAQ 100": "^NDX",
    "Russell 2000": "^RUT",
    "VIX": "^VIX",
}

SECTOR_ETFS = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Energy": "XLE",
    "Consumer Disc.": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Comm. Services": "XLC",
}

COMMODITIES = {
    "Gold": "GC=F",
    "Silver": "SI=F",
    "Crude Oil": "CL=F",
    "Nat. Gas": "NG=F",
    "Copper": "HG=F",
}

CRYPTO = {
    "Bitcoin": "BTC-USD",
    "Ethereum": "ETH-USD",
}

BONDS = {
    "US 2Y Yield": "^IRX",
    "US 10Y Yield": "^TNX",
    "US 30Y Yield": "^TYX",
}


def _fetch_pct_change(symbol: str) -> Dict:
    try:
        t = yf.Ticker(symbol)
        fi = t.fast_info
        price = fi.last_price
        prev = fi.previous_close
        chg_pct = round(((price - prev) / prev) * 100, 2) if prev else 0
        return {"price": round(price, 4), "changePct": chg_pct}
    except Exception:
        return {"price": None, "changePct": None}


class FinanceOperationTool(BaseTool):
    """
    Unified finance operations tool with full enum style.
    Handles quotes, company overviews, financial statements, technical analysis,
    market reports, market overview, and news/recommendations.
    """

    VALID_STATEMENT_TYPES = ["income", "balance_sheet", "cashflow"]
    VALID_FREQUENCIES = ["annual", "quarterly"]
    VALID_PERIODS = ["1mo", "3mo", "6mo", "1y", "2y"]
    VALID_INTERVALS = ["1d", "1wk"]

    def get_name(self) -> str:
        return "finance_ops"

    def get_description(self) -> str:
        return (
            "Unified finance operations tool. Retrieve stock quotes, company overviews, "
            "financial statements, technical analysis, full market reports, news, or a macro "
            "market overview snapshot."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="The finance operation to perform.",
                    required=True,
                    enum=[
                        "quote",
                        "company_overview",
                        "financial_statements",
                        "technical_analysis",
                        "market_report",
                        "market_overview",
                        "news_and_recommendations",
                    ],
                ),
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="Stock ticker symbol (required for most ops).",
                    required=False,
                ),
                ToolParameter(
                    name="statement_type",
                    type="string",
                    description="For 'financial_statements': 'income', 'balance_sheet', or 'cashflow'.",
                    required=False,
                    enum=self.VALID_STATEMENT_TYPES,
                ),
                ToolParameter(
                    name="frequency",
                    type="string",
                    description="For 'financial_statements': 'annual' or 'quarterly'. Default: annual",
                    required=False,
                    enum=self.VALID_FREQUENCIES,
                ),
                ToolParameter(
                    name="period",
                    type="string",
                    description="For 'technical_analysis' and 'market_report' (e.g. '1mo', '3mo', '6mo', '1y', '2y').",
                    required=False,
                    enum=self.VALID_PERIODS,
                ),
                ToolParameter(
                    name="interval",
                    type="string",
                    description="For 'technical_analysis': '1d' or '1wk'.",
                    required=False,
                    enum=self.VALID_INTERVALS,
                ),
                ToolParameter(
                    name="max_news",
                    type="string",
                    description="For 'news_and_recommendations': Max news articles to return (1-10). Default: 8",
                    required=False,
                ),
            ],
        )

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg, "output": f"Error: {msg}"}

    def _success(self, llm_content: str, display: Any) -> Dict[str, Any]:
        return {"success": True, "output": llm_content, "display": display}

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation")
        if not op:
            return self._error("Missing required parameter: 'operation'")

        if op == "market_overview":
            return await self._get_market_overview(**kwargs)

        symbol = kwargs.get("symbol", "")
        if not symbol or not isinstance(symbol, str) or not symbol.strip():
            return self._error(f"Missing required parameter 'symbol' for operation '{op}'")
        kwargs["symbol"] = symbol.upper().strip()

        if op == "quote":
            return await self._get_stock_quote(**kwargs)
        elif op == "company_overview":
            return await self._get_company_overview(**kwargs)
        elif op == "financial_statements":
            return await self._get_financial_statements(**kwargs)
        elif op == "technical_analysis":
            return await self._get_technical_analysis(**kwargs)
        elif op == "market_report":
            return await self._get_market_report(**kwargs)
        elif op == "news_and_recommendations":
            return await self._get_news_and_recommendations(**kwargs)
        else:
            return self._error(f"Unknown operation: {op}")

    async def _get_stock_quote(self, **kwargs: Any) -> Dict[str, Any]:
        symbol: str = kwargs.get("symbol", "")

        # ── Validation ────────────────────────────────────────────────
        if not symbol or not isinstance(symbol, str) or not symbol.strip():
            return self._error("Missing required parameter: 'symbol'")

        symbol = symbol.upper().strip()

        # ── Execution ─────────────────────────────────────────────────
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            if not info or info.get("regularMarketPrice") is None:
                # Try fast_info fallback
                fast = ticker.fast_info
                price = fast.last_price
                prev_close = fast.previous_close
            else:
                price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                prev_close = info.get("previousClose", 0)

            change = round(price - prev_close, 4) if price and prev_close else 0
            change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

            display = {
                "symbol": symbol,
                "name": info.get("longName", symbol),
                "price": round(price, 4),
                "change": change,
                "changePercent": change_pct,
                "previousClose": round(prev_close, 4),
                "open": info.get("open", 0),
                "dayHigh": info.get("dayHigh", 0),
                "dayLow": info.get("dayLow", 0),
                "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh", 0),
                "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow", 0),
                "volume": info.get("volume", 0),
                "avgVolume10d": info.get("averageVolume10days", 0),
                "marketCap": info.get("marketCap", 0),
                "bid": info.get("bid", 0),
                "ask": info.get("ask", 0),
                "currency": info.get("currency", "USD"),
                "exchange": info.get("exchange", ""),
                "timestamp": datetime.now().isoformat(),
            }

            direction = "▲" if change >= 0 else "▼"
            llm_content = (
                f"{display['name']} ({symbol}) | "
                f"Price: {display['currency']} {price:.4f} "
                f"{direction} {abs(change):.4f} ({abs(change_pct):.2f}%) | "
                f"Open: {display['open']} | "
                f"Day Range: {display['dayLow']} – {display['dayHigh']} | "
                f"52W Range: {display['fiftyTwoWeekLow']} – {display['fiftyTwoWeekHigh']} | "
                f"Volume: {display['volume']:,} | "
                f"Market Cap: ${display['marketCap']:,} | "
                f"Bid/Ask: {display['bid']} / {display['ask']}"
            )

            return self._success(llm_content, display)

        except Exception as e:
            return self._error(f"Failed to fetch quote for '{symbol}': {str(e)}")

    async def _get_company_overview(self, **kwargs: Any) -> Dict[str, Any]:
        symbol: str = kwargs.get("symbol", "")

        # ── Validation ────────────────────────────────────────────────
        if not symbol or not isinstance(symbol, str) or not symbol.strip():
            return self._error("Missing required parameter: 'symbol'")

        symbol = symbol.upper().strip()

        # ── Execution ─────────────────────────────────────────────────
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            if not info or not info.get("longName"):
                return self._error(f"No data found for symbol '{symbol}'. Check the ticker.")

            def safe_pct(val):
                return round(val * 100, 2) if val else 0

            display = {
                # Identity
                "symbol": symbol,
                "name": info.get("longName", ""),
                "sector": info.get("sector", "N/A"),
                "industry": info.get("industry", "N/A"),
                "country": info.get("country", "N/A"),
                "employees": info.get("fullTimeEmployees", 0),
                "website": info.get("website", ""),
                "description": (info.get("longBusinessSummary", "")[:500] + "...")
                if info.get("longBusinessSummary")
                else "",
                # Valuation
                "marketCap": info.get("marketCap", 0),
                "enterpriseValue": info.get("enterpriseValue", 0),
                "trailingPE": round(info.get("trailingPE", 0) or 0, 2),
                "forwardPE": round(info.get("forwardPE", 0) or 0, 2),
                "pegRatio": round(info.get("pegRatio", 0) or 0, 2),
                "priceToBook": round(info.get("priceToBook", 0) or 0, 2),
                "priceToSales": round(info.get("priceToSalesTrailing12Months", 0) or 0, 2),
                "evToEbitda": round(info.get("enterpriseToEbitda", 0) or 0, 2),
                "evToRevenue": round(info.get("enterpriseToRevenue", 0) or 0, 2),
                # Per-share
                "trailingEPS": round(info.get("trailingEps", 0) or 0, 2),
                "forwardEPS": round(info.get("forwardEps", 0) or 0, 2),
                "bookValuePerShare": round(info.get("bookValue", 0) or 0, 2),
                "revenuePerShare": round(info.get("revenuePerShare", 0) or 0, 2),
                # Profitability
                "grossMargin": safe_pct(info.get("grossMargins")),
                "operatingMargin": safe_pct(info.get("operatingMargins")),
                "netProfitMargin": safe_pct(info.get("profitMargins")),
                "ebitdaMargin": safe_pct(info.get("ebitdaMargins")),
                "returnOnEquity": safe_pct(info.get("returnOnEquity")),
                "returnOnAssets": safe_pct(info.get("returnOnAssets")),
                # Growth
                "revenueGrowthYoY": safe_pct(info.get("revenueGrowth")),
                "earningsGrowthYoY": safe_pct(info.get("earningsGrowth")),
                "earningsQuarterlyGrowth": safe_pct(info.get("earningsQuarterlyGrowth")),
                # Balance sheet
                "totalCash": info.get("totalCash", 0),
                "totalDebt": info.get("totalDebt", 0),
                "debtToEquity": round(info.get("debtToEquity", 0) or 0, 2),
                "currentRatio": round(info.get("currentRatio", 0) or 0, 2),
                "quickRatio": round(info.get("quickRatio", 0) or 0, 2),
                "freeCashflow": info.get("freeCashflow", 0),
                "operatingCashflow": info.get("operatingCashflow", 0),
                # Dividends
                "dividendYield": safe_pct(info.get("dividendYield")),
                "dividendRate": info.get("dividendRate", 0),
                "payoutRatio": safe_pct(info.get("payoutRatio")),
                "fiveYearAvgDividendYield": info.get("fiveYearAvgDividendYield", 0),
                # Analyst targets
                "analystRecommendation": info.get("recommendationKey", "N/A").upper(),
                "numberOfAnalysts": info.get("numberOfAnalystOpinions", 0),
                "targetHighPrice": info.get("targetHighPrice", 0),
                "targetLowPrice": info.get("targetLowPrice", 0),
                "targetMeanPrice": info.get("targetMeanPrice", 0),
                "targetMedianPrice": info.get("targetMedianPrice", 0),
                # Risk
                "beta": round(info.get("beta", 0) or 0, 2),
                "shortRatio": round(info.get("shortRatio", 0) or 0, 2),
                "shortPercentOfFloat": safe_pct(info.get("shortPercentOfFloat")),
                # Price performance
                "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh", 0),
                "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow", 0),
                "fiftyDayAverage": round(info.get("fiftyDayAverage", 0) or 0, 2),
                "twoHundredDayAverage": round(info.get("twoHundredDayAverage", 0) or 0, 2),
            }

            llm_content = (
                f"=== Company Overview: {display['name']} ({symbol}) ===\n"
                f"Sector: {display['sector']} | Industry: {display['industry']} | Country: {display['country']}\n"
                f"Employees: {display['employees']:,} | Website: {display['website']}\n\n"
                f"--- Valuation ---\n"
                f"Market Cap: ${display['marketCap']:,} | EV: ${display['enterpriseValue']:,}\n"
                f"P/E (trailing): {display['trailingPE']} | P/E (forward): {display['forwardPE']} | PEG: {display['pegRatio']}\n"
                f"P/B: {display['priceToBook']} | P/S: {display['priceToSales']} | EV/EBITDA: {display['evToEbitda']}\n"
                f"EPS (trailing): ${display['trailingEPS']} | EPS (forward): ${display['forwardEPS']}\n\n"
                f"--- Profitability ---\n"
                f"Gross Margin: {display['grossMargin']}% | Operating Margin: {display['operatingMargin']}% | Net Margin: {display['netProfitMargin']}%\n"
                f"ROE: {display['returnOnEquity']}% | ROA: {display['returnOnAssets']}%\n"
                f"Revenue Growth YoY: {display['revenueGrowthYoY']}% | Earnings Growth YoY: {display['earningsGrowthYoY']}%\n\n"
                f"--- Balance Sheet ---\n"
                f"Cash: ${display['totalCash']:,} | Debt: ${display['totalDebt']:,} | D/E: {display['debtToEquity']}\n"
                f"Current Ratio: {display['currentRatio']} | Quick Ratio: {display['quickRatio']}\n"
                f"Free Cash Flow: ${display['freeCashflow']:,}\n\n"
                f"--- Dividends ---\n"
                f"Yield: {display['dividendYield']}% | Rate: ${display['dividendRate']} | Payout Ratio: {display['payoutRatio']}%\n\n"
                f"--- Analyst Targets ({display['numberOfAnalysts']} analysts) ---\n"
                f"Recommendation: {display['analystRecommendation']}\n"
                f"Price Target: Low ${display['targetLowPrice']} | Mean ${display['targetMeanPrice']} | High ${display['targetHighPrice']}\n\n"
                f"--- Risk ---\n"
                f"Beta: {display['beta']} | Short Ratio: {display['shortRatio']} | Short % Float: {display['shortPercentOfFloat']}%\n"
                f"52W Range: ${display['fiftyTwoWeekLow']} – ${display['fiftyTwoWeekHigh']}\n"
                f"50D MA: ${display['fiftyDayAverage']} | 200D MA: ${display['twoHundredDayAverage']}"
            )

            return self._success(llm_content, display)

        except Exception as e:
            return self._error(f"Failed to fetch overview for '{symbol}': {str(e)}")

    async def _get_financial_statements(self, **kwargs: Any) -> Dict[str, Any]:
        symbol: str = kwargs.get("symbol", "")
        stmt_type: str = kwargs.get("statement_type", "")
        frequency: str = kwargs.get("frequency", "annual")

        # ── Validation ────────────────────────────────────────────────
        if not symbol or not isinstance(symbol, str) or not symbol.strip():
            return self._error("Missing required parameter: 'symbol'")
        if stmt_type not in self.VALID_STATEMENT_TYPES:
            return self._error(
                f"Invalid statement_type '{stmt_type}'. "
                f"Allowed: {', '.join(self.VALID_STATEMENT_TYPES)}"
            )
        if frequency not in self.VALID_FREQUENCIES:
            return self._error(
                f"Invalid frequency '{frequency}'. Allowed: {', '.join(self.VALID_FREQUENCIES)}"
            )

        symbol = symbol.upper().strip()
        quarterly = frequency == "quarterly"

        # ── Execution ─────────────────────────────────────────────────
        try:
            ticker = yf.Ticker(symbol)

            if stmt_type == "income":
                df = ticker.quarterly_income_stmt if quarterly else ticker.income_stmt
                label = "Income Statement"
            elif stmt_type == "balance_sheet":
                df = ticker.quarterly_balance_sheet if quarterly else ticker.balance_sheet
                label = "Balance Sheet"
            else:
                df = ticker.quarterly_cash_flow if quarterly else ticker.cash_flow
                label = "Cash Flow Statement"

            if df is None or df.empty:
                return self._error(
                    f"No {label} data available for '{symbol}'. "
                    "The company may not report this statement publicly."
                )

            # ── Convert DataFrame to clean dict ───────────────────────
            periods = [str(c)[:10] for c in df.columns[:4]]
            records: Dict[str, Dict] = {}

            for col in df.columns[:4]:
                period_key = str(col)[:10]
                records[period_key] = {}
                for row_idx in df.index:
                    val = df.loc[row_idx, col]
                    try:
                        records[period_key][str(row_idx)] = float(val) if val is not None else None
                    except (ValueError, TypeError):
                        records[period_key][str(row_idx)] = None

            # ── Extract key highlights ────────────────────────────────
            latest = records.get(periods[0], {}) if periods else {}
            highlights: List[str] = []

            if stmt_type == "income":
                keys_of_interest = [
                    ("Total Revenue", "Revenue"),
                    ("Gross Profit", "Gross Profit"),
                    ("Operating Income", "Operating Income"),
                    ("EBITDA", "EBITDA"),
                    ("Net Income", "Net Income"),
                    ("Basic EPS", "Basic EPS"),
                    ("Diluted EPS", "Diluted EPS"),
                ]
            elif stmt_type == "balance_sheet":
                keys_of_interest = [
                    ("Total Assets", "Total Assets"),
                    ("Total Liabilities Net Minority Interest", "Total Liabilities"),
                    ("Stockholders Equity", "Stockholders Equity"),
                    ("Cash And Cash Equivalents", "Cash"),
                    ("Total Debt", "Total Debt"),
                    ("Working Capital", "Working Capital"),
                ]
            else:
                keys_of_interest = [
                    ("Operating Cash Flow", "Operating CF"),
                    ("Investing Cash Flow", "Investing CF"),
                    ("Financing Cash Flow", "Financing CF"),
                    ("Free Cash Flow", "Free Cash Flow"),
                    ("Capital Expenditure", "CapEx"),
                ]

            for raw_key, display_name in keys_of_interest:
                val = latest.get(raw_key)
                if val is not None:
                    if abs(val) >= 1e9:
                        highlights.append(f"{display_name}: ${val / 1e9:.2f}B")
                    elif abs(val) >= 1e6:
                        highlights.append(f"{display_name}: ${val / 1e6:.2f}M")
                    else:
                        highlights.append(f"{display_name}: ${val:,.2f}")

            display = {
                "symbol": symbol,
                "statementType": label,
                "frequency": frequency,
                "periods": periods,
                "highlights": highlights,
                "lineItems": len(df.index),
                "data": records,
            }

            llm_content = (
                f"=== {label}: {symbol} ({frequency}) ===\n"
                f"Periods: {', '.join(periods)}\n"
                f"Total Line Items: {len(df.index)}\n\n"
                f"--- Key Highlights (most recent period: {periods[0] if periods else 'N/A'}) ---\n"
                + ("\n".join(f"  • {h}" for h in highlights) or "  No highlights available")
                + f"\n\nFull data returned in returnDisplay.data "
                f"with {len(periods)} periods × {len(df.index)} line items."
            )

            return self._success(llm_content, display)

        except Exception as e:
            return self._error(f"Failed to fetch {stmt_type} for '{symbol}': {str(e)}")

    async def _get_technical_analysis(self, **kwargs: Any) -> Dict[str, Any]:
        symbol: str = kwargs.get("symbol", "")
        period: str = kwargs.get("period", "6mo")
        interval: str = kwargs.get("interval", "1d")

        # ── Validation ────────────────────────────────────────────────
        if not symbol or not isinstance(symbol, str) or not symbol.strip():
            return self._error("Missing required parameter: 'symbol'")
        if period not in self.VALID_PERIODS:
            return self._error(
                f"Invalid period '{period}'. Allowed: {', '.join(self.VALID_PERIODS)}"
            )
        if interval not in self.VALID_INTERVALS:
            return self._error(
                f"Invalid interval '{interval}'. Allowed: {', '.join(self.VALID_INTERVALS)}"
            )

        symbol = symbol.upper().strip()

        # ── Fetch data ────────────────────────────────────────────────
        try:
            df = yf.Ticker(symbol).history(period=period, interval=interval)

            if df is None or df.empty:
                return self._error(f"No price history returned for '{symbol}'")
            if len(df) < 26:
                return self._error(
                    f"Not enough data for '{symbol}' — need at least 26 bars, got {len(df)}"
                )

            close = df["Close"]
            high = df["High"]
            low = df["Low"]
            volume = df["Volume"]

            # ── RSI (14) ──────────────────────────────────────────────
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss
            rsi = round(float(100 - (100 / (1 + rs.iloc[-1]))), 2)

            # ── MACD (12, 26, 9) ──────────────────────────────────────
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            histogram = macd_line - signal_line
            macd_val = round(float(macd_line.iloc[-1]), 6)
            signal_val = round(float(signal_line.iloc[-1]), 6)
            hist_val = round(float(histogram.iloc[-1]), 6)
            hist_prev = round(float(histogram.iloc[-2]), 6)

            # ── Bollinger Bands (20, 2) ───────────────────────────────
            bb_mid = close.rolling(20).mean()
            bb_std = close.rolling(20).std()
            bb_upper = float((bb_mid + 2 * bb_std).iloc[-1])
            bb_lower = float((bb_mid - 2 * bb_std).iloc[-1])
            bb_mid_v = float(bb_mid.iloc[-1])
            bb_pct = (
                round((float(close.iloc[-1]) - bb_lower) / (bb_upper - bb_lower) * 100, 2)
                if (bb_upper - bb_lower) != 0
                else 50
            )

            # ── Moving Averages ───────────────────────────────────────
            sma20 = round(float(close.rolling(20).mean().iloc[-1]), 4)
            sma50 = round(float(close.rolling(50).mean().iloc[-1]), 4) if len(close) >= 50 else None
            sma200 = (
                round(float(close.rolling(200).mean().iloc[-1]), 4) if len(close) >= 200 else None
            )
            ema20 = round(float(close.ewm(span=20).mean().iloc[-1]), 4)
            ema50 = round(float(close.ewm(span=50).mean().iloc[-1]), 4)

            # ── ATR (14) ──────────────────────────────────────────────
            tr = pd.concat(
                [
                    high - low,
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr = round(float(tr.rolling(14).mean().iloc[-1]), 4)

            # ── Stochastic Oscillator %K / %D (14, 3) ─────────────────
            low14 = low.rolling(14).min()
            high14 = high.rolling(14).max()
            stoch_k = round(float(((close - low14) / (high14 - low14) * 100).iloc[-1]), 2)
            stoch_d = round(
                float(((close - low14) / (high14 - low14) * 100).rolling(3).mean().iloc[-1]),
                2,
            )

            # ── Volume trend ──────────────────────────────────────────
            avg_vol = float(volume.rolling(20).mean().iloc[-1])
            last_vol = float(volume.iloc[-1])
            vol_ratio = round(last_vol / avg_vol, 2) if avg_vol else 0

            # ── Support / Resistance (last 60 bars) ───────────────────
            recent = df.tail(60)
            support = round(float(recent["Low"].min()), 4)
            resistance = round(float(recent["High"].max()), 4)

            price = round(float(close.iloc[-1]), 4)

            # ── Signal scoring ────────────────────────────────────────
            bullish: List[str] = []
            bearish: List[str] = []

            # RSI
            if rsi < 30:
                bullish.append(f"RSI oversold at {rsi}")
            elif rsi > 70:
                bearish.append(f"RSI overbought at {rsi}")
            elif rsi > 50:
                bullish.append(f"RSI above midline ({rsi})")
            else:
                bearish.append(f"RSI below midline ({rsi})")

            # MACD
            if macd_val > signal_val:
                bullish.append("MACD above signal line")
            else:
                bearish.append("MACD below signal line")
            if hist_val > 0 and hist_val > hist_prev:
                bullish.append("MACD histogram expanding bullish")
            elif hist_val < 0 and hist_val < hist_prev:
                bearish.append("MACD histogram expanding bearish")

            # Moving averages
            if price > sma20:
                bullish.append(f"Price above SMA20 ({sma20})")
            else:
                bearish.append(f"Price below SMA20 ({sma20})")
            if sma50:
                if price > sma50:
                    bullish.append(f"Price above SMA50 ({sma50})")
                else:
                    bearish.append(f"Price below SMA50 ({sma50})")
            if sma200:
                if price > sma200:
                    bullish.append(f"Price above SMA200 ({sma200}) — long-term uptrend")
                else:
                    bearish.append(f"Price below SMA200 ({sma200}) — long-term downtrend")
            if sma50 and sma200:
                if sma50 > sma200:
                    bullish.append("Golden cross: SMA50 > SMA200")
                else:
                    bearish.append("Death cross: SMA50 < SMA200")

            # Bollinger Bands
            if price < bb_lower:
                bullish.append("Price below lower Bollinger Band (oversold)")
            elif price > bb_upper:
                bearish.append("Price above upper Bollinger Band (overbought)")

            # Stochastic
            if stoch_k < 20:
                bullish.append(f"Stochastic oversold K={stoch_k}")
            elif stoch_k > 80:
                bearish.append(f"Stochastic overbought K={stoch_k}")
            if stoch_k > stoch_d:
                bullish.append("Stochastic %K crossed above %D")
            else:
                bearish.append("Stochastic %K crossed below %D")

            # Volume
            if vol_ratio > 1.5:
                bullish.append(f"High volume day ({vol_ratio}x avg) — conviction move")
            elif vol_ratio < 0.5:
                bearish.append(f"Low volume ({vol_ratio}x avg) — weak move")

            # Final signal
            score = len(bullish) - len(bearish)
            if score >= 5:
                signal = "STRONG BUY"
            elif score >= 2:
                signal = "BUY"
            elif score == 0:
                signal = "HOLD"
            elif score >= -3:
                signal = "SELL"
            else:
                signal = "STRONG SELL"

            display = {
                "symbol": symbol,
                "currentPrice": price,
                "signal": signal,
                "score": score,
                "bullishSignals": bullish,
                "bearishSignals": bearish,
                "indicators": {
                    "rsi14": rsi,
                    "macd": macd_val,
                    "macdSignal": signal_val,
                    "macdHistogram": hist_val,
                    "sma20": sma20,
                    "sma50": sma50,
                    "sma200": sma200,
                    "ema20": ema20,
                    "ema50": ema50,
                    "bollingerUpper": round(bb_upper, 4),
                    "bollingerMid": round(bb_mid_v, 4),
                    "bollingerLower": round(bb_lower, 4),
                    "bollingerPct": bb_pct,
                    "atr14": atr,
                    "stochasticK": stoch_k,
                    "stochasticD": stoch_d,
                    "volumeRatio": vol_ratio,
                },
                "levels": {
                    "support": support,
                    "resistance": resistance,
                },
                "period": period,
                "interval": interval,
                "barsAnalyzed": len(df),
            }

            llm_content = (
                f"=== Technical Analysis: {symbol} ({period}, {interval}) ===\n"
                f"Current Price: ${price} | Signal: {signal} (score: {score:+d})\n\n"
                f"--- Indicators ---\n"
                f"RSI(14): {rsi} {'[OVERSOLD]' if rsi < 30 else '[OVERBOUGHT]' if rsi > 70 else ''}\n"
                f"MACD: {macd_val} | Signal: {signal_val} | Histogram: {hist_val}\n"
                f"Bollinger Bands: Lower={round(bb_lower, 2)} | Mid={round(bb_mid_v, 2)} | Upper={round(bb_upper, 2)} | %B={bb_pct}%\n"
                f"SMA20: {sma20} | SMA50: {sma50} | SMA200: {sma200}\n"
                f"EMA20: {ema20} | EMA50: {ema50}\n"
                f"ATR(14): {atr} | Stochastic K: {stoch_k} / D: {stoch_d}\n"
                f"Volume Ratio vs 20D Avg: {vol_ratio}x\n\n"
                f"--- Key Levels ---\n"
                f"Support: ${support} | Resistance: ${resistance}\n\n"
                f"--- Bullish Signals ({len(bullish)}) ---\n"
                + ("\n".join(f"  ✅ {s}" for s in bullish) or "  None")
                + "\n\n"
                f"--- Bearish Signals ({len(bearish)}) ---\n"
                + ("\n".join(f"  ❌ {s}" for s in bearish) or "  None")
            )

            return self._success(llm_content, display)

        except Exception as e:
            return self._error(f"Technical analysis failed for '{symbol}': {str(e)}")

    async def _get_market_report(self, **kwargs: Any) -> Dict[str, Any]:
        symbol: str = kwargs.get("symbol", "")
        period: str = kwargs.get("period", "6mo")

        # ── Validation ────────────────────────────────────────────────
        if not symbol or not isinstance(symbol, str) or not symbol.strip():
            return self._error("Missing required parameter: 'symbol'")
        if period not in ["3mo", "6mo", "1y"]:
            return self._error("Invalid period. Use: 3mo, 6mo, 1y")

        symbol = symbol.upper().strip()

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            if not info or not info.get("longName"):
                return self._error(f"No data found for '{symbol}'. Check the ticker symbol.")

            # ════════════════════════════════════════════════════════
            # 1. REAL-TIME QUOTE
            # ════════════════════════════════════════════════════════
            price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            prev_close = info.get("previousClose", 0)
            change = round(price - prev_close, 4) if price and prev_close else 0
            change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

            quote = {
                "price": round(price, 4),
                "change": change,
                "changePercent": change_pct,
                "previousClose": prev_close,
                "dayHigh": info.get("dayHigh", 0),
                "dayLow": info.get("dayLow", 0),
                "volume": info.get("volume", 0),
                "marketCap": info.get("marketCap", 0),
                "currency": info.get("currency", "USD"),
            }

            # ════════════════════════════════════════════════════════
            # 2. COMPANY OVERVIEW
            # ════════════════════════════════════════════════════════
            def pct(v):
                return round((v or 0) * 100, 2)

            company = {
                "name": info.get("longName", symbol),
                "sector": info.get("sector", "N/A"),
                "industry": info.get("industry", "N/A"),
                "description": (info.get("longBusinessSummary", "")[:400] + "...")
                if info.get("longBusinessSummary")
                else "",
                "trailingPE": round(info.get("trailingPE", 0) or 0, 2),
                "forwardPE": round(info.get("forwardPE", 0) or 0, 2),
                "pegRatio": round(info.get("pegRatio", 0) or 0, 2),
                "priceToBook": round(info.get("priceToBook", 0) or 0, 2),
                "evToEbitda": round(info.get("enterpriseToEbitda", 0) or 0, 2),
                "eps": round(info.get("trailingEps", 0) or 0, 2),
                "roe": pct(info.get("returnOnEquity")),
                "roa": pct(info.get("returnOnAssets")),
                "netMargin": pct(info.get("profitMargins")),
                "grossMargin": pct(info.get("grossMargins")),
                "revenueGrowth": pct(info.get("revenueGrowth")),
                "earningsGrowth": pct(info.get("earningsGrowth")),
                "debtToEquity": round(info.get("debtToEquity", 0) or 0, 2),
                "currentRatio": round(info.get("currentRatio", 0) or 0, 2),
                "dividendYield": pct(info.get("dividendYield")),
                "beta": round(info.get("beta", 0) or 0, 2),
                "shortPercent": pct(info.get("shortPercentOfFloat")),
                "analystRating": info.get("recommendationKey", "N/A").upper(),
                "targetMeanPrice": info.get("targetMeanPrice", 0),
                "targetHighPrice": info.get("targetHighPrice", 0),
                "targetLowPrice": info.get("targetLowPrice", 0),
                "numberOfAnalysts": info.get("numberOfAnalystOpinions", 0),
                "52wHigh": info.get("fiftyTwoWeekHigh", 0),
                "52wLow": info.get("fiftyTwoWeekLow", 0),
                "50dMA": round(info.get("fiftyDayAverage", 0) or 0, 2),
                "200dMA": round(info.get("twoHundredDayAverage", 0) or 0, 2),
            }

            # ════════════════════════════════════════════════════════
            # 3. TECHNICAL ANALYSIS
            # ════════════════════════════════════════════════════════
            df = ticker.history(period=period, interval="1d")
            close = df["Close"]
            high = df["High"]
            low = df["Low"]
            volume = df["Volume"]

            # RSI
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rsi = round(float(100 - (100 / (1 + (gain / loss).iloc[-1]))), 2)

            # MACD
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_l = ema12 - ema26
            sig_l = macd_l.ewm(span=9, adjust=False).mean()
            hist = macd_l - sig_l

            # Bollinger
            bb_mid = close.rolling(20).mean()
            bb_std = close.rolling(20).std()
            bb_upper = float((bb_mid + 2 * bb_std).iloc[-1])
            bb_lower = float((bb_mid - 2 * bb_std).iloc[-1])

            # MAs
            sma20 = round(float(close.rolling(20).mean().iloc[-1]), 2)
            sma50 = round(float(close.rolling(50).mean().iloc[-1]), 2) if len(close) >= 50 else None
            sma200 = (
                round(float(close.rolling(200).mean().iloc[-1]), 2) if len(close) >= 200 else None
            )

            # ATR
            tr = pd.concat(
                [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
                axis=1,
            ).max(axis=1)
            atr = round(float(tr.rolling(14).mean().iloc[-1]), 2)

            # Support / Resistance
            support = round(float(df.tail(60)["Low"].min()), 2)
            resistance = round(float(df.tail(60)["High"].max()), 2)

            # Volume
            vol_ratio = round(float(volume.iloc[-1]) / float(volume.rolling(20).mean().iloc[-1]), 2)

            # Signal scoring
            bullish, bearish = [], []
            if rsi < 30:
                bullish.append(f"RSI oversold ({rsi})")
            elif rsi > 70:
                bearish.append(f"RSI overbought ({rsi})")
            if float(macd_l.iloc[-1]) > float(sig_l.iloc[-1]):
                bullish.append("MACD bullish crossover")
            else:
                bearish.append("MACD bearish crossover")
            if price > sma20:
                bullish.append("Above SMA20")
            else:
                bearish.append("Below SMA20")
            if sma50 and price > sma50:
                bullish.append("Above SMA50")
            elif sma50:
                bearish.append("Below SMA50")
            if sma200 and price > sma200:
                bullish.append("Above SMA200")
            elif sma200:
                bearish.append("Below SMA200")
            if sma50 and sma200 and sma50 > sma200:
                bullish.append("Golden cross (SMA50>SMA200)")
            elif sma50 and sma200:
                bearish.append("Death cross (SMA50<SMA200)")
            if price < bb_lower:
                bullish.append("Below lower Bollinger Band")
            elif price > bb_upper:
                bearish.append("Above upper Bollinger Band")

            score = len(bullish) - len(bearish)
            if score >= 4:
                signal = "STRONG BUY"
            elif score >= 2:
                signal = "BUY"
            elif score == 0:
                signal = "HOLD"
            elif score >= -2:
                signal = "SELL"
            else:
                signal = "STRONG SELL"

            technical = {
                "signal": signal,
                "score": score,
                "rsi": rsi,
                "macd": round(float(macd_l.iloc[-1]), 6),
                "macdSignal": round(float(sig_l.iloc[-1]), 6),
                "macdHist": round(float(hist.iloc[-1]), 6),
                "bbUpper": round(bb_upper, 2),
                "bbLower": round(bb_lower, 2),
                "sma20": sma20,
                "sma50": sma50,
                "sma200": sma200,
                "atr": atr,
                "support": support,
                "resistance": resistance,
                "volumeRatio": vol_ratio,
                "bullishSignals": bullish,
                "bearishSignals": bearish,
            }

            # ════════════════════════════════════════════════════════
            # 4. INCOME STATEMENT HIGHLIGHTS
            # ════════════════════════════════════════════════════════
            income_highlights = []
            try:
                inc = ticker.income_stmt
                if inc is not None and not inc.empty:
                    latest_col = inc.columns[0]

                    def get_val(key):
                        try:
                            return float(inc.loc[key, latest_col])
                        except Exception:
                            return None

                    for key, label in [
                        ("Total Revenue", "Revenue"),
                        ("Gross Profit", "Gross Profit"),
                        ("Operating Income", "Operating Income"),
                        ("Net Income", "Net Income"),
                        ("EBITDA", "EBITDA"),
                    ]:
                        v = get_val(key)
                        if v is not None:
                            income_highlights.append(
                                f"{label}: ${v / 1e9:.2f}B"
                                if abs(v) >= 1e9
                                else f"{label}: ${v / 1e6:.2f}M"
                            )
            except Exception:
                pass

            # ════════════════════════════════════════════════════════
            # 5. NEWS HEADLINES
            # ════════════════════════════════════════════════════════
            news_headlines = []
            try:
                raw_news = ticker.news or []
                for item in raw_news[:5]:
                    content = item.get("content", {})
                    title = content.get("title", item.get("title", ""))
                    pub = content.get("provider", {}).get("displayName", "")
                    if title:
                        news_headlines.append(f"[{pub}] {title}")
            except Exception:
                pass

            # ════════════════════════════════════════════════════════
            # 6. ASSEMBLE FULL REPORT
            # ════════════════════════════════════════════════════════
            upside = (
                round(((company["targetMeanPrice"] - price) / price * 100), 1)
                if price and company["targetMeanPrice"]
                else 0
            )

            display = {
                "symbol": symbol,
                "reportDate": datetime.now().isoformat(),
                "quote": quote,
                "company": company,
                "technical": technical,
                "incomeHighlights": income_highlights,
                "newsHeadlines": news_headlines,
            }

            arrow = "▲" if change >= 0 else "▼"
            llm_content = (
                f"╔══════════════════════════════════════════════════════════╗\n"
                f"  MARKET ANALYSIS REPORT — {company['name']} ({symbol})\n"
                f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"╚══════════════════════════════════════════════════════════╝\n\n"
                f"━━━ 📊 REAL-TIME QUOTE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  Price:    {quote['currency']} {price:.4f}  {arrow} {abs(change):.4f} ({abs(change_pct):.2f}%)\n"
                f"  Day Range:{quote['dayLow']} – {quote['dayHigh']}\n"
                f"  Volume:   {quote['volume']:,}\n"
                f"  Mkt Cap:  ${quote['marketCap']:,}\n\n"
                f"━━━ 🏢 COMPANY PROFILE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  Sector: {company['sector']} | Industry: {company['industry']}\n"
                f"  {company['description']}\n\n"
                f"━━━ 💰 VALUATION & FUNDAMENTALS ━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  P/E (trail/fwd): {company['trailingPE']} / {company['forwardPE']}  |  PEG: {company['pegRatio']}\n"
                f"  P/B: {company['priceToBook']}  |  EV/EBITDA: {company['evToEbitda']}  |  EPS: ${company['eps']}\n"
                f"  Gross Margin: {company['grossMargin']}%  |  Net Margin: {company['netMargin']}%\n"
                f"  ROE: {company['roe']}%  |  ROA: {company['roa']}%\n"
                f"  Rev Growth: {company['revenueGrowth']}%  |  Earnings Growth: {company['earningsGrowth']}%\n"
                f"  D/E: {company['debtToEquity']}  |  Current Ratio: {company['currentRatio']}\n"
                f"  Dividend Yield: {company['dividendYield']}%  |  Beta: {company['beta']}\n\n"
                f"━━━ 📋 INCOME HIGHLIGHTS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                + ("\n".join(f"  • {h}" for h in income_highlights) or "  Not available")
                + "\n\n"
                f"━━━ 📈 TECHNICAL ANALYSIS ({period}) ━━━━━━━━━━━━━━━━━━━━\n"
                f"  Signal: {signal} (score: {score:+d})\n"
                f"  RSI(14): {rsi}  |  MACD: {technical['macd']}  |  ATR: {atr}\n"
                f"  SMA20: {sma20}  |  SMA50: {sma50}  |  SMA200: {sma200}\n"
                f"  Bollinger: {round(bb_lower, 2)} – {round(bb_upper, 2)}\n"
                f"  Support: ${support}  |  Resistance: ${resistance}\n"
                f"  Volume Ratio: {vol_ratio}x\n"
                f"  ✅ Bullish: {', '.join(bullish) or 'None'}\n"
                f"  ❌ Bearish: {', '.join(bearish) or 'None'}\n\n"
                f"━━━ 🎯 ANALYST CONSENSUS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  Rating: {company['analystRating']}  ({company['numberOfAnalysts']} analysts)\n"
                f"  Target: Low ${company['targetLowPrice']} | Mean ${company['targetMeanPrice']} | High ${company['targetHighPrice']}\n"
                f"  Implied Upside from current price: {upside:+.1f}%\n\n"
                f"━━━ 📰 RECENT NEWS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                + ("\n".join(f"  • {h}" for h in news_headlines) or "  No recent news")
                + "\n\n"
                f"━━━ ⚠️  RISK METRICS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  Beta: {company['beta']} (market sensitivity)\n"
                f"  Short Interest: {company['shortPercent']}% of float\n"
                f"  52W Range: ${company['52wLow']} – ${company['52wHigh']}\n"
                f"  50D MA: ${company['50dMA']}  |  200D MA: ${company['200dMA']}"
            )

            return self._success(llm_content, display)

        except Exception as e:
            return self._error(f"Failed to generate report for '{symbol}': {str(e)}")

    async def _get_market_overview(self, **kwargs: Any) -> Dict[str, Any]:
        try:
            # ── Indices ───────────────────────────────────────────────
            indices_data = {}
            for name, sym in INDICES.items():
                indices_data[name] = {**_fetch_pct_change(sym), "symbol": sym}

            # ── Sectors ───────────────────────────────────────────────
            sectors_data = {}
            for name, sym in SECTOR_ETFS.items():
                sectors_data[name] = {**_fetch_pct_change(sym), "symbol": sym}

            # ── Commodities ───────────────────────────────────────────
            commodities_data = {}
            for name, sym in COMMODITIES.items():
                commodities_data[name] = {**_fetch_pct_change(sym), "symbol": sym}

            # ── Crypto ────────────────────────────────────────────────
            crypto_data = {}
            for name, sym in CRYPTO.items():
                crypto_data[name] = {**_fetch_pct_change(sym), "symbol": sym}

            # ── Bonds ─────────────────────────────────────────────────
            bonds_data = {}
            for name, sym in BONDS.items():
                bonds_data[name] = {**_fetch_pct_change(sym), "symbol": sym}

            # ── Breadth / Sentiment ───────────────────────────────────
            vix_price = indices_data.get("VIX", {}).get("price", 20) or 20
            if vix_price < 15:
                sentiment = "EXTREME GREED"
            elif vix_price < 20:
                sentiment = "GREED"
            elif vix_price < 25:
                sentiment = "NEUTRAL"
            elif vix_price < 30:
                sentiment = "FEAR"
            else:
                sentiment = "EXTREME FEAR"

            sector_changes = [
                (k, v["changePct"]) for k, v in sectors_data.items() if v["changePct"] is not None
            ]
            sectors_up = [s for s, c in sector_changes if c > 0]
            sectors_down = [s for s, c in sector_changes if c < 0]
            best_sector = max(sector_changes, key=lambda x: x[1]) if sector_changes else ("N/A", 0)
            worst_sector = min(sector_changes, key=lambda x: x[1]) if sector_changes else ("N/A", 0)

            ten_y = bonds_data.get("US 10Y Yield", {}).get("price", 0) or 0
            two_y = bonds_data.get("US 2Y Yield", {}).get("price", 0) or 0
            yield_curve = "INVERTED (recession risk)" if two_y > ten_y else "NORMAL"

            display = {
                "timestamp": datetime.now().isoformat(),
                "indices": indices_data,
                "sectors": sectors_data,
                "commodities": commodities_data,
                "crypto": crypto_data,
                "bonds": bonds_data,
                "sentiment": {
                    "vix": vix_price,
                    "reading": sentiment,
                    "sectorsUp": len(sectors_up),
                    "sectorsDown": len(sectors_down),
                    "bestSector": best_sector[0],
                    "bestSectorChangePct": best_sector[1],
                    "worstSector": worst_sector[0],
                    "worstSectorChangePct": worst_sector[1],
                    "yieldCurve": yield_curve,
                    "tenYearYield": ten_y,
                    "twoYearYield": two_y,
                },
            }

            # ── Format llmContent ─────────────────────────────────────
            def fmt(data: dict) -> str:
                lines = []
                for name, vals in data.items():
                    p = vals.get("price")
                    c = vals.get("changePct")
                    arrow = "▲" if (c or 0) >= 0 else "▼"
                    lines.append(f"  {name}: {p} {arrow} {c}%")
                return "\n".join(lines)

            llm_content = (
                f"=== Market Overview — {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n\n"
                f"--- Major Indices ---\n{fmt(indices_data)}\n\n"
                f"--- Sector Performance (ETFs) ---\n{fmt(sectors_data)}\n"
                f"  Best:  {best_sector[0]} ({best_sector[1]:+.2f}%)\n"
                f"  Worst: {worst_sector[0]} ({worst_sector[1]:+.2f}%)\n"
                f"  Sectors Up: {len(sectors_up)} | Down: {len(sectors_down)}\n\n"
                f"--- Commodities ---\n{fmt(commodities_data)}\n\n"
                f"--- Crypto ---\n{fmt(crypto_data)}\n\n"
                f"--- Bond Yields ---\n{fmt(bonds_data)}\n"
                f"  Yield Curve: {yield_curve}\n\n"
                f"--- Market Sentiment ---\n"
                f"  VIX: {vix_price} → {sentiment}\n"
                f"  2Y Yield: {two_y}% | 10Y Yield: {ten_y}%"
            )

            return self._success(llm_content, display)

        except Exception as e:
            return self._error(f"Market overview failed: {str(e)}")

    async def _get_news_and_recommendations(self, **kwargs: Any) -> Dict[str, Any]:
        symbol: str = kwargs.get("symbol", "")
        max_news_raw = kwargs.get("max_news", "8")

        # ── Validation ────────────────────────────────────────────────
        if not symbol or not isinstance(symbol, str) or not symbol.strip():
            return self._error("Missing required parameter: 'symbol'")

        try:
            max_news = int(str(max_news_raw))
            if not (1 <= max_news <= 10):
                return self._error("'max_news' must be between 1 and 10")
        except (ValueError, TypeError):
            return self._error("'max_news' must be an integer between 1 and 10")

        symbol = symbol.upper().strip()

        # ── Execution ─────────────────────────────────────────────────
        try:
            ticker = yf.Ticker(symbol)

            # ── News ──────────────────────────────────────────────────
            news_items: List[Dict] = []
            try:
                raw_news = ticker.news or []
                for item in raw_news[:max_news]:
                    content = item.get("content", {})
                    news_items.append(
                        {
                            "title": content.get("title", item.get("title", "")),
                            "publisher": content.get("provider", {}).get("displayName", ""),
                            "url": content.get("canonicalUrl", {}).get("url", ""),
                            "publishedAt": content.get("pubDate", ""),
                            "summary": content.get("summary", "")[:200]
                            if content.get("summary")
                            else "",
                        }
                    )
            except Exception:
                pass

            # ── Analyst Recommendations ───────────────────────────────
            recs: List[Dict] = []
            try:
                rec_df = ticker.recommendations
                if rec_df is not None and not rec_df.empty:
                    for idx, row in rec_df.head(4).iterrows():
                        recs.append(
                            {
                                "period": str(idx)[:10],
                                "strongBuy": int(row.get("strongBuy", 0)),
                                "buy": int(row.get("buy", 0)),
                                "hold": int(row.get("hold", 0)),
                                "sell": int(row.get("sell", 0)),
                                "strongSell": int(row.get("strongSell", 0)),
                            }
                        )
            except Exception:
                pass

            # ── Upgrades / Downgrades ─────────────────────────────────
            upgrades: List[Dict] = []
            try:
                upg_df = ticker.upgrades_downgrades
                if upg_df is not None and not upg_df.empty:
                    for idx, row in upg_df.head(10).iterrows():
                        action = row.get("Action", "")
                        upgrades.append(
                            {
                                "date": str(idx)[:10],
                                "firm": row.get("Firm", ""),
                                "fromGrade": row.get("FromGrade", ""),
                                "toGrade": row.get("ToGrade", ""),
                                "action": action,
                            }
                        )
            except Exception:
                pass

            # ── Aggregate recommendation totals ───────────────────────
            total_strong_buy = sum(r["strongBuy"] for r in recs)
            total_buy = sum(r["buy"] for r in recs)
            total_hold = sum(r["hold"] for r in recs)
            total_sell = sum(r["sell"] for r in recs)
            total_strong_sell = sum(r["strongSell"] for r in recs)
            total_analysts = (
                total_strong_buy + total_buy + total_hold + total_sell + total_strong_sell
            )

            bullish_count = total_strong_buy + total_buy
            bearish_count = total_sell + total_strong_sell
            if total_analysts > 0:
                bull_pct = round(bullish_count / total_analysts * 100, 1)
            else:
                bull_pct = 0

            display = {
                "symbol": symbol,
                "newsCount": len(news_items),
                "news": news_items,
                "recommendations": recs,
                "upgradesDowngrades": upgrades,
                "aggregateSentiment": {
                    "totalAnalysts": total_analysts,
                    "strongBuy": total_strong_buy,
                    "buy": total_buy,
                    "hold": total_hold,
                    "sell": total_sell,
                    "strongSell": total_strong_sell,
                    "bullishPercent": bull_pct,
                },
                "timestamp": datetime.now().isoformat(),
            }

            # Recent upgrades summary
            recent_upg_lines = []
            for u in upgrades[:5]:
                direction = (
                    "⬆ UPGRADE"
                    if u["action"].lower() == "up"
                    else "⬇ DOWNGRADE"
                    if u["action"].lower() == "down"
                    else "→ REITERATE"
                )
                recent_upg_lines.append(
                    f"  {u['date']} | {u['firm']}: {u['fromGrade']} → {u['toGrade']} [{direction}]"
                )

            news_lines = [f"  [{n['publisher']}] {n['title']}" for n in news_items[:5]]
            latest_rec = recs[0] if recs else {}

            llm_content = (
                f"=== News & Analyst Sentiment: {symbol} ===\n\n"
                f"--- Latest News ({len(news_items)} articles) ---\n"
                + ("\n".join(news_lines) or "  No news found")
                + "\n\n"
                f"--- Most Recent Analyst Recommendations ({latest_rec.get('period', 'N/A')}) ---\n"
                f"  Strong Buy: {latest_rec.get('strongBuy', 0)} | "
                f"Buy: {latest_rec.get('buy', 0)} | "
                f"Hold: {latest_rec.get('hold', 0)} | "
                f"Sell: {latest_rec.get('sell', 0)} | "
                f"Strong Sell: {latest_rec.get('strongSell', 0)}\n\n"
                f"--- Aggregate (last {len(recs)} periods, {total_analysts} total votes) ---\n"
                f"  Bullish: {bullish_count} ({bull_pct}%) | "
                f"Hold: {total_hold} | "
                f"Bearish: {bearish_count}\n\n"
                f"--- Recent Upgrades / Downgrades ---\n"
                + ("\n".join(recent_upg_lines) or "  No recent changes")
            )

            return self._success(llm_content, display)

        except Exception as e:
            return self._error(f"Failed to fetch news/recommendations for '{symbol}': {str(e)}")
