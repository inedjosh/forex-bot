# The Complete Step-by-Step Guide

Written for someone who is **not** a programmer or a trader. Follow it top to bottom.
Every command is copy-paste. When you see a box like this:

```bash
some command here
```

…it means: type (or paste) that line into your **Terminal** and press Enter.

---

## Table of contents

1. [The big picture (read this first)](#1-the-big-picture)
2. [The safe order — never skip a step](#2-the-safe-order)
3. [Part A — Run it on your own computer](#3-part-a--run-it-on-your-own-computer)
4. [Part B — Backtesting (testing on past prices)](#4-part-b--backtesting)
5. [Part C — Host it on a VPS (a computer in the cloud that never sleeps)](#5-part-c--host-it-on-a-vps)
6. [Part D — Connect to a real broker (practice money first)](#6-part-d--connect-to-a-real-broker)
7. [Part E — Switch to real money](#7-part-e--switch-to-real-money)
8. [Part F — Watch it (alerts & logs)](#8-part-f--watch-it)
9. [Safety checklist](#9-safety-checklist)
9b. [Running it as a business (operator guide)](#9b-running-it-as-a-business-operator-guide)
10. [Plain-English glossary](#10-plain-english-glossary)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. The big picture

Think of three separate things:

| Thing | What it is | Money at risk? |
|---|---|---|
| **The simulator** | Replays past prices to test your rules | ❌ None. Totally safe. |
| **The practice account (demo)** | Live prices, but fake money, at a real broker | ❌ None. Safe. |
| **The live account** | Real prices, **real money** | ✅ **Yes. Real.** |

The bot is the **same program** in all three — only what it's *connected to* changes.
You move from left to right, and **only** when the previous stage has proven itself.

**Two facts about your situation:**
- You're in **Nigeria**, so OANDA and (likely) Deriv won't accept you. You'll use a
  **MetaTrader 5 (MT5)** broker (IC Markets, Exness, XM, FP Markets, Pepperstone).
- MT5's automation only runs on **Windows**. Your Mac is fine for the simulator and
  backtesting, but for real/live trading you'll rent a small **Windows computer in the
  cloud (a VPS)** that stays on 24/7. (See Part C.)

---

## 2. The safe order

Do these in order. Each stage must look good before the next.

```
1. Run on your Mac           →  (Part A)   no money, learn the tool
2. Backtest on past data     →  (Part B)   does the formula have an edge?
3. Rent a Windows VPS        →  (Part C)   a cloud PC that never sleeps
4. Open an MT5 DEMO account  →  (Part D)   fake money, real live prices
5. Run on DEMO for weeks     →  (Part D)   do live results match the backtest?
6. Only then: real money     →  (Part E)   start tiny
```

⛔ **If you skip to step 6, you will very likely lose money.** There is no shortcut.

---

## 3. Part A — Run it on your own computer

You only do this setup **once** per computer.

### A1. Install Python (the engine the bot runs on)

- **Mac:** Open the **Terminal** app (press `Cmd+Space`, type "Terminal", Enter). Then:
  ```bash
  python3 --version
  ```
  If it prints a number like `Python 3.14`, you're done. If not, download Python from
  <https://www.python.org/downloads/> and install it, then re-check.

### A2. Get into the project folder

```bash
cd /Users/nwong/Documents/forex-bot
```

(That's already where your project lives.)

### A3. Create a private workspace and install the parts (one time)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- Line 1 makes a private box called `.venv` so this project's parts don't mess with your
  computer.
- Line 2 "steps into" that box. **You must run this line every time you open a new
  Terminal** before using the bot. You'll know it worked when your prompt shows `(.venv)`.
- Line 3 installs the helpers (charts, data download, the web page).

### A4. Open the dashboard (the easy way to use everything)

```bash
python scripts/run_ui.py --port 5055
```

Now open your web browser and go to:

```
http://127.0.0.1:5055
```

You'll see the **Forex Bot** dashboard with a "🧪 Practice mode" badge. That's it —
you're running.

> **Why `--port 5055`?** On Mac, port 5000 is sometimes used by AirPlay. 5055 avoids the
> clash. Any number works.

**To stop the dashboard:** go back to the Terminal and press `Ctrl+C`.

---

## 4. Part B — Backtesting

Backtesting = "if I had traded these rules on the last few years of prices, what would
have happened?" No money involved.

### The easy way (dashboard)

In the browser dashboard:

1. **Step 1 – Pick what to test.** Choose a pair (e.g. `EURUSD`), a timeframe (`1d` is a
   good start), history (`10y`), and click **Download**. Wait for the green "✅ Downloaded"
   message.
2. **Step 2 – Run the test.** Make sure the file you just downloaded is selected, then
   click the big **▶ Run the Test** button.
3. **Read the result.** You'll get a plain-English verdict ("✅ made money" / "❌ lost
   money"), six numbers (hover the ⓘ icons for what each means), and a chart of the
   account balance over time.
4. **Step 3 – Auto-improve (optional).** Click **Find Best Settings** to let the computer
   try many combinations. Click **Use the best settings**, then **Run the Test** again.
5. **Step 4 – Your formula.** Pick a **ready-made recipe** or adjust the boxes (see below).

### The formula in dead-simple terms

Imagine two lines drawn over the price:
- a **fast line** that hugs recent prices closely, and
- a **slow line** that moves more gently.

The whole idea:
> **When the fast line crosses ABOVE the slow line → the price is turning up → BUY.**
> **When the fast line crosses BELOW the slow line → the price is turning down → SELL.**

Everything else is just safety and fine-tuning:
- **Momentum filter** = "don't jump in if the move already looks exhausted."
- **Safety stop** = "if I'm wrong, automatically get me out after a small loss."
- **Reward vs. risk** = "aim to win more than I risk, e.g. risk $1 to try to make $2."
- **Risk per trade** = "never put more than ~1% of the account on one trade."

That's the entire formula. You don't need to know anything else to use it.

### Ready-made recipes (the easiest way)

In **Step 4**, the **🍽️ Start from a ready-made recipe** dropdown fills every box for you:

| Recipe | What it does | Good for |
|---|---|---|
| **Slow & Steady** | Trades rarely, follows big trends | First-timers |
| **Trend Follower** | Rides medium trends (tuned daily setup) | A solid default |
| **Cautious** | Very small risk, tight fixed stop | Nervous beginners |
| **Active** | Trades more often, shorter trends | Seeing lots of activity |

Pick one → press **Run the Test**. That's it.

### The command-line way (same thing, more control)

```bash
# Download real, free data (no account needed)
python scripts/fetch_free_data.py --pair EURUSD --interval 1d --period 10y

# Backtest and save a chart
python scripts/run_backtest.py --csv data/EURUSD_1d.csv --plot equity.png

# Find the best settings
python scripts/optimize.py --csv data/EURUSD_1d.csv --top 10

# The HONEST test: optimise on old data, check on unseen data
python scripts/walkforward.py --csv data/EURUSD_1d.csv

# Test one setting across many pairs at once
python scripts/run_multi.py --csv data/EURUSD_1d.csv data/GBPUSD_1d.csv data/USDJPY_1d.csv
```

> ### 📌 The most important rule of backtesting
> A great **backtest** number is easy to fake by over-tweaking (this is called
> "curve-fitting"). The number that actually predicts the future is the **walk-forward**
> result (`walkforward.py`). **Trust that one.** If walk-forward looks bad, the strategy
> has no real edge — no matter how pretty the plain backtest looks.

> ### ✏️ Setting YOUR formula (no code)
> Everything about the formula is a **simple form** in dashboard **Step 4 · Your formula** —
> no coding. You choose:
> - **Trend:** line type (EMA/SMA) and the fast/slow lengths.
> - **Momentum filter:** turn it on/off and set its bounds.
> - **Safety stop:** volatility-based or a fixed %, and how far.
> - **Target & risk:** reward-vs-risk and how much to risk per trade.
>
> Change any box, press **Run the Test**, and see the effect. Nothing you type here can
> break the program.

### How to read your results (a worked example)

Say you run a test and see this:

```
✅ On this past data, these rules made money (+$2,335).
Profit / Loss: +2,335    Return: +23.4%    Trades: 53
Win rate: 42%    Profit factor: 1.69    Worst dip: 15%
```

Here's what a beginner should take from each number:

- **Return +23.4%** — over the whole test period the pretend $10,000 grew to ~$12,335.
- **Trades: 53** — it made 53 round-trip trades. (Too few, like 5, means the result is
  basically luck. 30+ is more meaningful.)
- **Win rate 42%** — it *lost* more often than it won! That's fine here, because…
- **Profit factor 1.69** — for every $1 it lost, it made $1.69. Above 1.0 = profitable.
  This is the single most useful number. **A low win rate can still be very profitable**
  if the wins are bigger than the losses — which is exactly what's happening.
- **Worst dip 15%** — at the scariest moment the account was 15% below its high point.
  Ask yourself: "Could I stay calm watching my money drop 15%?" If not, choose a more
  cautious recipe.

**Rule of thumb for "is this any good?":** Profit factor above ~1.3, at least ~30 trades,
and a worst dip you could stomach. Then confirm with walk-forward (below).

### Worked examples (copy-paste these)

**Example 1 — A complete beginner's first test (dashboard):**
1. Open the dashboard. Step 1: pick `EURUSD`, `1d`, `10y` → **Download**.
2. Step 4: choose the **Trend Follower** recipe.
3. Step 2: press **▶ Run the Test**. Read the verdict and the chart.

**Example 2 — "Make it more cautious":** In Step 4 pick the **Cautious** recipe (or set
*Risk per trade* to `0.5` and *Stop-loss style* to `percent`), then Run the Test again.
Notice the "Worst dip" number get smaller.

**Example 3 — The same test on the command line:**
```bash
python scripts/fetch_free_data.py --pair EURUSD --interval 1d --period 10y
python scripts/run_backtest.py --csv data/EURUSD_1d.csv --plot equity.png
```

**Example 4 — Does it work on OTHER pairs? (the generalisation test):**
```bash
python scripts/fetch_free_data.py --pair GBPUSD --interval 1d --period 10y
python scripts/fetch_free_data.py --pair USDJPY --interval 1d --period 10y
python scripts/run_multi.py --csv data/EURUSD_1d.csv data/GBPUSD_1d.csv data/USDJPY_1d.csv
```
If it's profitable on several pairs with the *same* settings, that's a good sign it's real.

**Example 5 — The honest, curve-fit-proof test:**
```bash
python scripts/walkforward.py --csv data/EURUSD_1d.csv
```
Look at the **OOS (out-of-sample) return**. If it's positive, the edge is more believable.
If it's negative while the plain backtest looked great, the settings were "too perfect"
for the past and won't survive the future.

**Example 6 — Let the computer suggest settings:**
```bash
python scripts/optimize.py --csv data/EURUSD_1d.csv --top 10
```
It prints the best-scoring settings. Put the winner in Step 4 (or `.env`), then **always**
re-run Example 5 to sanity-check it.

---

## 5. Part C — Host it on a VPS

This is the most detailed part, because hosting is where beginners get stuck. Take it
slowly; every click is spelled out.

### C0. What is a VPS, and why do I need one?

A **VPS** ("Virtual Private Server") is a computer you rent in a data centre that stays
**on 24 hours a day, 7 days a week**. Think of it as a second PC living in the cloud that
never sleeps and never loses power or internet.

**Why you need it:** a trading bot must watch the market and place trades even while you
sleep, travel, or have a power cut. Your Mac can't do that (it turns off, closes, loses
Wi-Fi). The VPS can.

> **Analogy:** your Mac is your home kitchen (great for practising recipes). The VPS is a
> restaurant kitchen that runs around the clock. You develop the recipe at home, then run
> the real service in the always-open kitchen.

**Do I need it for backtesting?** No. Backtesting and the dashboard run fine on your Mac.
You only need a VPS for **live/demo trading that runs unattended**. Don't rent one until
you're at Part D.

### C1. Which VPS should I get?

- **For live trading with MT5 you need a WINDOWS VPS.** This is because MT5's automation
  only works on Windows. This is the one that matters for you.
- Ignore Linux VPS options — they're cheaper but won't run MT5's Python automation.

**What to order:**

| Spec | Get at least | Why |
|---|---|---|
| Operating system | **Windows Server 2019/2022** | MT5 automation needs Windows |
| RAM (memory) | **2 GB** (4 GB is comfortable) | MT5 + bot + Windows |
| CPU | 2 vCPUs | smooth enough |
| Disk | 40–50 GB | Windows is chunky |
| Location | Near your broker's servers (often London/NY) | faster order fills |

**Cost:** about **$8–25/month.**

**Where to get one (examples — check current reviews yourself):**
- **ForexVPS.net, Cheap-forex-vps, or "MT5 VPS"** specialists — often come with MT5
  pre-installed and are tuned for trading. Easiest for beginners.
- **General clouds:** Contabo (cheap), Vultr, Kamatera, or AWS Lightsail (pick the
  "Windows" plan). Many brokers (e.g. some MT5 brokers) also offer a **free VPS** if you
  keep a minimum balance — ask your broker.

### C2. Rent it and write down 3 things

1. Sign up with a provider, choose a **Windows Server** plan, and pay.
2. After a few minutes they'll email/show you a control panel with **three details** —
   copy them somewhere safe:
   - **IP address** — looks like `102.55.12.9` (this is the VPS's "phone number")
   - **Username** — usually `Administrator`
   - **Password** — a long random string

> ⚠️ Treat these like bank details. Anyone with them can control the VPS.

### C3. Connect to the VPS from your Mac (Remote Desktop)

You control a Windows VPS by seeing its screen inside a window on your Mac. This is called
**Remote Desktop (RDP)**.

1. On your Mac, open the **App Store**, search **"Windows App"** (it used to be called
   *Microsoft Remote Desktop*) and install it (free).
2. Open **Windows App** → click **+** → **Add PC**.
3. In **PC name**, paste the VPS **IP address** (e.g. `102.55.12.9`). Click **Add**.
4. Double-click the PC tile. When asked, type the **Username** (`Administrator`) and
   **Password**. Tick "remember" if you like. Click **Continue** if it warns about a
   certificate (that's normal for a fresh VPS).
5. After a few seconds a **Windows desktop appears in a window on your Mac.** 🎉
   **From now on, everything you do happens *on the VPS*, not your Mac.**

> **Tip:** You can safely close this Remote Desktop window later — the VPS keeps running.
> Reconnect any time to check on the bot.

### C4. Install the bot on the VPS — step by step

Do all of this **inside the Windows screen** you just connected to.

**Step 1 — Install Python.**
1. Open the **Edge** browser (blue "e" on the VPS taskbar).
2. Go to <https://www.python.org/downloads/> and click the big **Download Python** button.
3. Run the downloaded file. On the first screen, **tick the box "Add python.exe to PATH"**
   (bottom of the window — easy to miss and important), then click **Install Now**.
4. When done, click **Close**.

**Step 2 — Get the bot's files onto the VPS.** Pick the easiest for you:
- **Copy-paste (simplest):** On your Mac, right-click the `forex-bot` folder → Compress →
  you get `forex-bot.zip`. In the Remote Desktop window, you can often **drag-and-drop or
  copy-paste** that zip onto the VPS desktop. Then right-click it on the VPS → **Extract
  All** → move the folder to `C:\forex-bot`.
- **Or via cloud:** upload the zip to Google Drive/Dropbox on your Mac, open the same link
  in Edge on the VPS, download, extract to `C:\forex-bot`.
- **Or via GitHub** (if you use it): `git clone` your repo into `C:\forex-bot`.

**Step 3 — Install the bot's parts.**
1. On the VPS, click **Start**, type **cmd**, press **Enter** — a black **Command Prompt**
   window opens.
2. Type these lines one at a time (press Enter after each):
   ```bat
   cd C:\forex-bot
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   pip install MetaTrader5
   ```
   - `cd C:\forex-bot` = "go into the bot's folder."
   - The `.venv` lines make and enter the bot's private box. When it works, each new line
     starts with `(.venv)`.
   - The two `pip install` lines download the bot's parts (this one includes
     `MetaTrader5`, which only works here on Windows).

**Step 4 — Quick check it runs (no money, no broker yet).**
```bat
python scripts\run_live.py --broker sim --max-iterations 200
```
You should see log lines like `OPEN BUY ...` / `CLOSE ... pnl=...`. That proves the bot
works on the VPS. Press `Ctrl+C` to stop. ✅ **Your bot now lives on a computer that never
sleeps.** Continue to Part D to connect a broker.

### C5. (Optional) Use the dashboard on the VPS

You can run the same web dashboard on the VPS and view it *inside* the Remote Desktop
screen:
```bat
python scripts\run_ui.py --port 5055
```
Then open Edge on the VPS and go to `http://127.0.0.1:5055`.

> ### 🔒 IMPORTANT security rule
> **Never expose the dashboard to the public internet.** Do **not** open its port in the
> firewall, and do **not** run it on `0.0.0.0`. Only use it *through* the Remote Desktop
> screen (that connection is already private and password-protected). The dashboard can
> change your trading settings, so treat it like online banking.

### C6. Keep the bot running 24/7

- **Simplest:** in the Command Prompt, start it (Part D/E), then **just leave that window
  open** and **don't shut the VPS down**. You can close the Remote Desktop window on your
  Mac — the VPS and the bot keep running in the cloud.
- **Sturdier (auto-restart after a reboot):** Windows **Task Scheduler** can start the bot
  automatically whenever the VPS turns on. Ask your helper to set up a "Basic Task → When
  the computer starts → start a program" that runs the bot's start command. Do this once
  you're comfortable with the basics.
- **Reminder:** if you *fully shut down* the VPS, the bot stops. Leave it running (you can
  disconnect Remote Desktop freely — that does not stop it).

---

## 6. Part D — Connect to a real broker

**Always start with a DEMO (practice) account. Same steps, fake money.**

### D1. Open an MT5 account (Nigeria-friendly brokers)

1. Pick a broker that accepts Nigeria and offers MT5: **IC Markets, Exness, XM,
   FP Markets, Pepperstone**.
2. Sign up and open a **DEMO / practice account** first (free, instant, no funding).
3. Download and install the **MetaTrader 5** terminal **on the VPS**, and log into your
   demo account inside it. Leave it running.
4. From the broker, note these three things:
   - **Login** (an account number, e.g. `51234567`)
   - **Password**
   - **Server** (an exact name, e.g. `ICMarkets-Demo` — copy it precisely)

### D2. Tell the bot your details

On the VPS, open the file `C:\forex-bot\.env` in Notepad and fill in:

```ini
MT5_LOGIN=51234567
MT5_PASSWORD=your-demo-password
MT5_SERVER=ICMarkets-Demo

INSTRUMENT=EURUSD
GRANULARITY=D
```

> **Note:** MT5 symbols usually have **no** underscore (`EURUSD`, not `EUR_USD`).

### D3. Download the broker's own price data and backtest on it

Backtesting on your broker's real prices is more accurate than free data:

```bat
python scripts\fetch_mt5_data.py --instrument EURUSD --granularity D --count 3000
python scripts\run_backtest.py --csv data\EURUSD_D.csv
```

### D4. "Dry run" — connect, but place NO orders

This proves the connection works without doing anything risky. The bot will *log what it
would do* but not actually trade:

```bat
python scripts\run_live.py --broker mt5 --dry-run
```

Watch the messages. You should see it start up and, when a signal occurs, print
`[DRY-RUN] would BUY ...`. Press `Ctrl+C` to stop.

### D5. Let it trade the DEMO account for real (fake money)

```bat
python scripts\run_live.py --broker mt5
```

Now it places real orders — but on the **demo** account, so it's fake money. **Leave it
running for several weeks.** Compare its results to what your backtest predicted. If they
roughly match and you're comfortable, only then consider Part E.

---

## 7. Part E — Switch to real money

⚠️ **Do not reach this step until the demo has run successfully for weeks and your
formula passed walk-forward.**

For MT5, "going live" simply means pointing the bot at a **funded live account** instead
of the demo one:

1. With your broker, open and **fund** a **live** MT5 account. Start with the **smallest
   amount you are 100% willing to lose entirely.**
2. Get the **live** account's Login, Password, and Server (the server name will say
   something like `ICMarkets-Live`, not `-Demo`).
3. On the VPS, edit `.env` and replace the demo values with the **live** ones:
   ```ini
   MT5_LOGIN=<your LIVE login>
   MT5_PASSWORD=<your LIVE password>
   MT5_SERVER=ICMarkets-Live
   ```
4. **Set your risk low.** In `.env`:
   ```ini
   RISK_PCT=0.5          # risk only 0.5% of the account per trade to start
   ```
5. Log the MT5 terminal on the VPS into the **live** account.
6. Do a **dry run against live first** (connects, places nothing):
   ```bat
   python scripts\run_live.py --broker mt5 --dry-run
   ```
7. When you're ready to actually trade real money:
   ```bat
   python scripts\run_live.py --broker mt5
   ```

> ⚠️ **There is no "practice/live" switch inside the bot for MT5** — whether it's real
> money depends entirely on **which account you logged the MT5 terminal into**. Double-,
> triple-check you're on the account you intend. Live server names usually contain
> "Live"; demo names contain "Demo".

### Keep it running 24/7 on the VPS

Normally the bot stops if you close the Command Prompt. To keep it alive:
- Simplest: just leave the Command Prompt window open and keep the VPS on (don't shut it
  down; you can safely close your Mac's Remote Desktop window — the VPS keeps running).
- Sturdier: use Windows **Task Scheduler** to start the bot automatically when the VPS
  boots. (Ask your helper to set this up when you're ready — it's a "run this command at
  log-on" task.)

---

## 8. Part F — Watch it

### Get a message on every trade (optional but recommended)

The bot can ping your **Telegram** or **email** whenever it trades or hits its daily loss
limit. In `.env`:

```ini
# Telegram: message @BotFather in Telegram to make a bot + get a token, then get your chat id.
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=987654321

# Or email (e.g. a Gmail "app password"):
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
ALERT_EMAIL_TO=you@gmail.com
```

Leave any you don't want blank. A failed alert never stops the bot from trading.

### See what it's been doing

Every action is written to a file called `bot.log` in the project folder. Open it any time
to see the history.

---

## 9. Safety checklist

Before real money, tick every box:

- [ ] My real formula is in (not the placeholder).
- [ ] It made money in a plain **backtest**.
- [ ] It **also** made money in **walk-forward** (the honest, out-of-sample test).
- [ ] It worked on **more than one currency pair** (not just cherry-picked).
- [ ] I ran it on a **demo account for several weeks** and results matched.
- [ ] `RISK_PCT` is small (0.5–1%).
- [ ] I'm using money I can afford to lose **entirely**.
- [ ] The MT5 terminal is logged into the account I actually intend.
- [ ] The dashboard is **not** exposed to the public internet.

If any box is unticked, **stay on demo.**

---

## 9b. Running it as a business (operator guide)

You sell access to the bot as a subscription. You never hold customer funds; each customer
connects their own MT5 account and withdraws at their own broker.

**One-time: create your admin login (on the VPS):**
```bash
python scripts/manage_users.py add you@yourbrand.com --password "a-strong-password" --admin
```

**When a new customer pays you (directly):**
1. Log in at your site, click **Admin** (top right).
2. **Add a customer** with their email + a temporary password.
3. Open their row → **Activate** (optionally set "active until" = their paid-through date).
4. Send them their email + temporary password.

**The customer then:**
1. Logs in (login only, no public signup).
2. Goes to the **Account** tab → **Broker connection** → enters their **own** MT5 login,
   password, server, instrument, and Telegram chat id → **Save**. (You never see their
   broker password.) They can also change their password there.
3. Runs **Practice** to watch the bot, then **Live** (dry-run first) on their own account.
4. Deposits/withdraws money at their **own broker** — never through your app.

**When a customer stops paying:** open their row in Admin → **Deactivate**. Live trading is
blocked immediately (they can still log in). Subscriptions with an "active until" date turn
off automatically.

**Password resets:** customers click "Forgot your password?" and get a code on the Telegram
they registered, no action needed from you. (Requires `TELEGRAM_BOT_TOKEN` set in `.env`.)

**Everything is managed from the browser** — the admin dashboard writes to the same
database the bot uses, so you don't have to log into the VPS to add or manage customers.

> Before charging real customers: sort out HTTPS, a production web server, backups, and
> the legal items in SAAS_ROADMAP.md. This is money, do it properly.

---

## 10. Plain-English glossary

Every term you'll meet, in one line:

| Term | In plain words |
|---|---|
| **Forex** | Trading one currency against another (e.g. Euro vs US Dollar). |
| **Pair** | The two currencies being traded, written together: `EURUSD`. |
| **Bar / candle** | One chunk of price history (e.g. one day's worth on a "1d" chart). |
| **Timeframe** | How much time each bar covers: `1h` = one hour, `1d` = one day. |
| **Backtest** | Replaying past prices to see how your rules would have done. No money. |
| **Demo account** | A practice account at a broker: real live prices, fake money. |
| **Live account** | A real account: real prices, **real money**. |
| **Broker** | The company that lets you place trades (for you: an MT5 broker). |
| **MT5 (MetaTrader 5)** | The trading app/platform your broker uses; the bot talks to it. |
| **VPS** | A rented computer in the cloud that runs 24/7 so the bot never stops. |
| **RDP / Remote Desktop** | Seeing and controlling the VPS's screen from your Mac. |
| **Trend line (EMA/SMA)** | A smoothed line following the price; two of them make buy/sell signals. |
| **RSI / momentum** | A meter of whether price has moved "too far, too fast." |
| **Stop-loss** | An automatic exit that caps your loss if a trade goes wrong. |
| **Take-profit / target** | An automatic exit that locks in profit when a trade goes right. |
| **Reward-to-risk** | How much you aim to win vs. what you risk (2 = win $2 per $1 risked). |
| **Profit factor** | Money won ÷ money lost. Above 1.0 = profitable. Higher is better. |
| **Win rate** | Share of trades that made money. Low can still be profitable! |
| **Drawdown / "worst dip"** | The biggest drop from a high point. How scary it got. |
| **Walk-forward** | The honest test: tune on old data, check on unseen data. |
| **Curve-fitting** | Tweaking settings until the *past* looks perfect — a trap that fails live. |
| **Spread** | The small cost of entering a trade (the gap between buy/sell price). |
| **Lot / units / position size** | How big a trade is. The bot sizes this for you from your risk %. |
| **`.env` file** | A plain settings file where your formula values and keys are stored. |
| **Dry run** | Connect to the broker but place **no** orders — just show what it *would* do. |

---

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| `command not found: python` | Use `python3` instead, or install Python (A1). |
| Prompt doesn't show `(.venv)` | Run `source .venv/bin/activate` (Mac) or `.venv\Scripts\activate` (Windows). |
| Dashboard won't open in browser | Make sure the Terminal still shows it running; try the exact URL `http://127.0.0.1:5055`. |
| Downloaded data doesn't appear | Click the **↻** button next to the data list, or refresh the browser page. |
| "10 year" hourly download is empty | Data providers only keep ~2 years of hourly data. Use `1d` for long history. |
| `MetaTrader5` won't install on Mac | Correct — it's **Windows only**. Use it on the VPS (Part C). |
| MT5 connection fails | Check `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` are exact; make sure the MT5 terminal is open and logged in. |
| I broke the formula code | The tool keeps your last working version automatically. Or reopen Step 4 and click **Reload from file**. |

---

### One last word

This tool makes it **easy to test** and **hard to do something reckless** — on purpose.
The slow path (backtest → walk-forward → demo for weeks → tiny real money) is not
red tape; it's the difference between trading and gambling. Take your time.
