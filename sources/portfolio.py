"""
sources/portfolio.py

Fetches market data for AEGIS's daily brief using yfinance.
Free, no API key required.
"""

from pathlib import Path
import yfinance as yf


TICKERS_FILE = Path(__file__).parent.parent / "config" / "tickers.txt"


def load_tickers() -> list[str]:
    """Read tickers from config/tickers.txt.
    One ticker per line. Lines starting with # are ignored."""
    if not TICKERS_FILE.exists():
        return []

    tickers = []
    for line in TICKERS_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tickers.append(line.upper())
    return tickers


def get_quote(ticker: str) -> dict:
    """Get current price, previous close, and % change for one ticker."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.fast_info

        current = info.last_price
        prev_close = info.previous_close

        if current is None or prev_close is None:
            return {"ticker": ticker, "error": "no data"}

        change = current - prev_close
        pct_change = (change / prev_close) * 100

        return {
            "ticker": ticker,
            "price": round(current, 2),
            "prev_close": round(prev_close, 2),
            "change": round(change, 2),
            "pct_change": round(pct_change, 2),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_top_headline(ticker: str) -> str | None:
    """Fetch the most recent news headline for a ticker.
    Returns None if nothing's available (common for crypto and small tickers)."""
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        if not news:
            return None

        # yfinance returns news with slightly different shapes between versions
        first = news[0]
        if "title" in first:
            return first["title"]
        if "content" in first and isinstance(first["content"], dict):
            return first["content"].get("title")
        return None
    except Exception:
        return None


def format_quote(q: dict) -> str:
    """Turn a quote dict into a readable line."""
    if "error" in q:
        return f"{q['ticker']}: data unavailable"
    direction = "up" if q["change"] >= 0 else "down"
    return (
        f"{q['ticker']}: ${q['price']} "
        f"({direction} {abs(q['pct_change'])}% from ${q['prev_close']})"
    )


def get_market_indexes() -> str:
    """Snapshot of broader market: S&P 500, Nasdaq, Dow."""
    indexes = {
        "SPY": "S&P 500",
        "QQQ": "Nasdaq 100",
        "DIA": "Dow Jones",
    }
    lines = ["MARKET INDEXES:"]
    for ticker, name in indexes.items():
        q = get_quote(ticker)
        if "error" in q:
            lines.append(f"  {name}: data unavailable")
        else:
            direction = "up" if q["change"] >= 0 else "down"
            lines.append(f"  {name} ({ticker}): {direction} {abs(q['pct_change'])}%")
    return "\n".join(lines)


def get_portfolio_summary() -> str:
    """Build the full portfolio section: holdings + headlines + indexes."""
    tickers = load_tickers()

    if not tickers:
        return "PORTFOLIO: No tickers configured. Add some to config/tickers.txt"

    # Separate stocks from crypto for cleaner formatting
    stocks = [t for t in tickers if not t.endswith("-USD")]
    crypto = [t for t in tickers if t.endswith("-USD")]

    sections = []

    if stocks:
        sections.append("YOUR STOCK POSITIONS:")
        for ticker in stocks:
            q = get_quote(ticker)
            sections.append(f"  {format_quote(q)}")
            headline = get_top_headline(ticker)
            if headline:
                sections.append(f"     news: {headline}")

    if crypto:
        sections.append("\nYOUR CRYPTO POSITIONS:")
        for ticker in crypto:
            q = get_quote(ticker)
            sections.append(f"  {format_quote(q)}")
            headline = get_top_headline(ticker)
            if headline:
                sections.append(f"     news: {headline}")

    sections.append("")
    sections.append(get_market_indexes())

    return "\n".join(sections)


# Lets you test this file alone:  python3 -m sources.portfolio
if __name__ == "__main__":
    print(get_portfolio_summary())
