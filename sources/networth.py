"""
sources/networth.py
Calculates total net worth from config/positions.json + live prices.
"""
import json
from pathlib import Path
import yfinance as yf

POSITIONS_FILE = Path(__file__).parent.parent / "config" / "positions.json"

ACCOUNT_COLOR = {
    "taxable":     "#6FC8D6",
    "roth_ira":    "#9B8CE6",
    "self_custody":"#D9B36A",
}


def get_prices(tickers: list[str]) -> dict[str, float]:
    prices = {}
    for t in tickers:
        if not t:
            continue
        try:
            prices[t] = round(yf.Ticker(t).fast_info.last_price, 4)
        except Exception:
            prices[t] = None
    return prices


def calculate(positions_file: Path = POSITIONS_FILE) -> dict:
    data = json.loads(positions_file.read_text())
    accounts = data["accounts"]

    # Collect all unique tickers
    all_tickers = list({
        h["ticker"]
        for acc in accounts
        for h in acc["holdings"]
        if h["shares"] and h["shares"] > 0
    })

    prices = get_prices(all_tickers)

    total_value    = 0.0
    total_cost     = 0.0
    account_rows   = []

    for acc in accounts:
        acc_value = 0.0
        acc_cost  = 0.0
        holdings  = []

        for h in acc["holdings"]:
            ticker = h["ticker"]
            shares = h.get("shares") or 0
            cost_per = h.get("cost_per_share")
            price = prices.get(ticker)

            if not price or not shares:
                continue

            value = round(price * shares, 2)
            cost  = round(cost_per * shares, 2) if cost_per else None
            pnl   = round(value - cost, 2)   if cost else None
            pnl_pct = round((pnl / cost) * 100, 2) if cost else None

            acc_value += value
            if cost:
                acc_cost += cost

            holdings.append({
                "ticker":  ticker,
                "shares":  shares,
                "price":   price,
                "value":   value,
                "cost":    cost,
                "pnl":     pnl,
                "pnl_pct": pnl_pct,
            })

        total_value += acc_value
        total_cost  += acc_cost

        account_rows.append({
            "id":       acc["id"],
            "name":     acc["name"],
            "type":     acc["type"],
            "broker":   acc["broker"],
            "value":    round(acc_value, 2),
            "cost":     round(acc_cost, 2) if acc_cost else None,
            "color":    ACCOUNT_COLOR.get(acc["type"], "#5A6069"),
            "holdings": holdings,
        })

    total_pnl = round(total_value - total_cost, 2) if total_cost else None
    total_pnl_pct = round((total_pnl / total_cost) * 100, 2) if total_cost else None

    cash = data.get("cash", [])
    cash_total = sum(c.get("amount", 0) for c in cash)

    return {
        "total":     round(total_value + cash_total, 2),
        "investments": round(total_value, 2),
        "cost":      round(total_cost, 2),
        "pnl":       total_pnl,
        "pnl_pct":   total_pnl_pct,
        "accounts":  account_rows,
        "prices":    prices,
        "cash":      cash,
        "cash_total": cash_total,
    }


if __name__ == "__main__":
    r = calculate()
    print(f"\nTotal Net Worth: ${r['total']:,.2f}")
    if r['pnl']:
        sign = "+" if r['pnl'] >= 0 else ""
        print(f"P&L (known basis): {sign}${r['pnl']:,.2f} ({sign}{r['pnl_pct']}%)")
    print()
    for acc in r["accounts"]:
        print(f"  {acc['name']:35} ${acc['value']:>12,.2f}")
        for h in acc["holdings"]:
            pnl_str = f"  P&L: ${h['pnl']:+,.2f}" if h['pnl'] is not None else ""
            print(f"    {h['ticker']:8} {h['shares']} sh @ ${h['price']:>10,.2f} = ${h['value']:>10,.2f}{pnl_str}")
