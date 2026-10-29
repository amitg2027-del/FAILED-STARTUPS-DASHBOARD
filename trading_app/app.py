"""Paper Trading Desk: day trading plus options, futures and derivatives (F&O)
for India (NSE) and the US, with practice money only.

Run it from the repository folder with:
    streamlit run trading_app/app.py
"""

import calendar
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import derivatives as dv  # noqa: E402
import market as mk  # noqa: E402
import paper  # noqa: E402
import strategy as sg  # noqa: E402

st.set_page_config(page_title="Paper Trading Desk", page_icon="📈", layout="wide")


# ---------------------------------------------------------------- cached data

@st.cache_data(ttl=300, show_spinner=False)
def get_intraday(symbol, mkey):
    return mk.intraday(symbol, mk.MARKETS[mkey])


@st.cache_data(ttl=900, show_spinner=False)
def get_daily(symbol, mkey, rng="1y"):
    return mk.daily(symbol, mk.MARKETS[mkey], rng)


@st.cache_data(ttl=60, show_spinner=False)
def get_price(symbol, mkey):
    return mk.last_price(symbol, mk.MARKETS[mkey])


def now_local(m):
    return dt.datetime.now(dt.timezone.utc).astimezone(m.zone)


def safe(fn, *args):
    """Run a data fetch; show a friendly error instead of a crash."""
    try:
        return fn(*args)
    except mk.DataError as e:
        st.error(str(e))
    except Exception as e:  # network hiccups, odd Yahoo replies
        st.error("Something went wrong fetching data: %s" % e)
    return None


# ---------------------------------------------------------------- sidebar

st.sidebar.title("📈 Paper Trading Desk")
st.sidebar.caption("Practice only: no real money, no broker.")
mkey = st.sidebar.radio("Market", list(mk.MARKETS), format_func=lambda k: mk.MARKETS[k].name)
M = mk.MARKETS[mkey]
is_open, status_text = mk.market_status(M)
(st.sidebar.success if is_open else st.sidebar.info)(status_text)

book = paper.load()
acct = book[mkey]

with st.sidebar.expander("My risk limits", expanded=False):
    base = acct["start_cash"]
    limits = {
        "max_loss": st.number_input("Max loss per trade (%s)" % M.currency, min_value=1.0,
                                    value=round(base * 0.005, 0), step=100.0 if mkey == "IN" else 10.0,
                                    help="The most you are willing to lose if the stop is hit."),
        "daily_loss": st.number_input("Daily loss limit (%s)" % M.currency, min_value=1.0,
                                      value=round(base * 0.015, 0), step=100.0 if mkey == "IN" else 10.0,
                                      help="Stop trading for the day once you have lost this much."),
        "max_trades": st.number_input("Max new trades per day", min_value=1, value=5, step=1),
        "min_rr": st.number_input("Minimum reward / risk", min_value=0.0, value=1.0, step=0.25,
                                  help="1.0 means the target is at least as far away as the stop."),
        "max_position_pct": st.number_input("Biggest position (% of cash)", min_value=1.0, max_value=100.0,
                                            value=50.0, step=5.0),
        "require_open": st.checkbox("Only allow orders while the market is open", value=False,
                                    help="Untick to practise any time using the latest price."),
    }

st.sidebar.metric("Practice cash", M.money(acct["cash"]))
st.sidebar.caption("Started with %s · %d open position(s)" % (M.money(acct["start_cash"]), len(acct["positions"])))


# ---------------------------------------------------------------- helpers

