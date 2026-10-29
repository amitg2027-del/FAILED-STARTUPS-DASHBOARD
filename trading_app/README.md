# Paper Trading Desk

A **practice-only** trading app for **India (NSE)** and the **US**, with:

- **Day trading**, built on the ideas of the free
  [day-trader skill](https://github.com/Jakeschincariol/day-trader-skill) (MIT licence):
  chart scanner → opening-range entry → exit plan → Time Machine odds → position sizing →
  risk check → practice order.
- **Options, futures & derivatives (F&O)**: option chain with Greeks, a strategy builder
  with payoff charts (spreads, straddles, strangles, iron condors, covered calls…), and a
  futures calculator.
- **A paper portfolio**: virtual cash (₹10,00,000 for India, $10,000 for the US),
  open positions, profit and loss, and trade history.

No real money is used and no broker is connected. Nothing here is investment advice.

This app is separate from the startups dashboard in the folder above. It has its own
files and its own `requirements.txt`.

## Where the numbers come from

| What | Source | Real or calculated? |
| --- | --- | --- |
| Stock and index prices, 5-minute and daily charts | Yahoo Finance (free, may lag a few minutes) | **Real** |
| Option prices and Greeks | Black-Scholes formula, using the real price and the stock's past volatility | **Calculated** |
| Futures prices | Cost of carry: price × e^(interest rate × time) | **Calculated** |

There is no free live option-chain feed this app can use, so real F&O prices on NSE or
US exchanges **will differ**, sometimes a lot (around results, budget day, or big news).
NSE lot sizes change from time to time: check [nseindia.com](https://www.nseindia.com)
and type the right one in the app.

## How to run it on your computer (Windows, step by step)

You only need to do steps 1–4 once.

1. **Install Python.** Download it from https://www.python.org/downloads/ and run the
   installer. On the first screen, **tick "Add python.exe to PATH"**.
2. **Get this project.** On the GitHub page, click the green **Code** button, then
   **Download ZIP**. Unzip it, for example to your Desktop.
3. **Open PowerShell in the project folder.** Open the unzipped folder in File Explorer,
   click the address bar, type `powershell` and press Enter.
4. **Install the app's packages.** Copy and paste these one at a time and press Enter:

   ```powershell
   python -m venv .venv
   ```

   ```powershell
   .\.venv\Scripts\activate
   ```

   ```powershell
   pip install -r trading_app/requirements.txt
   ```

5. **Start the app** (every time you want to use it, after `.\.venv\Scripts\activate`):

   ```powershell
   streamlit run trading_app/app.py
   ```

   Your browser opens at http://localhost:8501. To stop the app, go back to PowerShell
   and press `Ctrl + C`.

## How to use it

1. Pick **India** or **US** in the left sidebar. Set **My risk limits** there too.
2. **🔎 Scanner**: press *Run the scan* to see which watchlist stocks have a chart setup.
3. **🎯 Day-trade planner**: type a symbol (e.g. `RELIANCE`, `TCS`, `TSLA`) and go down
   the page: entry → exit plan → Time Machine → budget → risk check → tick *Yes* → place
   the practice order.
4. **🧮 Options & Futures**: pick NIFTY 50, NIFTY BANK or a stock, choose an expiry date,
   then use the option chain, the strategy builder or the futures calculator.
5. **💼 Paper portfolio**: check stops and targets, close positions, see your history,
   or reset the account.

Your practice account is saved in `trading_app/data/paper_account.json` on your
computer. That file is not uploaded to GitHub.

## Tests

```powershell
python -m unittest discover -s trading_app/tests
```
