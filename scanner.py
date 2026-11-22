
import yfinance as yf
import pandas as pd
import json
import os
import requests
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")

# NSE official F&O eligible stocks list
NSE_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"

def get_fno_stocks():
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(NSE_URL, headers=headers, timeout=20)
        response.raise_for_status()

        from io import StringIO
        table = pd.read_csv(StringIO(response.text))

        column = next(
            (c for c in table.columns if "symbol" in c.lower()),
            None
        )
        if column is None:
            raise ValueError("Symbol column not found")

        stocks = sorted(set(
            str(x).strip().upper()
            for x in table[column].dropna()
            if str(x).strip()
        ))

        with open("fno_stocks.json", "w") as f:
            json.dump(stocks, f, indent=2)

        return stocks

    except Exception as e:
        print("NSE list download failed:", e)

        if os.path.exists("fno_stocks.json"):
            with open("fno_stocks.json") as f:
                return json.load(f)

        return []


def slow_stochastic(daily):
    low14 = daily["Low"].rolling(14).min()
    high14 = daily["High"].rolling(14).max()
    spread = (high14 - low14).replace(0, float("nan"))
    fast_k = 100 * (daily["Close"] - low14) / spread
    slow_k = fast_k.rolling(3).mean()
    slow_d = slow_k.rolling(3).mean()
    return slow_k, slow_d


def scan_stock(symbol):
    try:
        ticker = symbol + ".NS"

        intraday = yf.download(
            ticker, period="5d", interval="15m",
            progress=False, auto_adjust=False
        )

        daily = yf.download(
            ticker, period="6mo", interval="1d",
            progress=False, auto_adjust=False
        )

        if intraday.empty or daily.empty:
            return None

        if isinstance(intraday.columns, pd.MultiIndex):
            intraday.columns = intraday.columns.get_level_values(0)

        if isinstance(daily.columns, pd.MultiIndex):
            daily.columns = daily.columns.get_level_values(0)

        intraday = intraday.dropna()
        daily = daily.dropna()

        now = datetime.now(IST)
        intraday.index = pd.to_datetime(intraday.index)

        if intraday.index.tz is None:
            intraday.index = intraday.index.tz_localize("Asia/Kolkata")
        else:
            intraday.index = intraday.index.tz_convert("Asia/Kolkata")

        today = intraday[intraday.index.date == now.date()]

        # Need at least 4 candles; ignore the still-forming candle
        if len(today) < 4:
            return None

        completed = today.iloc[:-1]
        if len(completed) < 3:
            return None

        first = today.iloc[0]
        c0, c1, c2 = completed.iloc[-1], completed.iloc[-2], completed.iloc[-3]

        # Previous 50 sessions' first 15-minute volumes
        old = intraday[intraday.index.date < now.date()]
        first_volumes = [
            group.iloc[0]["Volume"]
            for _, group in old.groupby(old.index.date)
            if len(group) > 0
        ]

        if len(first_volumes) < 50:
            return None

        avg_first_volume = sum(first_volumes[-50:]) / 50
        volume_filter = first["Volume"] > avg_first_volume * 5

        k, d = slow_stochastic(daily)
        if pd.isna(k.iloc[-1]) or pd.isna(d.iloc[-1]):
            return None

        buy = (
            volume_filter
            and c1["Volume"] < c2["Volume"]
            and c0["Volume"] > c1["Volume"]
            and c0["Close"] > first["Open"]
            and c1["Close"] <= c1["Open"]
            and c0["Close"] > c1["High"]
            and k.iloc[-1] > d.iloc[-1]
        )

        sell = (
            volume_filter
            and c1["Volume"] < c2["Volume"]
            and c0["Volume"] > c1["Volume"]
            and c0["Close"] < first["Open"]
            and c1["Close"] >= c1["Open"]
            and c0["Close"] < c1["Low"]
            and k.iloc[-1] < d.iloc[-1]
        )

        if buy or sell:
            return {
                "symbol": symbol,
                "signal": "BUY" if buy else "SELL",
                "price": round(float(c0["Close"]), 2),
                "time": str(completed.index[-1])
            }

    except Exception as e:
        print("Error scanning", symbol, e)

    return None


def main():
    stocks = get_fno_stocks()
    print("F&O stocks loaded:", len(stocks))

    results = []

    for symbol in stocks:
        print("Scanning:", symbol)
        result = scan_stock(symbol)
        if result:
            results.append(result)

    output = {
        "last_scan": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
        "results": results
    }

    os.makedirs("data", exist_ok=True)

    with open("data/signals.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Scan complete:", len(results), "signals")


if __name__ == "__main__":
    main()
