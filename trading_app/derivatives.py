"""Options, futures and derivatives maths.

There is no free live option-chain feed this app can use, so option prices here
are THEORETICAL: the Black-Scholes formula fed with the real current price and
the stock's real historical volatility. Real market prices will differ,
sometimes a lot (around earnings, budget day, or when traders expect a big move).
"""

import math
from statistics import NormalDist

import numpy as np

N = NormalDist()


def hist_vol(closes, days=30):
    """Annualised volatility from the last `days` daily closes (252 trading days a year)."""
    c = np.asarray(closes, dtype=float)[-(days + 1):]
    if len(c) < 3:
        return None
    r = np.diff(np.log(c))
    return float(r.std(ddof=1) * math.sqrt(252))


def bs(spot, strike, years, vol, rate, kind="call", div=0.0):
    """Black-Scholes price and Greeks of a European option.
    Theta is per calendar day, vega and rho per 1 percentage point."""
    if years <= 0 or vol <= 0:
        intrinsic = max(0.0, spot - strike) if kind == "call" else max(0.0, strike - spot)
        delta = (1.0 if spot > strike else 0.0) if kind == "call" else (-1.0 if spot < strike else 0.0)
        return {"price": intrinsic, "delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    sq = vol * math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - div + vol * vol / 2) * years) / sq
    d2 = d1 - sq
    disc_r, disc_q = math.exp(-rate * years), math.exp(-div * years)
    pdf = N.pdf(d1)
    gamma = disc_q * pdf / (spot * sq)
    vega = spot * disc_q * pdf * math.sqrt(years) / 100
    if kind == "call":
        price = spot * disc_q * N.cdf(d1) - strike * disc_r * N.cdf(d2)
        delta = disc_q * N.cdf(d1)
        theta = (-spot * disc_q * pdf * vol / (2 * math.sqrt(years))
                 - rate * strike * disc_r * N.cdf(d2) + div * spot * disc_q * N.cdf(d1)) / 365
        rho = strike * years * disc_r * N.cdf(d2) / 100
    else:
        price = strike * disc_r * N.cdf(-d2) - spot * disc_q * N.cdf(-d1)
        delta = -disc_q * N.cdf(-d1)
        theta = (-spot * disc_q * pdf * vol / (2 * math.sqrt(years))
                 + rate * strike * disc_r * N.cdf(-d2) - div * spot * disc_q * N.cdf(-d1)) / 365
        rho = -strike * years * disc_r * N.cdf(-d2) / 100
    return {"price": price, "delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho}


def strike_step(spot):
    """A sensible gap between strikes for a given price."""
    for limit, step in ((50, 1), (100, 2.5), (250, 5), (1000, 10), (2500, 20), (5000, 50),
                        (20000, 100)):
        if spot < limit:
            return step
    return 500


def atm_strike(spot):
    step = strike_step(spot)
    return round(spot / step) * step


def chain(spot, years, vol, rate, n=8):
    """A theoretical option chain: n strikes either side of the money."""
    step = strike_step(spot)
    mid = atm_strike(spot)
    rows = []
    for k in range(-n, n + 1):
        K = mid + k * step
        if K <= 0:
            continue
        c, p = bs(spot, K, years, vol, rate, "call"), bs(spot, K, years, vol, rate, "put")
        rows.append({"Call price": c["price"], "Call delta": c["delta"], "Strike": K,
                     "Put price": p["price"], "Put delta": p["delta"], "Gamma": c["gamma"],
                     "Theta (call/day)": c["theta"], "Vega (per 1%)": c["vega"]})
    return rows


def futures_fair(spot, years, rate, div=0.0):
    """Cost of carry: F = S * e^((r - q) T)."""
    return spot * math.exp((rate - div) * years)


# ---------------------------------------------------------------- strategies

# Each leg: (kind, side, strike offset in steps from the money). kind is call / put / future.
STRATEGIES = {
    "Long call (bet on a rise)": [("call", "buy", 0)],
    "Long put (bet on a fall)": [("put", "buy", 0)],
    "Long future": [("future", "buy", 0)],
    "Short future": [("future", "sell", 0)],
    "Bull call spread": [("call", "buy", 0), ("call", "sell", 2)],
    "Bear put spread": [("put", "buy", 0), ("put", "sell", -2)],
    "Long straddle (bet on a big move)": [("call", "buy", 0), ("put", "buy", 0)],
    "Long strangle": [("call", "buy", 2), ("put", "buy", -2)],
    "Short straddle (bet on no move, unlimited risk)": [("call", "sell", 0), ("put", "sell", 0)],
    "Iron condor": [("put", "buy", -4), ("put", "sell", -2), ("call", "sell", 2), ("call", "buy", 4)],
    "Covered call (own shares, sell a call)": [("stock", "buy", 0), ("call", "sell", 2)],
    "Protective put (own shares, buy a put)": [("stock", "buy", 0), ("put", "buy", -2)],
}


def leg_value(leg, price, years, vol, rate):
    """Value per unit of one leg at underlying `price` with `years` left."""
    if leg["kind"] in ("stock",):
        return price
    if leg["kind"] == "future":
        return futures_fair(price, years, rate)
    return bs(price, leg["strike"], years, vol, rate, leg["kind"])["price"]


def payoff(legs, prices, years_now, vol, rate):
    """P&L per unit size for each price: at expiry and today (theoretical)."""
    expiry = np.zeros(len(prices))
    today = np.zeros(len(prices))
    for leg in legs:
        sign = 1 if leg["side"] == "buy" else -1
        units = leg["qty"]
        for i, s in enumerate(prices):
            expiry[i] += sign * units * (leg_value(leg, s, 0.0, vol, rate) - leg["premium"])
            today[i] += sign * units * (leg_value(leg, s, years_now, vol, rate) - leg["premium"])
    return expiry, today


def breakevens(prices, pnl):
    """Prices where the expiry P&L crosses zero (linear interpolation)."""
    out = []
    for i in range(1, len(prices)):
        a, b = pnl[i - 1], pnl[i]
        if a == 0:
            out.append(prices[i - 1])
        elif a * b < 0:
            out.append(prices[i - 1] + (prices[i] - prices[i - 1]) * (-a) / (b - a))
    return out
