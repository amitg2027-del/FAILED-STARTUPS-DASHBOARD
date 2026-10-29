"""Paper (practice) trading account. No real money and no broker: orders "fill" at
the price you see, and everything is saved in data/paper_account.json.

Every position blocks some cash when it opens ("blocked"): the full cost for shares
and bought options, a margin for futures and sold options. Closing it returns the
blocked cash plus or minus the profit or loss.
"""

import datetime as dt
import json
import os
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "data", "paper_account.json")

START_CASH = {"IN": 1_000_000.0, "US": 10_000.0}


def _blank(market_key, cash=None):
    c = START_CASH[market_key] if cash is None else float(cash)
    return {"start_cash": c, "cash": c, "positions": [], "log": []}


def load(path=PATH):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        doc = {}
    for k in START_CASH:
        doc.setdefault(k, _blank(k))
    return doc


def save(doc, path=PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, default=str)
    os.replace(tmp, path)


def reset(doc, market_key, cash=None):
    doc[market_key] = _blank(market_key, cash)


def sign(side):
    return 1 if side == "buy" else -1


def open_position(acct, *, kind, symbol, side, qty, price, blocked, now, **extra):
    """Add a position and take `blocked` cash. Raises ValueError if cash is short."""
    if qty <= 0:
        raise ValueError("Quantity must be above zero.")
    if blocked > acct["cash"] + 1e-6:
        raise ValueError("Not enough practice cash: this needs %.2f, you have %.2f." % (blocked, acct["cash"]))
    pos = {"id": uuid.uuid4().hex[:8], "kind": kind, "symbol": symbol, "side": side, "qty": qty,
           "entry": float(price), "blocked": float(blocked), "opened": now.isoformat(timespec="seconds")}
    pos.update(extra)
    acct["cash"] -= blocked
    acct["positions"].append(pos)
    acct["log"].append({"time": pos["opened"], "action": "open", "kind": kind, "symbol": label(pos),
                        "side": side, "qty": qty, "price": float(price), "pnl": None})
    return pos


def pnl(pos, mark):
    return sign(pos["side"]) * (mark - pos["entry"]) * pos["qty"]


def close_position(acct, pos_id, mark, now, reason="closed by you"):
    pos = next(p for p in acct["positions"] if p["id"] == pos_id)
    gain = pnl(pos, mark)
    acct["cash"] += pos["blocked"] + gain
    acct["positions"] = [p for p in acct["positions"] if p["id"] != pos_id]
    acct["log"].append({"time": now.isoformat(timespec="seconds"), "action": "close (%s)" % reason,
                        "kind": pos["kind"], "symbol": label(pos), "side": "sell" if pos["side"] == "buy" else "buy",
                        "qty": pos["qty"], "price": float(mark), "pnl": gain})
    return gain


def label(pos):
    if pos["kind"] in ("call", "put"):
        return "%s %s %s %s" % (pos["symbol"], pos["expiry"], fmt_strike(pos["strike"]), pos["kind"].upper())
    if pos["kind"] == "future":
        return "%s FUT %s" % (pos["symbol"], pos["expiry"])
    return pos["symbol"]


def fmt_strike(k):
    return ("%.2f" % k).rstrip("0").rstrip(".")


def today_stats(acct, local_today):
    """(realised P&L today, new trades opened today) in the market's local date."""
    realised, opened = 0.0, 0
    for row in acct["log"]:
        try:
            d = dt.datetime.fromisoformat(row["time"]).date()
        except ValueError:
            continue
        if d != local_today:
            continue
        if row["action"] == "open":
            opened += 1
        elif row["pnl"] is not None:
            realised += row["pnl"]
    return realised, opened
