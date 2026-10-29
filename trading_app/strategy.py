"""Day-trading logic, adapted from the day-trader skill
(https://github.com/Jakeschincariol/day-trader-skill, MIT licence) so it works
for any market's session hours, not only New York's.

    find_setups      the skill's daily chart scanner (trader-scanner)
    opening_range    15-minute opening range and the first close above/below it (trader-entry)
    exit_plan        stop and target before you enter (trader-exit)
    time_machine     10,000 replays of the rest of the session (trader-timemachine)
    history_replay   the same rule on every past session (trader-timemachine)
    size_position    shares from your max loss per trade (trader-budget)
    risk_check       PASS / BLOCK against your limits (trader-risk)
"""

import math

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- scanner (daily setups)

def rsi(closes, n=14):
    """Wilder's RSI, the same maths as the skill's scanner."""
    if len(closes) < n + 1:
        return None
    g = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    lo = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag, al = sum(g[:n]) / n, sum(lo[:n]) / n
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + lo[i]) / n
    return 100 - 100 / (1 + ag / al) if al else 100.0


SETUP_LABELS = {
    "breakout_20d": "20-day breakout (closed above the highest close of the last 20 days)",
    "bull_flag": "Bull flag (up over 10% then a tight 5-day pause)",
    "reclaim_ma20": "Reclaimed the 20-day average",
    "oversold": "Oversold (RSI under 30)",
    "oversold_bounce": "Oversold bounce (RSI was under 30 and today closed higher)",
}


def find_setups(closes):
    """Daily closes, oldest first (at least 30) -> (setup keys, numbers)."""
    c = list(closes)
    last = c[-1]
    hi20 = max(c[-21:-1])
    ma20 = sum(c[-20:]) / 20.0
    ma20_prev = sum(c[-21:-1]) / 20.0
    run = c[-6] / c[-16] - 1
    rng5 = (max(c[-5:]) - min(c[-5:])) / last
    r = rsi(c)
    r_prev = rsi(c[:-1])
    tags = []
    if last > hi20:
        tags.append("breakout_20d")
    if run > 0.10 and rng5 < 0.05:
        tags.append("bull_flag")
    if c[-2] < ma20_prev and last > ma20:
        tags.append("reclaim_ma20")
    if r is not None and r < 30:
        tags.append("oversold")
    if r_prev is not None and r_prev < 30 and last > c[-2]:
        tags.append("oversold_bounce")
    return tags, {"rsi": r, "high20": hi20, "ma20": ma20, "run_pct": run * 100, "range5_pct": rng5 * 100}


# ---------------------------------------------------------------- entry: opening-range breakout

def opening_range(session, n_bars=3):
    """(high, low) of the first n 5-minute bars (3 bars = the first 15 minutes)."""
    first = session.iloc[:n_bars]
    return float(first["high"].max()), float(first["low"].min())


def orb_trigger(session, n_bars=3, side="buy"):
    """The first completed bar after the range to CLOSE beyond it.
    -> dict(index, time the bar closed, price, or_high, or_low) or None."""
    if len(session) <= n_bars:
        return None
    oh, ol = opening_range(session, n_bars)
    for k in range(n_bars, len(session)):
        c = float(session["close"].iloc[k])
        if (c > oh) if side == "buy" else (c < ol):
            return {"index": k, "time": session.index[k] + pd.Timedelta(minutes=5), "price": round(c, 2),
                    "or_high": oh, "or_low": ol}
    return None


# ---------------------------------------------------------------- exit plan

STOP_RULES = {
    "or_mid": "Middle of the opening range",
    "or_edge": "Other side of the opening range",
    "pct": "A fixed % from the entry",
}


def away(x, long):
    """Round a stop to 2 decimals, away from the entry."""
    c = round(x * 100, 4)
    return (math.floor(c) if long else math.ceil(c)) / 100.0