def candle_chart(df, title, lines=(), height=420):
    fig = go.Figure(go.Candlestick(x=df.index, open=df["open"], high=df["high"], low=df["low"],
                                   close=df["close"], name="price"))
    for y, name, color in lines:
        fig.add_hline(y=y, line_dash="dash", line_color=color, annotation_text="%s %.2f" % (name, y),
                      annotation_position="right")
    fig.update_layout(title=title, height=height, xaxis_rangeslider_visible=False,
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig


def next_monthly_expiry(m, today):
    """India: last Tuesday of the month (NSE's monthly F&O expiry). US: third Friday."""
    def for_month(y, mo):
        if m.key == "IN":
            last = calendar.monthrange(y, mo)[1]
            d = dt.date(y, mo, last)
            return d - dt.timedelta(days=(d.weekday() - 1) % 7)
        d = dt.date(y, mo, 1)
        d += dt.timedelta(days=(4 - d.weekday()) % 7)
        return d + dt.timedelta(weeks=2)
    e = for_month(today.year, today.month)
    if e < today:
        y, mo = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        e = for_month(y, mo)
    return e


def years_to(expiry, today):
    return max((expiry - today).days, 0) / 365.0


def mark_position(pos, m):
    """Current value per unit of a position, or None if no price."""
    got = safe(get_price, pos.get("underlying", pos["symbol"]), m.key)
    if got is None:
        return None
    spot = got[0]
    if pos["kind"] == "stock":
        return spot
    exp = dt.date.fromisoformat(pos["expiry"])
    yrs = years_to(exp, now_local(m).date())
    if pos["kind"] == "future":
        return dv.futures_fair(spot, yrs, pos["rate"])
    return dv.bs(spot, pos["strike"], yrs, pos["vol"], pos["rate"], pos["kind"])["price"]


def confirm_box(key, text):
    """The skill's rule: no order without an explicit yes for this exact order."""
    return st.checkbox(text, key=key)


# ---------------------------------------------------------------- tabs

tab_start, tab_scan, tab_plan, tab_fno, tab_port = st.tabs(
    ["📘 Start here", "🔎 Scanner", "🎯 Day-trade planner", "🧮 Options & Futures", "💼 Paper portfolio"])

# ---------------- Start here
with tab_start:
    st.header("Welcome to your practice trading desk")
    st.write(
        "This app turns the ideas of the free **day-trader skill** into clickable screens, and adds an "
        "**options, futures and derivatives (F&O)** desk. Everything is *paper trading*: you get practice "
        "money (%s for India, %s for the US) and nothing ever reaches a real broker."
        % (mk.MARKETS["IN"].money(paper.START_CASH["IN"]), mk.MARKETS["US"].money(paper.START_CASH["US"])))
    st.markdown(
        """
**The day-trading path (one trade, left to right through the tabs):**

1. **🔎 Scanner**: finds stocks on your watchlist with a chart setup today.
2. **🎯 Day-trade planner**: pick one stock and work through it:
   - *Entry*: waits for the price to close above the first 15 minutes' range (an "opening-range breakout").
   - *Exit plan*: sets your stop (where you give up) and target (where you take profit) **before** you enter.
   - *Time Machine*: replays the rest of the day 10,000 times using the stock's own last 60 days,
     and also tests the same rule on every one of those real days. It tells you the honest odds.
   - *Budget*: works out how many shares so that hitting the stop loses no more than your limit.
   - *Risk check*: PASS or BLOCK against your limits (set them in the sidebar).
   - *Place practice order*: only after you tick "yes" for that exact order.
3. **💼 Paper portfolio**: watch positions, check stops and targets, close trades, see your history.

**The F&O path:** **🧮 Options & Futures** gives you an option chain, a strategy builder with payoff
charts (straddles, spreads, iron condors…), and a futures calculator, all with practice orders.
        """)
    st.warning(
        "**About the numbers.** Stock prices are real (Yahoo Finance, may lag a few minutes). "
        "Option and futures prices are **calculated** with the Black-Scholes formula from the real price and the "
        "stock's own past volatility, because no free live option-chain feed is available. Real F&O prices can "
        "be quite different. Lot sizes change: check nseindia.com. Nothing here is investment advice.")
    st.info("Indian stocks: type the NSE symbol, e.g. RELIANCE, TCS, INFY (the app adds .NS). "
            "Indices: ^NSEI (NIFTY 50), ^NSEBANK (NIFTY BANK).")

# ---------------- Scanner
with tab_scan:
    st.header("🔎 Scanner: which stocks have a setup today?")
    st.caption("Checks each stock's daily chart for the day-trader skill's five setups. "
               "Uses complete trading days only.")
    wl_text = st.text_area("Watchlist (comma separated)", ", ".join(M.watchlist), key="wl_" + mkey)
    if st.button("Run the scan", type="primary"):
        syms = [s.strip() for s in wl_text.replace("\n", ",").split(",") if s.strip()]
        rows, prog = [], st.progress(0.0)
        for i, s in enumerate(syms):
            ysym = M.yahoo(s)
            try:
                d = get_daily(ysym, mkey, "6mo")
                today = now_local(M).date()
                # drop today's bar while the market is still open: it is not a complete day yet
                if is_open and len(d) and d.index[-1].date() == today:
                    d = d.iloc[:-1]
                closes = d["close"].tolist()
                if len(closes) < 30:
                    rows.append({"Symbol": s, "Last close": None, "Setups": "not enough history"})
                else:
                    tags, nums = sg.find_setups(closes)
                    rows.append({"Symbol": s, "Last close": closes[-1],
                                 "Setups": ", ".join(tags) if tags else "-",
                                 "RSI": round(nums["rsi"], 1) if nums["rsi"] is not None else None,
                                 "vs 20-day avg %": round((closes[-1] / nums["ma20"] - 1) * 100, 2),
                                 "15-day run %": round(nums["run_pct"], 2)})
            except Exception as e:
                rows.append({"Symbol": s, "Last close": None, "Setups": "error: %s" % e})
            prog.progress((i + 1) / len(syms))
        st.session_state["scan_" + mkey] = rows
    rows = st.session_state.get("scan_" + mkey)
    if rows:
        df = pd.DataFrame(rows)
        hits = df[~df["Setups"].isin(["-", "not enough history"]) & ~df["Setups"].str.startswith("error")]
        st.subheader("%d of %d stocks have a setup" % (len(hits), len(df)))
        st.dataframe(df, width="stretch", hide_index=True)
        with st.expander("What do the setups mean?"):
            for k, v in sg.SETUP_LABELS.items():
                st.markdown("- **%s**: %s" % (k, v))
        st.caption("A setup is a reason to look closer, not a reason to buy. Take one to the 🎯 planner next.")

# ---------------- Day-trade planner
with tab_plan:
    st.header("🎯 Day-trade planner")
    c1, c2, c3, c4 = st.columns(4)
    sym_in = c1.text_input("Stock symbol", M.watchlist[0], key="plan_sym_" + mkey)
    side = c2.radio("Direction", ["buy", "sell"], horizontal=True,
                    format_func=lambda s: "Buy (expect up)" if s == "buy" else "Sell short (expect down)")
    or_min = c3.selectbox("Opening range", [5, 15, 30], index=1, format_func=lambda x: "first %d minutes" % x)
    flat_min = c4.selectbox("Be out by", [5, 15, 30], index=0,
                            format_func=lambda x: "%d min before the close" % x)
    ysym = M.yahoo(sym_in)
    bars = safe(get_intraday, ysym, mkey) if sym_in else None

    if bars is not None and len(bars):
        n_range = or_min // 5
        n_bars = M.session_bars
        last_bar = n_bars - 1 - flat_min // 5
        latest_day = bars.index[-1].date()
        today_bars = bars[bars.index.date == latest_day]
        filled = mk.fill_session(today_bars, M)
        if filled is None:
            st.warning("Today's first bar is missing from Yahoo's data, so bar times may be off.")
        else:
            today_bars = filled
        past = {d: g for d, g in mk.split_sessions(bars, M).items() if d < latest_day}
        oh, ol = sg.opening_range(today_bars, n_range) if len(today_bars) >= n_range else (None, None)

        st.subheader("1 · Entry")
        trig = sg.orb_trigger(today_bars, n_range, side) if oh is not None else None
        mode = st.radio("How do you want to enter?",
                        ["Opening-range breakout (the skill's rule)", "Enter at the latest price"], horizontal=True)
        entry = k = None
        if oh is None:
            st.info("The opening range for %s is not complete yet. Come back after the first %d minutes."
                    % (latest_day, or_min))
        elif mode.startswith("Opening"):
            if trig:
                entry, k = trig["price"], trig["index"]
                st.success("**Triggered** at %s: the bar closed at %.2f, %s the range (%.2f to %.2f)."
                           % (trig["time"].strftime("%H:%M"), entry, "above" if side == "buy" else "below", ol, oh))
            else:
                st.info("**Waiting**: no 5-minute bar has closed %s the opening range (%.2f to %.2f) yet."
                        % ("above" if side == "buy" else "below", ol, oh))
        else:
            k = len(today_bars) - 1
            entry = round(float(today_bars["close"].iloc[-1]), 2)
            st.write("Entry at the latest 5-minute close: **%.2f** (%s)."
                     % (entry, (today_bars.index[-1] + pd.Timedelta(minutes=5)).strftime("%H:%M")))

        lines = []
        if oh is not None:
            lines += [(oh, "range high", "royalblue"), (ol, "range low", "royalblue")]

        plan = None
        if entry is not None:
            st.subheader("2 · Exit plan (decided before you enter)")
            e1, e2, e3 = st.columns(3)
            stop_rule = e1.selectbox("Stop", list(sg.STOP_RULES), format_func=sg.STOP_RULES.get)
            stop_pct = e2.number_input("Stop % (for the fixed-% rule)", 0.1, 20.0, 1.0, 0.1)
            target_r = e3.number_input("Target, in multiples of the risk (R)", 0.25, 10.0, 1.0, 0.25)
            try:
                plan = sg.exit_plan(entry, side, stop_rule, oh, ol, stop_pct, target_r)
                st.write("Stop **%.2f**, target **%.2f**: risking %.2f a share to make %.2f. Out by %s either way."
                         % (plan["stop"], plan["target"], plan["risk_per_share"], plan["risk_per_share"] * target_r,
                            (dt.datetime.combine(latest_day, M.close) - dt.timedelta(minutes=flat_min)).strftime("%H:%M")))
                lines += [(entry, "entry", "gray"), (plan["stop"], "stop", "crimson"), (plan["target"], "target", "green")]
            except ValueError as e:
                st.error(str(e))

        st.plotly_chart(candle_chart(today_bars, "%s on %s (5-minute bars, %s time)" % (ysym, latest_day, M.tz),
                                     lines), width="stretch")

        if plan:
            st.subheader("3 · Time Machine: the honest odds")
            if k >= last_bar:
                st.info("There are no bars left before your be-out time in this session, so there is nothing to replay. "
                        "Try the breakout mode, or come back during market hours.")
            elif len(past) < 20:
                st.warning("Only %d full past sessions in the data; the Time Machine needs at least 20." % len(past))
            else:
                t1, t2 = st.columns(2)
                replays = t1.select_slider("Replays", [1000, 5000, 10000, 20000], value=10000)
                seed = t2.number_input("Random seed (same seed = same result)", 0, 10_000, 19)
                with st.spinner("Replaying the rest of the session %d times…" % replays):
                    tm = sg.time_machine(past, entry, plan["stop"], plan["target"], k, last_bar, side, replays, seed)
                    hist = sg.history_replay(past, n_range, stop_rule, stop_pct, target_r, last_bar, side)
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Target hit first", "%.1f%%" % (100 * tm["p_target"]))
                m2.metric("Stop hit first", "%.1f%%" % (100 * tm["p_stop"]))
                m3.metric("Neither by the end", "%.1f%%" % (100 * tm["p_neither"]))
                m4.metric("Average result", "%+.2f R" % tm["avg_R"])
                st.markdown("**Verdict: %s** Price at your be-out time: median %.2f, 90%% of replays between %.2f and %.2f."
                            % (tm["verdict"], tm["median_close"], tm["p5_close"], tm["p95_close"]))
                times = [today_bars.index[0] + pd.Timedelta(minutes=5 * (i + 1)) for i in range(k, last_bar + 1)]
                fig = go.Figure()
                for col in range(tm["sample_paths"].shape[1]):
                    fig.add_trace(go.Scatter(x=times, y=tm["sample_paths"][:, col], mode="lines",
                                             line=dict(width=0.6, color="rgba(120,120,120,0.25)"), showlegend=False,
                                             hoverinfo="skip"))
                b = tm["bands"]
                fig.add_trace(go.Scatter(x=times, y=b[0], line=dict(width=0), showlegend=False, hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=times, y=b[4], fill="tonexty", fillcolor="rgba(65,105,225,0.15)",
                                         line=dict(width=0), name="5th to 95th percentile"))
                fig.add_trace(go.Scatter(x=times, y=b[2], line=dict(color="royalblue", width=2), name="median"))
                fig.add_hline(y=plan["stop"], line_color="crimson", line_dash="dash", annotation_text="stop")
                fig.add_hline(y=plan["target"], line_color="green", line_dash="dash", annotation_text="target")
                fig.update_layout(height=380, title="Fan of replayed paths", margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig, width="stretch")
                if hist:
                    hd = pd.DataFrame(hist)
                    st.markdown("**The same rule on the last %d real sessions:** it fired %d times: "
                                "%d hit the target, %d the stop, %d neither. Average %+.2f R."
                                % (len(past), len(hd), (hd.outcome == "target").sum(), (hd.outcome == "stop").sum(),
                                   (hd.outcome == "close").sum(), hd.R.mean()))
                    with st.expander("See every past trade"):
                        st.dataframe(hd, width="stretch", hide_index=True)
                st.caption("Built from the stock's own last 60 days. It is not a prediction: news, results and "
                           "events can do what the last 60 days never did.")

            st.subheader("4 · Budget: how many shares?")
            got = safe(get_price, ysym, mkey)
            if got:
                live, when = got
                qty = sg.size_position(entry, plan["stop"], limits["max_loss"], acct["cash"],
                                       limits["max_position_pct"])
                qty = st.number_input("Shares", min_value=0, value=int(qty), step=1,
                                      help="Suggested so that a fill at the stop loses at most your max loss per trade.")
                st.write("Latest price **%.2f** (%s). Cost about **%s**. Loss if the stop fills: **%s**. "
                         "Gain at the target: **%s**."
                         % (live, when.strftime("%d %b %H:%M") if when else "time unknown", M.money(qty * live),
                            M.money(qty * abs(live - plan["stop"])), M.money(qty * abs(plan["target"] - live))))

                st.subheader("5 · Risk check")
                realised, opened = paper.today_stats(acct, now_local(M).date())
                order = {"qty": qty, "entry": live, "stop": plan["stop"], "target": plan["target"], "side": side}
                checks = sg.risk_check(order, limits, {"cash": acct["cash"], "realized_today": realised,
                                                       "trades_today": opened, "market_open": is_open})
                long = side == "buy"
                checks.append(("Price is still between the stop and the target",
                               (plan["stop"] < live < plan["target"]) if long else (plan["target"] < live < plan["stop"]),
                               "latest %.2f" % live))
                st.dataframe(pd.DataFrame([{"Rule": r, "Result": "✅ PASS" if ok else "⛔ BLOCK", "Detail": d}
                                           for r, ok, d in checks]), width="stretch", hide_index=True)
                passed = all(ok for _, ok, _ in checks)

                st.subheader("6 · Place the practice order")
                if not passed:
                    st.error("BLOCKED: fix the rules marked ⛔ above first.")
                else:
                    ticket = ("%s %d %s at about %.2f · stop-loss %.2f · take-profit %.2f · max loss %s"
                              % ("BUY" if long else "SELL SHORT", qty, ysym, live, plan["stop"], plan["target"],
                                 M.money(qty * abs(live - plan["stop"]))))
                    st.code(ticket, language=None)
                    yes = confirm_box("yes_stock_" + mkey, "Yes, place this exact practice order")
                    if st.button("Place practice order", type="primary", disabled=not yes):
                        try:
                            paper.open_position(acct, kind="stock", symbol=ysym, side=side, qty=qty, price=live,
                                                blocked=qty * live, now=now_local(M), stop=plan["stop"],
                                                target=plan["target"])
                            paper.save(book)
                            st.toast("Filled (practice): %s. See it in 💼 Paper portfolio." % ticket, icon="✅")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))

