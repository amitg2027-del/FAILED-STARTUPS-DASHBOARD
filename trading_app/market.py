"""Markets and price data.

Prices come from Yahoo Finance's free chart endpoint (the same source the
day-trader skill uses). It is unofficial, can lag by a few minutes and has no
live option chains, so option and futures prices in this app are calculated
(see derivatives.py), not quoted.
"""

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import pandas as pd

UA = "Mozilla/5.0 (compatible; paper-trading-app/1.0)"
HOSTS = ("query2", "query1")


@dataclass(frozen=True)
class Market:
    key: str
    name: str
    tz: str
    open: dt.time
    close: dt.time
    currency: str
    symbol_suffix: str          # added to plain tickers: RELIANCE -> RELIANCE.NS
    risk_free: float            # default yearly rate for option and futures maths
    margin_pct: float           # default futures / option-selling margin, % of notional
    watchlist: tuple = ()
    indices: dict = field(default_factory=dict)   # name -> (yahoo symbol, default lot size)
    stock_lot_note: str = ""

    @property
    def zone(self):
        return ZoneInfo(self.tz)

    @property
    def session_bars(self):
        """Number of 5-minute bars in a full session."""
        mins = (self.close.hour * 60 + self.close.minute) - (self.open.hour * 60 + self.open.minute)
        return mins // 5

    def yahoo(self, sym):
        """User text -> Yahoo symbol. Index symbols (^...) and symbols that already
        carry an exchange suffix are left alone."""
        s = sym.strip().upper()
        if not s or s.startswith("^") or "." in s or not self.symbol_suffix:
            return s
        return s + self.symbol_suffix

    def money(self, x):
        if x is None:
            return "-"
        sign = "-" if x < 0 else ""
        return f"{sign}{self.currency}{abs(x):,.2f}"


MARKETS = {
    "IN": Market(
        key="IN", name="India (NSE)", tz="Asia/Kolkata",
        open=dt.time(9, 15), close=dt.time(15, 30), currency="₹", symbol_suffix=".NS",
        risk_free=0.065, margin_pct=15.0,
        watchlist=("RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "ITC", "LT",
                   "BHARTIARTL", "AXISBANK", "KOTAKBANK", "HINDUNILVR", "MARUTI", "TATAMOTORS",
                   "SUNPHARMA", "BAJFINANCE"),
        # NSE revises lot sizes from time to time: always check nseindia.com before relying on these.
        indices={"NIFTY 50": ("^NSEI", 75), "NIFTY BANK": ("^NSEBANK", 35)},
        stock_lot_note="Each NSE stock has its own F&O lot size (e.g. a few hundred shares). "
                       "Look it up on nseindia.com and type it in.",
    ),
    "US": Market(
        key="US", name="United States (NYSE / Nasdaq)", tz="America/New_York",
        open=dt.time(9, 30), close=dt.time(16, 0), currency="$", symbol_suffix="",
        risk_free=0.04, margin_pct=20.0,
        watchlist=("TSLA", "AAPL", "NVDA", "MSFT", "AMZN", "META", "GOOGL", "AMD", "NFLX", "SPY", "QQQ"),
        indices={"S&P 500 (SPY)": ("SPY", 100), "Nasdaq 100 (QQQ)": ("QQQ", 100)},
        stock_lot_note="One US stock option contract covers 100 shares.",
    ),
}


class DataError(Exception):
    """A plain-English problem fetching prices."""


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def fetch_chart(symbol, rng="60d", interval="5m"):
    """Yahoo v8 chart -> raw result dict. Tries query2 then query1, waits once on 429."""
    path = "/v8/finance/chart/%s?range=%s&interval=%s" % (urllib.parse.quote(symbol), rng, interval)
    last = None
    for attempt, host in enumerate(HOSTS + HOSTS[:1]):
        try:
            doc = json.loads(_get("https://%s.finance.yahoo.com%s" % (host, path)))
            res = (doc.get("chart") or {}).get("result")
            if not res:
                err = (doc.get("chart") or {}).get("error") or {}
                raise DataError("Yahoo has no data for %s (%s)." % (symbol, err.get("description", "unknown symbol")))
            return res[0]
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise DataError("Yahoo does not know the symbol %s. Check the spelling." % symbol)
            if e.code == 429:
                time.sleep(3)
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
    raise DataError("Could not reach Yahoo Finance for %s (%s). Try again in a minute." % (symbol, last))