def exit_plan(entry, side, stop_rule, or_high, or_low, stop_pct=1.0, target_r=1.0):
    """-> dict(stop, target, risk_per_share) or raises ValueError in plain words."""
    long = side == "buy"
    if stop_rule == "or_mid":
        stop = away((or_high + or_low) / 2, long)
    elif stop_rule == "or_edge":
        stop = away(or_low if long else or_high, long)
    else:
        stop = away(entry * (1 - stop_pct / 100) if long else entry * (1 + stop_pct / 100), long)
    risk = (entry - stop) if long else (stop - entry)
    if risk <= 0:
        raise ValueError("The stop (%.2f) is on the wrong side of the entry (%.2f). "
                         "Pick a different stop rule." % (stop, entry))
    target = round(entry + target_r * risk, 2) if long else round(entry - target_r * risk, 2)
    return {"stop": stop, "target": target, "risk_per_share": round(risk, 4), "target_r": target_r}


# ---------------------------------------------------------------- Time Machine

def build_pool(sessions):
    """pool[i] = array of every past session's bar i as (high, low, close) / bar i-1's close."""
    days = list(sessions.values())
    n = len(days[0])
    pool = [None]
    for i in range(1, n):
        rows = []
        for d in days:
            pc = d["close"].iloc[i - 1]
            rows.append((d["high"].iloc[i] / pc, d["low"].iloc[i] / pc, d["close"].iloc[i] / pc))
        pool.append(np.array(rows))
    return pool


def time_machine(sessions, entry, stop, target, k, last, side="buy", replays=10000, seed=19, window=2):
    """Replays bars k+1..last from `entry`. Each bar is drawn from the stock's own past bars at
    about the same time of day (+/- `window` bars) and scaled to the current price. The stop is
    checked before the target in every bar (a bar touching both counts as a loss).
    -> dict of odds, percentiles and a fan of price paths."""
    long = side == "buy"
    risk = (entry - stop) if long else (stop - entry)
    r_target = ((target - entry) if long else (entry - target)) / risk
    pool = build_pool(sessions)
    n_slots = len(pool)
    rng = np.random.default_rng(seed)

    p = np.full(replays, float(entry))
    outcome = np.zeros(replays, dtype=np.int8)    # 0 open, 1 target, -1 stop
    paths = [p.copy()]
    for i in range(k + 1, last + 1):
        j = np.clip(i + rng.integers(-window, window + 1, size=replays), 1, n_slots - 1)
        hi = np.empty(replays)
        lo = np.empty(replays)
        cl = np.empty(replays)
        for slot in np.unique(j):
            mask = j == slot
            rows = pool[slot][rng.integers(0, len(pool[slot]), size=mask.sum())]
            hi[mask], lo[mask], cl[mask] = rows[:, 0], rows[:, 1], rows[:, 2]
        hi, lo = p * hi, p * lo
        open_ = outcome == 0
        if long:
            hit_stop = open_ & (lo <= stop)
            hit_tgt = open_ & ~hit_stop & (hi >= target)
        else:
            hit_stop = open_ & (hi >= stop)
            hit_tgt = open_ & ~hit_stop & (lo <= target)
        outcome[hit_stop] = -1
        outcome[hit_tgt] = 1
        p = p * cl
        paths.append(p.copy())

    final = p
    move = (final - entry) if long else (entry - final)
    R = np.where(outcome == 1, r_target, np.where(outcome == -1, -1.0, move / risk))
    green = (outcome == 1) | ((outcome == 0) & (move > 0))
    paths = np.array(paths)                         # (bars, replays)
    bands = np.percentile(paths, [5, 25, 50, 75, 95], axis=1)
    p_t, p_s = float((outcome == 1).mean()), float((outcome == -1).mean())
    return {
        "replays": replays, "seed": seed, "bars_left": last - k,
        "p_target": p_t, "p_stop": p_s, "p_neither": float((outcome == 0).mean()),
        "p_green": float(green.mean()), "avg_R": float(R.mean()), "r_target": r_target,
        "median_close": float(np.median(final)), "p5_close": float(np.percentile(final, 5)),
        "p95_close": float(np.percentile(final, 95)), "bands": bands,
        "sample_paths": paths[:, :60], "finals": final,
        "verdict": verdict(p_t, p_s, r_target),
    }


