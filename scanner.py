
import yfinance as yf
import pandas as pd
import requests
import json
import os
from io import StringIO
from datetime import datetime, time
import pytz

IST = pytz.timezone("Asia/Kolkata")
NSE_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"


def get_fno_stocks():
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(NSE_URL, headers=headers, timeout=30)
    response.raise_for_status()

    df = pd.read_csv(StringIO(response.text))
    symbol_col = next(
        (c for c in df.columns if "symbol" in c.lower()), None
    )

    if symbol_col is None:
        raise ValueError("F&O list-e Symbol column paoa jayni")

    stocks = sorted(set(
        str(x).strip().upper()
        for x in df[symbol_col].dropna()
        if str(x).strip()
    ))

    with open("fno_stocks.json", "w") as f:
        json.dump(stocks, f, indent=2)

    return stocks


def get_stochastic(daily):
    low = daily["Low"].rolling(14).min()
    high = daily["High"].rolling(14).max()
    denominator = (high - low).replace(0, float("nan"))

    k = 100 * (daily["Close"] - low) / denominator
    d = k.rolling(3).mean()

    return k, d


def scan_stock(symbol):
    ticker = symbol + ".NS"

    intraday = yf.download(
        ticker, period="60d", interval="15m",
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

    if len(intraday) < 53 or len(daily) < 20:
        return None

    intraday.index = pd.to_datetime(intraday.index)

    if intraday.index.tz is None:
        intraday.index = intraday.index.tz_localize("UTC")

    intraday.index = intraday.index.tz_convert(IST)
    intraday["session"] = intraday.index.date

    today = datetime.now(IST).date()
    today_data = intraday[intraday["session"] == today].copy()

    if len(today_data) < 3:
        return None

    first_bar = today_data.iloc[0]

    # Today's first candle-er ager 50-ti 15-minute candle
    previous_candles = intraday[
        intraday.index < today_data.index[0]
    ]

    previous_50 = previous_candles.tail(50)

    if len(previous_50) < 50:
        return None

    average_volume = previous_50["Volume"].mean()

    # Shudhu completed 15-minute candles
    now = datetime.now(IST)
    completed = today_data[
        today_data.index + pd.Timedelta(minutes=15) <= now
    ]

    if len(completed) < 3:
        return None

    c0 = completed.iloc[-1]
    c1 = completed.iloc[-2]
    c2 = completed.iloc[-3]

    k, d = get_stochastic(daily)

    if pd.isna(k.iloc[-1]) or pd.isna(d.iloc[-1]):
        return None

    volume_filter = (
        float(first_bar["Volume"]) > float(average_volume) * 5
    )

    buy = (
        volume_filter
        and c1["Volume"] < c2["Volume"]
        and c0["Volume"] > c1["Volume"]
        and c0["Close"] > first_bar["Open"]
        and c1["Close"] <= c1["Open"]
        and c0["Close"] > c1["High"]
        and k.iloc[-1] > d.iloc[-1]
    )

    sell = (
        volume_filter
        and c1["Volume"] < c2["Volume"]
        and c0["Volume"] > c1["Volume"]
        and c0["Close"] < first_bar["Open"]
        and c1["Close"] >= c1["Open"]
        and c0["Close"] < c1["Low"]
        and k.iloc[-1] < d.iloc[-1]
    )

    if buy or sell:
        return {
            "symbol": symbol,
            "signal": "BUY" if buy else "SELL",
            "price": round(float(c0["Close"]), 2)
        }

    return None


def main():
    now = datetime.now(IST)

    if now.weekday() >= 5 or not (
        time(9, 15) <= now.time() <= time(15, 30)
    ):
        print("Market time-er baire. Scan kora holo na.")
        return

    stocks = get_fno_stocks()
    results = []

    for i, symbol in enumerate(stocks, 1):
        try:
            result = scan_stock(symbol)
            if result:
                results.append(result)

            print(f"{i}/{len(stocks)} scanned: {symbol}")

        except Exception as error:
            print(f"Error: {symbol} - {error}")

    os.makedirs("data", exist_ok=True)

    output = {
        "last_scan": now.strftime("%d-%m-%Y %H:%M:%S"),
        "buy": [x for x in results if x["signal"] == "BUY"],
        "sell": [x for x in results if x["signal"] == "SELL"]
    }

    with open("data/signals.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Scan complete:", len(results), "signals")


if __name__ == "__main__":
    main()
