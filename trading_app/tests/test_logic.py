"""Offline checks of the maths. Run from the repository folder:
    python -m unittest discover -s trading_app/tests
"""

import datetime as dt
import math
import os
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import derivatives as dv  # noqa: E402
import market as mk  # noqa: E402
import paper  # noqa: E402
import strategy as sg  # noqa: E402


def session(day, closes, market):
    """A full fake session: each bar opens at the previous close, high/low 0.1 either side."""
    idx = pd.date_range(pd.Timestamp(dt.datetime.combine(day, market.open), tz=market.tz),
                        periods=len(closes), freq="5min")
    opens = [closes[0]] + list(closes[:-1])
    return pd.DataFrame({"open": opens, "high": np.maximum(opens, closes) + 0.1,
                         "low": np.minimum(opens, closes) - 0.1, "close": closes, "volume": 1}, index=idx)


class Derivatives(unittest.TestCase):
    def test_black_scholes_textbook(self):
        c = dv.bs(100, 100, 1, 0.2, 0.05, "call")
        p = dv.bs(100, 100, 1, 0.2, 0.05, "put")
        self.assertAlmostEqual(c["price"], 10.4506, places=3)
        self.assertAlmostEqual(p["price"], 5.5735, places=3)
        # put-call parity: C - P = S - K e^(-rT)
        self.assertAlmostEqual(c["price"] - p["price"], 100 - 100 * math.exp(-0.05), places=9)

    def test_expired_option_is_intrinsic(self):
        self.assertEqual(dv.bs(110, 100, 0, 0.2, 0.05, "call")["price"], 10)
        self.assertEqual(dv.bs(110, 100, 0, 0.2, 0.05, "put")["price"], 0)

    def test_straddle_breakevens(self):
        legs = [{"kind": "call", "side": "buy", "strike": 100, "qty": 1, "premium": 5},
                {"kind": "put", "side": "buy", "strike": 100, "qty": 1, "premium": 5}]
        prices = np.linspace(80, 120, 401)
        exp, _ = dv.payoff(legs, prices, 0.1, 0.2, 0.05)
        be = dv.breakevens(prices, exp)
        self.assertEqual(len(be), 2)
        self.assertAlmostEqual(be[0], 90, places=6)
        self.assertAlmostEqual(be[1], 110, places=6)
        self.assertAlmostEqual(exp.min(), -10, places=6)

    def test_futures_fair(self):
        self.assertAlmostEqual(dv.futures_fair(100, 1, 0.05), 100 * math.exp(0.05))


class Strategy(unittest.TestCase):
    def test_exit_plan_or_mid(self):
        p = sg.exit_plan(364.18, "buy", "or_mid", 362.18, 354.47, target_r=1)
        self.assertEqual(p["stop"], 358.32)          # the skill's TSLA example
        self.assertEqual(p["target"], 370.04)

    def test_exit_plan_wrong_side(self):
        with self.assertRaises(ValueError):
            sg.exit_plan(350, "buy", "or_mid", 362.18, 354.47)

    def test_size_position(self):
        # the skill's example: $50 max loss, 5.86 risk a share -> 8 shares
        self.assertEqual(sg.size_position(364.18, 358.32, 50, 5000), 8)
        self.assertEqual(sg.size_position(100, 99, 1000, 5000), 50)      # capped by cash
        self.assertEqual(sg.size_position(100, 99, 1000, 1e6, lot=75), 975)

    def test_orb_trigger_and_time_machine(self):
        m = mk.MARKETS["IN"]
        n = m.session_bars
        rng = np.random.default_rng(1)
        past = {}
        for i in range(25):
            day = dt.date(2026, 1, 1) + dt.timedelta(days=i)
            past[day] = session(day, 100 * np.cumprod(1 + rng.normal(0, 0.002, n)), m)
        today = session(dt.date(2026, 3, 1), [100, 100.5, 99.8, 100.2, 101.0, 101.2], m)
        trig = sg.orb_trigger(today, 3, "buy")
        self.assertEqual(trig["index"], 4)
        self.assertEqual(trig["time"].strftime("%H:%M"), "09:40")   # the 09:35 bar closes at 09:40
        plan = sg.exit_plan(trig["price"], "buy", "or_mid", trig["or_high"], trig["or_low"])
        tm = sg.time_machine(past, trig["price"], plan["stop"], plan["target"], 4, n - 2, replays=2000)
        self.assertAlmostEqual(tm["p_target"] + tm["p_stop"] + tm["p_neither"], 1.0)
        again = sg.time_machine(past, trig["price"], plan["stop"], plan["target"], 4, n - 2, replays=2000)
        self.assertEqual(tm["p_target"], again["p_target"])         # same seed, same answer

    def test_risk_check_blocks_big_loss(self):
        rows = sg.risk_check({"qty": 100, "entry": 100, "stop": 90, "target": 120, "side": "buy"},
                             {"max_loss": 500, "daily_loss": 2000, "max_trades": 5, "min_rr": 1,
                              "max_position_pct": 100, "require_open": False},
                             {"cash": 1e6, "realized_today": 0, "trades_today": 0, "market_open": False})
        failed = [r for r, ok, _ in rows if not ok]
        self.assertEqual(failed, ["Loss at the stop is within your max loss per trade"])


class Market(unittest.TestCase):
    def test_fill_session_fills_small_gaps(self):
        m = mk.MARKETS["IN"]
        full = session(dt.date(2026, 3, 2), list(np.linspace(100, 110, m.session_bars)), m)
        holey = full.drop(full.index[[10, 40]])
        days = mk.split_sessions(holey, m)
        self.assertEqual(len(days[dt.date(2026, 3, 2)]), 75)
        filled = days[dt.date(2026, 3, 2)]
        self.assertEqual(filled["close"].iloc[10], full["close"].iloc[9])  # flat at the previous close

    def test_symbols(self):
        self.assertEqual(mk.MARKETS["IN"].yahoo("reliance"), "RELIANCE.NS")
        self.assertEqual(mk.MARKETS["IN"].yahoo("^NSEI"), "^NSEI")
        self.assertEqual(mk.MARKETS["US"].yahoo("tsla"), "TSLA")


class Paper(unittest.TestCase):
    def test_open_close_cash(self):
        path = os.path.join(tempfile.mkdtemp(), "acct.json")
        book = paper.load(path)
        acct = book["IN"]
        now = dt.datetime(2026, 3, 2, 10, 0)
        pos = paper.open_position(acct, kind="stock", symbol="X.NS", side="buy", qty=10, price=100,
                                  blocked=1000, now=now)
        self.assertEqual(acct["cash"], 1_000_000 - 1000)
        gain = paper.close_position(acct, pos["id"], 110, now)
        self.assertEqual(gain, 100)
        self.assertEqual(acct["cash"], 1_000_100)
        paper.save(book, path)
        self.assertEqual(paper.load(path)["IN"]["cash"], 1_000_100)
        self.assertEqual(paper.today_stats(acct, now.date()), (100, 1))

    def test_not_enough_cash(self):
        acct = paper.load(os.path.join(tempfile.mkdtemp(), "none.json"))["US"]
        with self.assertRaises(ValueError):
            paper.open_position(acct, kind="stock", symbol="X", side="buy", qty=1, price=1e9, blocked=1e9,
                                now=dt.datetime(2026, 1, 1))


if __name__ == "__main__":
    unittest.main()