def bars_frame(result, market):
    """Raw chart result -> DataFrame indexed by exchange-local time with open/high/low/close/volume.
    Rows with a missing price are dropped."""
    ts = result.get("timestamp") or []
    q = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    df = pd.DataFrame({
        "open": q.get("open"), "high": q.get("high"), "low": q.get("low"),
        "close": q.get("close"), "volume": q.get("volume"),
    }, index=pd.to_datetime(ts, unit="s", utc=True).tz_convert(market.tz))
    df.index.name = "time"
    return df.dropna(subset=["open", "high", "low", "close"])


def intraday(symbol, market, rng="60d"):
    """5-minute bars inside regular hours only (drops the odd 16:00 print)."""
    df = bars_frame(fetch_chart(symbol, rng, "5m"), market)
    t = df.index.time
    return df[(t >= market.open) & (t < market.close)]


def daily(symbol, market, rng="1y"):
    df = bars_frame(fetch_chart(symbol, rng, "1d"), market)
    df.index = df.index.normalize()
    return df[~df.index.duplicated(keep="last")]


def last_price(symbol, market):
    """(price, time) of the latest trade Yahoo reports."""
    meta = fetch_chart(symbol, "1d", "1d").get("meta") or {}
    p = meta.get("regularMarketPrice")
    if p is None:
        raise DataError("No current price for %s." % symbol)
    t = meta.get("regularMarketTime")
    when = dt.datetime.fromtimestamp(t, market.zone) if t else None
    return float(p), when


def market_status(market, now=None):
    """Plain-English open/closed status. Weekends count as closed; exchange holidays
    are not listed, so on a holiday this can say 'open' while prices do not move."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(market.zone)
    weekday = now.weekday() < 5
    is_open = weekday and market.open <= now.time() < market.close
    if is_open:
        text = "OPEN until %s" % market.close.strftime("%H:%M")
    elif weekday and now.time() < market.open:
        text = "CLOSED, opens today at %s" % market.open.strftime("%H:%M")
    else:
        text = "CLOSED"
    return is_open, "%s (%s local time is %s)" % (text, market.name, now.strftime("%a %d %b, %H:%M"))


def split_sessions(df, market, max_missing=5):
    """5-minute bars -> {date: DataFrame of exactly session_bars rows}.
    Yahoo leaves a few NSE bars empty most days, so up to `max_missing` gaps are
    filled with a flat bar at the previous close (volume 0); days with more gaps,
    or with the first bar missing (half days, outages), are left out."""
    out = {}
    n = market.session_bars
    for day, g in df.groupby(df.index.date):
        if len(g) < n - max_missing:
            continue
        full = fill_session(g, market, n)
        if full is not None:
            out[day] = full
    return out


def fill_session(g, market, n=None):
    """One day's bars on the exact 5-minute grid from the open, gaps filled flat.
    Without `n` the grid runs to the last bar present (a session still trading).
    None if the first bar is missing or a bar sits off the grid."""
    day = g.index[0].date()
    start = pd.Timestamp(dt.datetime.combine(day, market.open), tz=market.tz)
    if n is None:
        n = int((g.index[-1] - start) / pd.Timedelta(minutes=5)) + 1
    grid = pd.date_range(start, periods=n, freq="5min")
    if g.index[0] != grid[0] or not g.index.isin(grid).all():
        return None
    full = g.reindex(grid)
    gap = full["close"].isna()
    full["close"] = full["close"].ffill()
    for col in ("open", "high", "low"):
        full.loc[gap, col] = full.loc[gap, "close"]
    full.loc[gap, "volume"] = 0
    full.index.name = "time"
    return full
