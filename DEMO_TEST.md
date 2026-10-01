# Testing CRT on a real MT5 DEMO account (via the dashboard)

Goal: prove the bot actually connects to MT5 and trades a **demo** account (fake money,
real live prices), using the web dashboard. You picked: **Windows VM on your Mac**.

There are two phases:
- **Phase 1 — Plumbing test (~30 min):** on a fast timeframe, confirm the bot connects,
  places a real demo order, and you see it in MT5 + the chart + Telegram + History.
- **Phase 2 — Real validation (weeks):** on the Daily timeframe (where CRT was tested),
  let it run and compare live results to the backtest.

> ⚠️ **Apple Silicon note (M1/M2/M3):** Windows runs as ARM in the VM and the
> `MetaTrader5` Python package is x64, so it can be fiddly. If it won't import in the VM,
> the reliable fallback is a cheap **Windows VPS** (x64) — same steps from Step 3 on.

---

## Step 0 — Get a demo account
1. Open a demo account with a Nigeria-friendly MT5 broker (IC Markets, Exness, XM,
   FP Markets, Pepperstone).
2. Note the **login** (account number), **password**, and **server** name.

## Step 1 — Set up the Windows VM
1. Install a VM app (Parallels, VMware Fusion, or free UTM) and install Windows in it.
2. Everything below happens **inside Windows**.

## Step 2 — Install MetaTrader 5 in the VM
1. Download/install the **MetaTrader 5** terminal.
2. Log into your **demo** account inside it. Leave the terminal open and logged in.

## Step 3 — Install Python in the VM
1. Get Python from <https://www.python.org/downloads/>.
2. Run the installer and **tick "Add python.exe to PATH"**.

## Step 4 — Put the bot in the VM and install it
Copy the `forex-bot` folder into the VM (e.g. `C:\forex-bot`), then in **Command Prompt**:
```bat
cd C:\forex-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install MetaTrader5 cryptography
```
(`cryptography` encrypts stored broker passwords; `MetaTrader5` is the Windows-only bridge.)

## Step 5 — Create your admin login
```bat
python scripts\manage_users.py add you@yourbrand.com --password "a-strong-password" --admin
```

## Step 6 — Start the dashboard (inside the VM)
```bat
python scripts\run_ui.py --port 5055
```
Open **http://127.0.0.1:5055** in the VM's browser and log in as your admin.

> The dashboard must run **inside the VM**, because that's where MetaTrader 5 lives.

## Step 7 — Connect your broker (Account tab)
1. Go to **Account**.
2. Under **Broker connection**, enter your demo **MT5 login, password, server**, and your
   **Telegram chat id**. Save.
3. Click **Send test Telegram alert** to confirm alerts work.

## Step 8 — Phase 1: plumbing test on a fast timeframe
So you see action within minutes (not once a day), temporarily use a 5-minute timeframe:
1. Stop the dashboard (Ctrl+C), edit `.env`: set `GRANULARITY=M5`, then start it again.
2. Go to the **Live** tab. The readiness box should say broker configured: **yes**,
   MetaTrader 5 available: **yes**.
3. Set **Safety = Dry-run (no orders)** → **Start**. Watch the log: it connects and prints
   `[DRY-RUN] would BUY/SELL ...` when a CRT setup appears. Let it run a few minutes.
4. Now set **Safety = Place real orders** → **Start**. When a setup fires you should see:
   - a **real order in the MT5 terminal** (with stop-loss + take-profit attached),
   - the order on the **live chart** + in the **log**,
   - a **Telegram alert**,
   - the closed trade later in the **History** tab (and CSV).
5. Confirm the numbers match what MT5 shows. Then **Stop**.

✅ If all that happens, the whole pipeline works against real MT5.

## Step 9 — Phase 2: real validation on Daily
1. Stop the dashboard, set `.env` back to `GRANULARITY=D`, restart.
2. Live tab → **Start** (real orders, demo account).
3. **Leave the VM on and the bot running for several weeks.** Check the History tab and
   compare the live demo results to the backtest (win rate, profit factor, drawdown).
4. Only if live demo roughly matches the backtest should you consider real money.

---

## Common issues (and the fixes already built in)
| Symptom | Cause / fix |
|---|---|
| Readiness: "MetaTrader 5 available: no" | `MetaTrader5` not importable in the VM (Apple Silicon). Use a Windows VPS. |
| "MT5 login failed" | Login/password/server not exactly as in the terminal. Server name is case-sensitive. |
| "MT5 initialize failed" | The MT5 terminal isn't installed/open in the VM. |
| No trades for a long time | Normal on Daily (few signals). Use M5 for the plumbing test. |
| Order rejected | The adapter auto-retries filling modes and rounds stops to the symbol's digits; if it still fails the log shows the broker's exact reason. |

## Reminder
- Demo = fake money. Keep it on demo until it proves itself.
- You never handle customer funds; each person connects their own account and withdraws
  at their own broker.