# ---------------- Options & Futures
with tab_fno:
    st.header("🧮 Options, Futures & Derivatives")
    st.caption("Prices below are calculated (Black-Scholes and cost of carry) from the real current price, "
               "not live exchange quotes.")
    f1, f2, f3 = st.columns([2, 2, 1])
    choices = list(M.indices) + ["A stock…"]
    pick = f1.selectbox("Underlying", choices)
    if pick == "A stock…":
        under = M.yahoo(f2.text_input("Stock symbol", M.watchlist[0], key="fno_sym_" + mkey))
        default_lot = 100 if mkey == "US" else 1
        f2.caption(M.stock_lot_note)
    else:
        under, default_lot = M.indices[pick]
        f2.text_input("Yahoo symbol", under, disabled=True)
    lot = int(f3.number_input("Lot size", min_value=1, value=int(default_lot), step=1,
                              help="Units in one contract. NSE changes these; check nseindia.com."))

    d1y = safe(get_daily, under, mkey, "1y")
    got = safe(get_price, under, mkey)
    if d1y is not None and got is not None and len(d1y) > 70:
        spot = got[0]
        today = now_local(M).date()
        hv30, hv90 = dv.hist_vol(d1y["close"], 30), dv.hist_vol(d1y["close"], 90)
        g1, g2, g3, g4 = st.columns(4)
        g1.metric("Spot price", "%.2f" % spot)
        g2.metric("Past volatility (30 days)", "%.1f%%" % (100 * hv30))
        g3.metric("Past volatility (90 days)", "%.1f%%" % (100 * hv90))
        vol = g4.number_input("Volatility to use (%)", 1.0, 300.0, round(100 * hv30, 1), 0.5,
                              help="Option prices depend heavily on this. Higher = pricier options.") / 100
        h1, h2 = st.columns(2)
        expiry = h1.date_input("Expiry date", next_monthly_expiry(M, today), min_value=today,
                               help="India: monthly F&O contracts expire on the last Tuesday. US: third Friday.")
        rate = h2.number_input("Interest rate (% a year)", 0.0, 20.0, M.risk_free * 100, 0.25) / 100
        yrs = years_to(expiry, today)
        st.caption("%d days to expiry." % (expiry - today).days)

        sub_chain, sub_strat, sub_fut = st.tabs(["Option chain", "Strategy builder", "Futures"])

        with sub_chain:
            ch = pd.DataFrame(dv.chain(spot, yrs, vol, rate))
            atm = dv.atm_strike(spot)
            st.dataframe(ch.style.format({c: "{:.2f}" for c in ch.columns if c != "Strike"} | {"Strike": "{:g}"})
                         .apply(lambda r: ["background-color: rgba(65,105,225,0.15)" if r["Strike"] == atm else ""
                                           for _ in r], axis=1),
                         width="stretch", hide_index=True)
            with st.expander("What do these columns mean?"):
                st.markdown(
                    "- **Call**: the right to *buy* at the strike. Gains when the price rises.\n"
                    "- **Put**: the right to *sell* at the strike. Gains when the price falls.\n"
                    "- **Price**: per unit; one contract costs price × lot size (%d).\n"
                    "- **Delta**: how much the option moves for a 1-point move in the stock.\n"
                    "- **Gamma**: how fast delta changes.\n"
                    "- **Theta**: how much value the option loses per day just from time passing.\n"
                    "- **Vega**: change in price for 1%% more volatility.\n"
                    "- The highlighted row is *at the money* (strike closest to today's price)." % lot)

        with sub_strat:
            s1, s2 = st.columns([3, 1])
            preset = s1.selectbox("Strategy", list(dv.STRATEGIES))
            lots = int(s2.number_input("Lots", 1, 1000, 1))
            step = dv.strike_step(spot)
            base_rows = []
            for kind, sd, off in dv.STRATEGIES[preset]:
                base_rows.append({"Type": kind, "Side": sd,
                                  "Strike": float(dv.atm_strike(spot) + off * step) if kind in ("call", "put") else None,
                                  "Lots": lots})
            legs_df = st.data_editor(pd.DataFrame(base_rows), key="legs_%s_%s_%s_%d" % (mkey, under, preset, lots),
                                     column_config={
                                         "Type": st.column_config.SelectboxColumn(options=["call", "put", "future", "stock"]),
                                         "Side": st.column_config.SelectboxColumn(options=["buy", "sell"]),
                                         "Strike": st.column_config.NumberColumn(step=step),
                                         "Lots": st.column_config.NumberColumn(min_value=1, step=1)},
                                     num_rows="dynamic", width="stretch", hide_index=True)
            legs = []
            for _, r in legs_df.dropna(subset=["Type", "Side"]).iterrows():
                kind = r["Type"]
                if kind in ("call", "put") and (pd.isna(r["Strike"]) or r["Strike"] <= 0):
                    continue
                leg = {"kind": kind, "side": r["Side"], "strike": float(r["Strike"]) if kind in ("call", "put") else None,
                       "qty": int(r["Lots"] or 1) * lot}
                leg["premium"] = dv.leg_value(leg, spot, yrs, vol, rate)
                g = dv.bs(spot, leg["strike"], yrs, vol, rate, kind) if kind in ("call", "put") else \
                    {"delta": 1.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
                leg["greeks"] = g
                legs.append(leg)

            if legs:
                prices = np.linspace(spot * 0.8, spot * 1.2, 241)
                exp_pnl, now_pnl = dv.payoff(legs, prices, yrs, vol, rate)
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=prices, y=exp_pnl, name="At expiry", line=dict(color="royalblue", width=2)))
                fig.add_trace(go.Scatter(x=prices, y=now_pnl, name="Today (theoretical)",
                                         line=dict(color="orange", dash="dot")))
                fig.add_hline(y=0, line_color="gray")
                fig.add_vline(x=spot, line_color="gray", line_dash="dash", annotation_text="spot")
                fig.update_layout(height=400, title="Profit / loss of the whole strategy",
                                  xaxis_title="Underlying price", yaxis_title="P&L (%s)" % M.currency,
                                  margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig, width="stretch")
                net = sum((-1 if l["side"] == "buy" else 1) * l["premium"] * l["qty"]
                          for l in legs if l["kind"] in ("call", "put"))
                bes = dv.breakevens(prices, exp_pnl)
                sgn = lambda l: 1 if l["side"] == "buy" else -1  # noqa: E731
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Premium " + ("received" if net >= 0 else "paid"), M.money(abs(net)))
                k2.metric("Best case (±20%)", M.money(exp_pnl.max()))
                k3.metric("Worst case (±20%)", M.money(exp_pnl.min()))
                k4.metric("Break-even", ", ".join("%.2f" % b for b in bes) or "none in range")
                gsum = {g: sum(sgn(l) * l["qty"] * l["greeks"][g] for l in legs) for g in ("delta", "gamma", "theta", "vega")}
                st.caption("Whole position: delta %.2f · gamma %.4f · theta %s a day · vega %s per 1%% vol"
                           % (gsum["delta"], gsum["gamma"], M.money(gsum["theta"]), M.money(gsum["vega"])))
                if any(l["side"] == "sell" and l["kind"] in ("call", "put") for l in legs):
                    st.warning("This strategy *sells* options. Selling can lose much more than the premium you collect.")

                # practice order
                blocked_total = 0.0
                for l in legs:
                    if l["kind"] == "stock":
                        l["blocked"] = l["premium"] * l["qty"]
                    elif l["kind"] == "future" or l["side"] == "sell":
                        l["blocked"] = spot * l["qty"] * M.margin_pct / 100
                    else:
                        l["blocked"] = l["premium"] * l["qty"]
                    blocked_total += l["blocked"]
                st.write("Practice cash this needs (cost + margin at %.0f%% of the value of sold options and futures): **%s** "
                         "· you have %s." % (M.margin_pct, M.money(blocked_total), M.money(acct["cash"])))
                yes = confirm_box("yes_fno_" + mkey, "Yes, place these %d legs as a practice order" % len(legs))
                if st.button("Place practice F&O order", type="primary", disabled=not yes):
                    if blocked_total > acct["cash"]:
                        st.error("Not enough practice cash.")
                    else:
                        now = now_local(M)
                        for l in legs:
                            extra = {"underlying": under, "rate": rate, "vol": vol, "lot": lot}
                            if l["kind"] != "stock":
                                extra["expiry"] = expiry.isoformat()
                            if l["kind"] in ("call", "put"):
                                extra["strike"] = l["strike"]
                            paper.open_position(acct, kind=l["kind"], symbol=under, side=l["side"], qty=l["qty"],
                                                price=l["premium"], blocked=l["blocked"], now=now, **extra)
                        paper.save(book)
                        st.toast("Practice order filled: %d legs. See 💼 Paper portfolio." % len(legs), icon="✅")
                        st.rerun()

        with sub_fut:
            fair = dv.futures_fair(spot, yrs, rate)
            u1, u2, u3 = st.columns(3)
            u1.metric("Futures fair price", "%.2f" % fair, "%+.2f basis" % (fair - spot))
            u2.metric("One lot is worth", M.money(fair * lot))
            u3.metric("Margin for one lot (≈%.0f%%)" % M.margin_pct, M.money(fair * lot * M.margin_pct / 100))
            st.write("A **future** is an agreement to buy or sell at today's futures price on the expiry date. "
                     "You only put up the margin, so profits and losses are magnified: a 1%% move is **%s** per lot, "
                     "which is %.1f%% of your margin." % (M.money(fair * lot * 0.01), 100 / M.margin_pct))
            moves = [-5, -3, -2, -1, 0, 1, 2, 3, 5]
            st.dataframe(pd.DataFrame({"Price move %": moves,
                                       "Long 1 lot P&L": [M.money(fair * lot * m / 100) for m in moves],
                                       "Short 1 lot P&L": [M.money(-fair * lot * m / 100) for m in moves]}),
                         width="stretch", hide_index=True)