def verdict(p_target, p_stop, r_target):
    """The skill's verdict: compare target / (target + stop) with the break-even share 1 / (1 + R)."""
    decided = p_target + p_stop
    if decided == 0:
        return "No replay reached the stop or the target before the close: the closing price decides."
    share = p_target / decided
    gap = share - 1 / (1 + r_target)
    if abs(gap) < 0.05:
        return "Close to a coin flip." if abs(r_target - 1) < 1e-9 else "Close to break-even."
    word = "target" if gap > 0 else "stop"
    return ("Strongly toward the %s." if abs(gap) >= 0.15 else "Leans toward the %s.") % word


def history_replay(sessions, n_range, stop_rule, stop_pct, target_r, last, side="buy"):
    """The same opening-range rule on every past full session."""
    long = side == "buy"
    trades = []
    for day, d in sessions.items():
        trig = orb_trigger(d.iloc[:last + 1], n_range, side)
        if trig is None:
            continue
        try:
            plan = exit_plan(trig["price"], side, stop_rule, trig["or_high"], trig["or_low"], stop_pct, target_r)
        except ValueError:
            continue
        s, t, e, kk = plan["stop"], plan["target"], trig["price"], trig["index"]
        oc = "close"
        for _, b in d.iloc[kk + 1:last + 1].iterrows():
            if (b["low"] <= s) if long else (b["high"] >= s):
                oc = "stop"
                break
            if (b["high"] >= t) if long else (b["low"] <= t):
                oc = "target"
                break
        cl = float(d["close"].iloc[last])
        risk = plan["risk_per_share"]
        R = target_r if oc == "target" else -1.0 if oc == "stop" else ((cl - e) if long else (e - cl)) / risk
        trades.append({"date": day, "entry time": trig["time"].strftime("%H:%M"), "entry": e,
                       "stop": s, "target": t, "outcome": oc, "R": round(R, 2)})
    return trades


# ---------------------------------------------------------------- budget and risk

def size_position(entry, stop, max_loss, cash, max_position_pct=100.0, lot=1):
    """Shares (in whole lots) so a fill at the stop loses at most `max_loss`,
    capped by cash and by the biggest position allowed."""
    risk = abs(entry - stop)
    if risk <= 0 or entry <= 0:
        return 0
    by_risk = math.floor(max_loss / risk)
    by_cash = math.floor(cash / entry)
    by_cap = math.floor(cash * max_position_pct / 100 / entry)
    qty = min(by_risk, by_cash, by_cap)
    return int(qty // lot * lot)


def risk_check(order, limits, account):
    """order: dict(qty, entry, stop, target, side). limits: dict(max_loss, daily_loss, max_trades,
    min_rr, max_position_pct). account: dict(cash, realized_today, trades_today, market_open).
    -> list of (rule, passed, explanation)."""
    qty, e, s, t = order["qty"], order["entry"], order["stop"], order["target"]
    risk = abs(e - s) * qty
    reward = abs(t - e) * qty
    cost = e * qty
    rr = reward / risk if risk else 0
    rows = [
        ("Quantity is above zero", qty > 0, "%d shares" % qty),
        ("Loss at the stop is within your max loss per trade", risk <= limits["max_loss"] + 1e-9,
         "%.2f at risk vs a limit of %.2f" % (risk, limits["max_loss"])),
        ("Daily loss limit not reached", -account["realized_today"] + risk <= limits["daily_loss"] + 1e-9,
         "lost %.2f today, plus %.2f at risk, vs %.2f" % (max(0.0, -account["realized_today"]), risk,
                                                         limits["daily_loss"])),
        ("Trades per day", account["trades_today"] < limits["max_trades"],
         "%d of %d used" % (account["trades_today"], limits["max_trades"])),
        ("Reward is big enough for the risk", rr >= limits["min_rr"] - 1e-9,
         "reward/risk %.2f vs a minimum of %.2f" % (rr, limits["min_rr"])),
        ("Position size", cost <= account["cash"] * limits["max_position_pct"] / 100 + 1e-9,
         "%.2f is %.0f%% of your cash (limit %.0f%%)" % (cost, 100 * cost / account["cash"] if account["cash"] else 0,
                                                         limits["max_position_pct"])),
        ("Enough cash", cost <= account["cash"] + 1e-9, "needs %.2f, you have %.2f" % (cost, account["cash"])),
    ]
    if limits.get("require_open", True):
        rows.append(("Market is open", account["market_open"], "practice orders fill at the latest price"))
    return rows