# ---------------- Portfolio
with tab_port:
    st.header("💼 Paper portfolio (%s)" % M.name)
    positions = acct["positions"]
    now = now_local(M)
    rows, marks = [], {}
    for p in positions:
        m_ = mark_position(p, M)
        marks[p["id"]] = m_
        rows.append({"ID": p["id"], "Position": paper.label(p), "Type": p["kind"], "Side": p["side"], "Qty": p["qty"],
                     "Entry": round(p["entry"], 2), "Now": round(m_, 2) if m_ is not None else None,
                     "P&L": round(paper.pnl(p, m_), 2) if m_ is not None else None,
                     "Stop": p.get("stop"), "Target": p.get("target"), "Opened": p["opened"]})
    unreal = sum(r["P&L"] or 0 for r in rows)
    equity = acct["cash"] + sum(p["blocked"] for p in positions) + unreal
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Account value", M.money(equity), M.money(equity - acct["start_cash"]))
    a2.metric("Free cash", M.money(acct["cash"]))
    a3.metric("Open P&L", M.money(unreal))
    realised, opened = paper.today_stats(acct, now.date())
    a4.metric("Realised today", M.money(realised), "%d trade(s) opened today" % opened, delta_color="off")

    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        b1, b2 = st.columns(2)
        if b1.button("Check stops, targets & expiries", help="Closes stock trades that crossed their stop or target, "
                                                              "and settles expired F&O contracts."):
            msgs = []
            for p in list(positions):
                m_ = marks.get(p["id"])
                if m_ is None:
                    continue
                long = p["side"] == "buy"
                reason = None
                if p["kind"] == "stock" and p.get("stop") is not None:
                    if (m_ <= p["stop"]) if long else (m_ >= p["stop"]):
                        reason = "stop hit"
                    elif (m_ >= p["target"]) if long else (m_ <= p["target"]):
                        reason = "target hit"
                if p.get("expiry") and dt.date.fromisoformat(p["expiry"]) < now.date():
                    reason = "expired"
                if reason:
                    g = paper.close_position(acct, p["id"], m_, now, reason)
                    msgs.append("%s: %s, P&L %s" % (paper.label(p), reason, M.money(g)))
            paper.save(book)
            st.toast("\n".join(msgs) if msgs else "Nothing hit its stop or target; nothing expired.")
            st.rerun()
        to_close = b2.selectbox("Close a position", [r["ID"] for r in rows],
                                format_func=lambda i: next(r["Position"] + " (" + i + ")" for r in rows if r["ID"] == i))
        if b2.button("Close it at the current price"):
            if marks.get(to_close) is None:
                st.error("No current price, try again in a minute.")
            else:
                g = paper.close_position(acct, to_close, marks[to_close], now)
                paper.save(book)
                st.toast("Closed, P&L %s." % M.money(g), icon="✅")
                st.rerun()
    else:
        st.info("No open positions. Plan a trade in 🎯 or build a strategy in 🧮.")

    st.subheader("Trade history")
    if acct["log"]:
        st.dataframe(pd.DataFrame(acct["log"][::-1]), width="stretch", hide_index=True)
    else:
        st.caption("No trades yet.")

    with st.expander("Reset this practice account"):
        new_cash = st.number_input("Starting cash", min_value=100.0, value=float(paper.START_CASH[mkey]), step=1000.0)
        if st.checkbox("Yes, delete all %s positions and history" % M.name) and st.button("Reset"):
            paper.reset(book, mkey, new_cash)
            paper.save(book)
            st.rerun()
