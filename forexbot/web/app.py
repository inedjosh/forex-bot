"""Dead-simple local web UI for the forex bot.

Runs entirely on your machine (nothing is uploaded anywhere). Lets a non-technical user:
  - download real market data with one click,
  - adjust the strategy settings with plain-language fields,
  - run a backtest and see the results + equity curve,
  - run the optimizer and apply the best settings.

Start it with:  python scripts/run_ui.py   then open http://127.0.0.1:5000
"""

from __future__ import annotations

import glob
import io
import os
from pathlib import Path

from ..backtest import BacktestEngine
from ..config import env_bool, env_float, env_int, env_str, update_env
from ..data import load_csv, synthetic_candles
from ..data.yahoo import download_yahoo
from ..optimize import grid_search
from ..risk import RiskConfig
from ..strategies import REGISTRY, get_strategy

_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _ROOT / "data"

# The formula settings the UI exposes as a plain form (no code), grouped for clarity.
# Each: key, group, label, kind (int/float/choice/bool), default, help, [options].
SETTINGS = [
    # ── Strategy & timeframe ──
    {"key": "STRATEGY", "group": "Strategy", "label": "Trading strategy", "kind": "choice",
     "options": ["crt", "ashape"], "default": "crt",
     "help": "'crt' = Candle Range Theory (best on Daily). 'ashape' = your A-Shape/V-Shape key-level model (best on H1 with higher-TF key levels)."},
    {"key": "GRANULARITY", "group": "Strategy", "label": "Timeframe", "kind": "choice",
     "options": ["M5", "M15", "M30", "H1", "H4", "D"], "default": "D",
     "help": "The candle size the bot trades on. CRT -> D (daily). Your A-Shape model -> H1."},
    # ── A-Shape / V-Shape Key Level (your model) ──
    {"key": "KL_HTF_MULTIPLE", "group": "Key Level model", "label": "Key-level timeframe (x base)", "kind": "int", "default": 2,
     "help": "Key levels are read from this many base candles grouped together. On H1: 2 = 2H key levels, 4 = 4H."},
    {"key": "KL_RISK_REWARD", "group": "Key Level model", "label": "Reward:risk", "kind": "float", "default": 2.0,
     "help": "Target vs stop. 2 = aim to win twice the risk (works best around 2 for this model)."},
    {"key": "KL_STOP_BUFFER_PCT", "group": "Key Level model", "label": "Stop buffer (%)", "kind": "float", "default": 0.05,
     "help": "Extra cushion beyond the key level for the stop, as a % of price."},
    {"key": "KL_MAX_AGE", "group": "Key Level model", "label": "Key-level lifespan (bars)", "kind": "int", "default": 120,
     "help": "How many base candles a key level stays valid, waiting for price to return."},
    {"key": "KL_REQUIRE_ENGULFING", "group": "Key Level model", "label": "Require engulfing?", "kind": "bool", "default": True,
     "help": "Wait for a bearish (sell) / bullish (buy) engulfing candle to confirm, as in your model. Recommended: Yes."},
    {"key": "KL_TRADE_SELLS", "group": "Key Level model", "label": "Take A-Shape sells?", "kind": "bool", "default": True,
     "help": "Trade the A-Shape (bull-then-bear) supply zones as sells."},
    {"key": "KL_TRADE_BUYS", "group": "Key Level model", "label": "Take V-Shape buys?", "kind": "bool", "default": True,
     "help": "Trade the mirror V-Shape (bear-then-bull) demand zones as buys."},
    # ── CRT setup ──
    {"key": "CRT_RANGE_LOOKBACK", "group": "CRT setup", "label": "Range candles", "kind": "int", "default": 1,
     "help": "How many prior candles form the range whose high/low get swept. 1 = the single previous candle (classic CRT)."},
    {"key": "CRT_TARGET_MODE", "group": "CRT setup", "label": "Target", "kind": "choice",
     "options": ["range", "rr"], "default": "range",
     "help": "'range' aims for the opposite side of the range (classic CRT). 'rr' aims for a fixed reward-to-risk multiple instead."},
    {"key": "CRT_RISK_REWARD", "group": "CRT setup", "label": "Reward:risk (if target = rr)", "kind": "float", "default": 2.0,
     "help": "Only used when Target = rr. 2 = aim to win twice what you risk."},
    {"key": "CRT_MIN_RR", "group": "CRT setup", "label": "Minimum reward:risk", "kind": "float", "default": 1.0,
     "help": "Skip setups whose reward-to-risk is below this. Filters out low-quality trades."},
    {"key": "CRT_STOP_BUFFER_PCT", "group": "CRT setup", "label": "Stop buffer (%)", "kind": "float", "default": 0.0,
     "help": "Extra cushion beyond the sweep wick for the stop-loss, as a % of price. 0 = stop exactly at the wick."},
    {"key": "CRT_TREND_FILTER", "group": "CRT setup", "label": "Trade with the trend?", "kind": "bool", "default": True,
     "help": "Evidence-based: only take trades in the direction of the bigger trend (longs in uptrends, shorts in downtrends). Trend-following is the most robust edge. Recommended: Yes."},
    {"key": "CRT_TREND_PERIOD", "group": "CRT setup", "label": "Trend line length", "kind": "int", "default": 50,
     "help": "How many bars define the 'bigger trend' for the filter. 50 is a common choice on the daily chart."},
    # ── Account & risk ──
    {"key": "RISK_PCT", "group": "Account & risk", "label": "Risk per trade (%)", "kind": "float", "default": 1.0,
     "help": "Most you can lose on ONE trade, as a % of the account. Keep small: 0.5% to 2%."},
    {"key": "STARTING_BALANCE", "group": "Account & risk", "label": "Practice balance ($)", "kind": "float", "default": 10000,
     "help": "The pretend account size used for backtests/practice. Not real money."},
    # ── Loss protection (your safety net) ──
    {"key": "MAX_MONTHLY_LOSS_PCT", "group": "Loss protection", "label": "Max monthly loss (%)", "kind": "float", "default": 20.0,
     "help": "HARD cap: if the account is down this % for the month, the bot stops until next month. Your ultimate safety net."},
    {"key": "MAX_DAILY_LOSS_PCT", "group": "Loss protection", "label": "Max daily loss (%)", "kind": "float", "default": 0.8,
     "help": "If down this % on the day, the bot stops until tomorrow. ~0.8% x 21 trading days stays under a 20% month."},
    {"key": "DAILY_PROFIT_TARGET_PCT", "group": "Loss protection", "label": "Daily profit target (%)", "kind": "float", "default": 0.0,
     "help": "Once up this % on the day, the bot stops and locks in the win. 0 = keep trading all day."},
    {"key": "MAX_TRADES_PER_DAY", "group": "Loss protection", "label": "Max trades per day", "kind": "int", "default": 0,
     "help": "Stop after this many trades in a day (prevents over-trading). 0 = no limit."},
    {"key": "MAX_CONSECUTIVE_LOSSES", "group": "Loss protection", "label": "Stop after losses in a row", "kind": "int", "default": 0,
     "help": "After this many losing trades back-to-back, pause for the day. 0 = off."},
]


def _setting_value(s):
    key, kind = s["key"], s["kind"]
    if kind == "int":
        return env_int(key, int(s["default"]))
    if kind == "float":
        return env_float(key, float(s["default"]))
    if kind == "bool":
        return "true" if env_bool(key, bool(s["default"])) else "false"
    return env_str(key, str(s["default"]))  # choice


# Ready-made "recipes" , pick one to fill the whole form with sensible values.
PRESETS = [
    {"name": "Classic CRT (range target)",
     "desc": "Sweep the previous candle's high/low, reclaim, then aim for the opposite side of the range. The textbook setup.",
     "values": {"CRT_RANGE_LOOKBACK": 1, "CRT_TARGET_MODE": "range",
                "CRT_RISK_REWARD": 2.0, "CRT_MIN_RR": 1.0, "CRT_STOP_BUFFER_PCT": 0.0,
                "RISK_PCT": 1.0}},
    {"name": "CRT 1:2 reward",
     "desc": "Same sweep + reclaim, but takes profit at a fixed 2x your risk instead of the range edge.",
     "values": {"CRT_RANGE_LOOKBACK": 1, "CRT_TARGET_MODE": "rr",
                "CRT_RISK_REWARD": 2.0, "CRT_MIN_RR": 1.0, "CRT_STOP_BUFFER_PCT": 0.0,
                "RISK_PCT": 1.0}},
    {"name": "CRT high-quality only",
     "desc": "Only takes setups offering at least 2:1 reward, with a small stop cushion. Fewer, cleaner trades.",
     "values": {"CRT_RANGE_LOOKBACK": 1, "CRT_TARGET_MODE": "range",
                "CRT_RISK_REWARD": 2.0, "CRT_MIN_RR": 2.0, "CRT_STOP_BUFFER_PCT": 0.05,
                "RISK_PCT": 1.0}},
    {"name": "CRT cautious (small risk)",
     "desc": "The classic setup but risking only 0.5% per trade. Smaller ups and downs.",
     "values": {"CRT_RANGE_LOOKBACK": 1, "CRT_TARGET_MODE": "range",
                "CRT_RISK_REWARD": 2.0, "CRT_MIN_RR": 1.0, "CRT_STOP_BUFFER_PCT": 0.0,
                "RISK_PCT": 0.5}},
]

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP"]
INTERVALS = ["15m", "30m", "1h", "1d"]


def _current_config() -> dict:
    out = {s["key"]: _setting_value(s) for s in SETTINGS}
    out["STRATEGY"] = env_str("STRATEGY", "crt")
    return out


def _data_files() -> list:
    files = sorted(glob.glob(str(_DATA_DIR / "*.csv")))
    return [os.path.basename(f) for f in files]


def _result_to_dict(result) -> dict:
    return {
        "strategy": result.strategy_name,
        "trades": result.num_trades,
        "wins": len(result.wins),
        "losses": len(result.losses),
        "win_rate": round(result.win_rate, 1),
        "profit_factor": (None if result.profit_factor == float("inf")
                          else round(result.profit_factor, 2)),
        "net_pnl": round(result.net_pnl, 2),
        "return_pct": round(result.return_pct, 2),
        "start_balance": round(result.starting_balance, 2),
        "end_balance": round(result.ending_balance, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
    }


def create_app():
    try:
        from flask import Flask, jsonify, redirect, request, send_file, session
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Flask is required for the web UI.\n"
                          "    pip install flask") from exc

    from . import auth
    auth.init_db()

    app = Flask(__name__)
    app.secret_key = auth.get_secret_key()
    # Hold the most recent equity-curve PNG in memory to serve to the browser.
    app.config["_equity_png"] = None

    _PUBLIC = {"/login", "/logout", "/forgot", "/reset"}

    def _is_admin():
        return session.get("role") == "admin"

    @app.before_request
    def _require_login():
        p = request.path
        if p in _PUBLIC or p.startswith("/static"):
            return None
        if session.get("uid"):
            return None
        if p.startswith("/api"):
            return jsonify({"ok": False, "error": "Please log in."}), 401
        return redirect("/login")

    @app.after_request
    def _no_cache(resp):
        # Never let the browser serve a stale page or stale data list.
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        return resp

    # ── Authentication routes ────────────────────────────────────────────────
    @app.get("/login")
    def login_page():
        return _auth_html("login")

    @app.post("/login")
    def login_post():
        u = auth.verify_user(request.form.get("email", ""), request.form.get("password", ""))
        if not u:
            return _auth_html("login", error="Wrong email or password.")
        session["uid"], session["email"], session["role"] = u["id"], u["email"], u["role"]
        return redirect("/")

    # Public signup is intentionally disabled — accounts are created by the admin only.
    # Bootstrap the first admin on the VPS with:
    #     python scripts/manage_users.py add you@example.com --password '...' --admin

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect("/login")

    @app.get("/forgot")
    def forgot_page():
        return _auth_html("forgot")

    @app.post("/forgot")
    def forgot_post():
        from ..notify import send_telegram_to
        email = request.form.get("email", "")
        req = auth.start_reset(email)
        if req:
            send_telegram_to(req["chat_id"],
                             f"Your Forex Bot password reset code is: {req['code']}\n"
                             f"It expires in 15 minutes.")
        # Don't reveal whether the account/telegram exists.
        return _auth_html("reset",
                          info="If that account has Telegram on file, a code was just sent. "
                               "Enter it below.")

    @app.get("/reset")
    def reset_page():
        return _auth_html("reset")

    @app.post("/reset")
    def reset_post():
        ok, msg = auth.complete_reset(request.form.get("email", ""),
                                      request.form.get("code", ""),
                                      request.form.get("password", ""))
        if not ok:
            return _auth_html("reset", error=msg)
        return _auth_html("login", info="Password updated. Please log in.")

    @app.get("/api/me")
    def me():
        return jsonify({"email": session.get("email"), "role": session.get("role")})

    # ── Admin API (manage everything from the browser — no SSH needed) ─────────
    @app.get("/admin")
    def admin_page():
        if not _is_admin():
            return redirect("/")
        return _ADMIN_HTML

    @app.get("/api/admin/users")
    def admin_users():
        if not _is_admin():
            return jsonify({"ok": False, "error": "admins only"}), 403
        return jsonify({"ok": True, "users": auth.list_users()})

    @app.post("/api/admin/action")
    def admin_action():
        if not _is_admin():
            return jsonify({"ok": False, "error": "admins only"}), 403
        d = request.get_json(force=True) or {}
        action = d.get("action")
        email = d.get("email", "")

        if action == "create":
            ok, msg = auth.create_user(email, d.get("password", ""))
            return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)

        if action == "set":
            # Admin sets account-level fields only (incl. the customer's Telegram, which
            # they give you up front for alerts + password reset). The CUSTOMER still sets
            # their own MT5 details from their dashboard, so we never hold their broker password.
            fields = {k: d[k] for k in ("subdomain", "notes", "telegram_chat_id", "instrument")
                      if d.get(k) not in (None,)}
            if not fields:
                return jsonify({"ok": False, "error": "nothing to update"}), 400
            ok = auth.set_settings(email, **fields)
            return jsonify({"ok": ok}), (200 if ok else 400)

        if action == "activate":
            exp = d.get("until")
            exp = (exp + "T23:59:59+00:00") if exp else None
            ok = auth.set_settings(email, active=1, expires_at=exp)
            return jsonify({"ok": ok}), (200 if ok else 400)

        if action == "deactivate":
            ok = auth.set_settings(email, active=0)
            return jsonify({"ok": ok}), (200 if ok else 400)

        # Note: password resets are self-service only (customers use "Forgot password"
        # via Telegram). Admins cannot set customer passwords.
        return jsonify({"ok": False, "error": "unknown action"}), 400

    @app.get("/api/admin/platform-token")
    def get_platform_token():
        if not _is_admin():
            return jsonify({"ok": False}), 403
        return jsonify({"ok": True, "set": bool(env_str("TELEGRAM_BOT_TOKEN", ""))})

    @app.post("/api/admin/platform-token")
    def set_platform_token():
        if not _is_admin():
            return jsonify({"ok": False, "error": "admins only"}), 403
        tok = (request.get_json(force=True) or {}).get("token", "").strip()
        if not tok:
            return jsonify({"ok": False, "error": "empty token"}), 400
        update_env({"TELEGRAM_BOT_TOKEN": tok})  # saved to server .env (not git)
        return jsonify({"ok": True})

    @app.get("/")
    def index():
        return _INDEX_HTML

    @app.get("/api/state")
    def state():
        return jsonify({
            "config": _current_config(),
            "settings": [
                {"key": s["key"], "group": s["group"], "label": s["label"],
                 "kind": s["kind"], "help": s["help"], "options": s.get("options"),
                 "default": ("true" if s["default"] else "false") if s["kind"] == "bool"
                            else s["default"]}
                for s in SETTINGS
            ],
            "datafiles": _data_files(),
            "strategies": sorted(REGISTRY),
            "pairs": PAIRS,
            "intervals": INTERVALS,
            "presets": PRESETS,
        })

    @app.post("/api/save-config")
    def save_config():
        if not _is_admin():
            return jsonify({"ok": False, "error": "admins only"}), 403
        data = request.get_json(force=True) or {}
        allowed = {s["key"] for s in SETTINGS} | {"STRATEGY"}
        updates = {k: v for k, v in data.items() if k in allowed and v not in ("", None)}
        if updates:
            update_env(updates)
        return jsonify({"ok": True, "saved": list(updates)})

    @app.post("/api/fetch")
    def fetch():
        if not _is_admin():
            return jsonify({"ok": False, "error": "admins only"}), 403
        data = request.get_json(force=True) or {}
        pair = data.get("pair", "EURUSD")
        interval = data.get("interval", "1h")
        period = data.get("period", "2y")
        try:
            path, rows = download_yahoo(pair, interval, period)
        except ImportError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "file": os.path.basename(path), "candles": rows})

    @app.post("/api/backtest")
    def backtest():
        if not _is_admin():
            return jsonify({"ok": False, "error": "admins only"}), 403
        data = request.get_json(force=True) or {}
        strategy_name = data.get("strategy", env_str("STRATEGY", "crt"))
        source = data.get("file", "")

        if source == "__synthetic__" or not source:
            candles = synthetic_candles(n=2000, seed=42)
            label = "sample practice data"
        else:
            path = _DATA_DIR / source
            if not path.exists():
                return jsonify({"ok": False, "error": "data file not found"}), 400
            candles = load_csv(str(path))
            label = source

        if len(candles) < 50:
            return jsonify({"ok": False, "error": "not enough candles"}), 400

        engine = BacktestEngine(risk_config=RiskConfig.from_env())
        try:
            result = engine.run(get_strategy(strategy_name), candles)
        except Exception as exc:  # noqa: BLE001 , surface formula errors to the UI
            return jsonify({"ok": False,
                            "error": f"The formula errored while running: {exc}"}), 400

        # Render equity curve to an in-memory PNG (if matplotlib is available).
        image_ok = False
        try:
            from ..analytics.plot import plot_equity
            tmp = _DATA_DIR / "_ui_equity.png"
            plot_equity(result, str(tmp))
            app.config["_equity_png"] = tmp.read_bytes()
            image_ok = True
        except Exception:  # noqa: BLE001 , plotting is optional
            app.config["_equity_png"] = None

        payload = _result_to_dict(result)
        payload["source"] = label
        payload["candles"] = len(candles)
        return jsonify({"ok": True, "result": payload, "has_image": image_ok})

    @app.get("/api/equity.png")
    def equity_png():
        png = app.config.get("_equity_png")
        if not png:
            return ("no image", 404)
        return send_file(io.BytesIO(png), mimetype="image/png")

    @app.post("/api/optimize")
    def optimize():
        if not _is_admin():
            return jsonify({"ok": False, "error": "admins only"}), 403
        data = request.get_json(force=True) or {}
        source = data.get("file", "")
        if source and source != "__synthetic__":
            path = _DATA_DIR / source
            if not path.exists():
                return jsonify({"ok": False, "error": "data file not found"}), 400
            candles = load_csv(str(path))
        else:
            candles = synthetic_candles(n=3000, seed=42)

        ranked = grid_search(candles, risk_config=RiskConfig.from_env())
        valid = [r for r in ranked if r.score != float("-inf")][:10]
        rows = [{
            "params": pr.params,
            "net_pnl": round(pr.result.net_pnl, 2),
            "profit_factor": (None if pr.result.profit_factor == float("inf")
                              else round(pr.result.profit_factor, 2)),
            "win_rate": round(pr.result.win_rate, 1),
            "trades": pr.result.num_trades,
        } for pr in valid]
        return jsonify({"ok": True, "rows": rows,
                        "best": rows[0]["params"] if rows else None})

    from .live_controller import LiveController
    # One trading loop PER USER (multi-tenant isolation), keyed by email.
    _controllers: dict = {}

    def _ctrl():
        email = session.get("email", "?")
        if email not in _controllers:
            _controllers[email] = LiveController()
        _controllers[email].email = email  # so closed trades are saved to this user
        return _controllers[email]

    @app.post("/api/live/start")
    def live_start():
        data = request.get_json(force=True) or {}
        mode = data.get("mode", "practice")
        dry_run = bool(data.get("dry_run", False))
        tick = float(data.get("tick", 0.7))
        c = _ctrl()

        tg = (auth.get_settings(session.get("email", "")) or {}).get("telegram_chat_id")

        if mode == "practice":
            csv_path = None
            src = data.get("file", "")
            if src and src != "__synthetic__":
                p = _DATA_DIR / src
                if not p.exists():
                    return jsonify({"ok": False, "error": "data file not found"}), 400
                csv_path = str(p)
            ok, msg = c.start(mode="practice", csv_path=csv_path, tick=tick, telegram_chat_id=tg)
            return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)

        # Live: must have an active subscription (admins are exempt) and broker connected.
        email = session.get("email", "")
        if not _is_admin() and not auth.is_active(email):
            return jsonify({"ok": False,
                            "error": "Your subscription is not active. Please contact support."}), 403
        s = auth.get_settings(email) or {}
        if not (s.get("mt5_login") and s.get("mt5_password") and s.get("mt5_server")):
            return jsonify({"ok": False,
                            "error": "Connect your broker first: enter your MT5 details below."}), 400
        instrument = s.get("instrument") or "EURUSD"
        ok, msg = c.start(
            mode="live", dry_run=dry_run, tick=tick,
            mt5={"login": s["mt5_login"], "password": s["mt5_password"], "server": s["mt5_server"]},
            instrument=instrument, telegram_chat_id=s.get("telegram_chat_id"),
        )
        if ok:
            # Remember this run so it auto-resumes after a restart/reboot.
            auth.set_live_run(email, dry_run, instrument)
        return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)

    @app.post("/api/live/stop")
    def live_stop():
        _ctrl().stop()
        # Explicit stop = don't auto-resume this one later.
        auth.clear_live_run(session.get("email", ""))
        return jsonify({"ok": True})

    @app.get("/api/live/state")
    def live_state():
        return jsonify(_ctrl().state())

    # ── The logged-in user's own broker connection (they set it themselves) ────
    @app.get("/api/my-broker")
    def my_broker():
        s = auth.get_settings(session.get("email", "")) or {}
        return jsonify({
            "mt5_login": s.get("mt5_login") or "",
            "mt5_server": s.get("mt5_server") or "",
            "instrument": s.get("instrument") or "",
            "telegram_chat_id": s.get("telegram_chat_id") or "",
            "has_password": bool(s.get("mt5_password")),
            "active": auth.is_active(session.get("email", "")),
            "expires_at": s.get("expires_at"),
        })

    @app.post("/api/my-broker")
    def my_broker_save():
        d = request.get_json(force=True) or {}
        fields = {k: d[k] for k in ("mt5_login", "mt5_server", "instrument", "telegram_chat_id")
                  if d.get(k) is not None}
        if d.get("mt5_password"):
            fields["mt5_password"] = d["mt5_password"]
        if fields:
            auth.set_settings(session.get("email", ""), **fields)
        return jsonify({"ok": True})

    @app.post("/api/test-telegram")
    def test_telegram():
        from ..notify import send_telegram_to
        s = auth.get_settings(session.get("email", "")) or {}
        chat = s.get("telegram_chat_id")
        if not chat:
            return jsonify({"ok": False, "error": "Set your Telegram chat id first."}), 400
        if not env_str("TELEGRAM_BOT_TOKEN", ""):
            return jsonify({"ok": False, "error": "The service's Telegram bot isn't configured yet."}), 400
        sent = send_telegram_to(chat, "Forex Bot test alert: your Telegram is connected. "
                                      "You'll get trade alerts and reset codes here.")
        if sent:
            return jsonify({"ok": True})
        return jsonify({"ok": False,
                        "error": "Could not send. Open the bot in Telegram and press Start, then retry."}), 400

    @app.get("/api/my-history")
    def my_history():
        return jsonify({"trades": auth.list_trades(session.get("email", ""), limit=500)})

    @app.get("/api/my-history.csv")
    def my_history_csv():
        from flask import Response
        csv_text = auth.trades_csv(session.get("email", ""))
        return Response(csv_text, mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=trade_history.csv"})

    @app.post("/api/my-password")
    def my_password():
        d = request.get_json(force=True) or {}
        email = session.get("email", "")
        if not auth.verify_user(email, d.get("current", "")):
            return jsonify({"ok": False, "error": "Current password is wrong."}), 400
        if not auth.set_password(email, d.get("new", "")):
            return jsonify({"ok": False, "error": "New password must be at least 8 characters."}), 400
        return jsonify({"ok": True})

    @app.get("/api/live-status")
    def live_status():
        """Report whether THIS user is ready to live-trade (their broker connected?)."""
        s = auth.get_settings(session.get("email", "")) or {}
        mt5_configured = bool(s.get("mt5_login") and s.get("mt5_password") and s.get("mt5_server"))
        try:
            import MetaTrader5  # noqa: F401
            mt5_available = True
        except Exception:  # noqa: BLE001 — Windows-only package; absent on Mac
            mt5_available = False
        return jsonify({
            "mt5_configured": mt5_configured,
            "mt5_available": mt5_available,
            "instrument": s.get("instrument") or env_str("INSTRUMENT", "EURUSD"),
            "granularity": env_str("GRANULARITY", "D"),
            "alerts": (["telegram"] if s.get("telegram_chat_id") else []),
            "server": s.get("mt5_server", ""),
        })

    # ── Auto-resume live trading after a restart / VPS reboot ──────────────────
    def _resume_live_runs():
        import logging
        log = logging.getLogger("forexbot.web")
        for r in auth.list_live_runs():
            email = r["email"]
            if not auth.is_active(email):
                auth.clear_live_run(email)  # subscription lapsed while we were down
                continue
            s = auth.get_settings(email) or {}
            if not (s.get("mt5_login") and s.get("mt5_password") and s.get("mt5_server")):
                continue
            c = _controllers.setdefault(email, LiveController())
            c.email = email
            ok, msg = c.start(
                mode="live", dry_run=bool(r["dry_run"]),
                mt5={"login": s["mt5_login"], "password": s["mt5_password"],
                     "server": s["mt5_server"]},
                instrument=r.get("instrument") or s.get("instrument") or "EURUSD",
            )
            # On resume the loop checks the broker for the existing position (placed with
            # its stop-loss/take-profit) and keeps managing it instead of double-opening.
            log.info("Resume live run for %s: %s", email, "ok" if ok else msg)

    try:
        _resume_live_runs()
    except Exception:  # noqa: BLE001 — never let resume crash startup
        pass

    return app


def _auth_html(kind: str, error: str = "", info: str = "") -> str:
    """Render an auth page: kind is 'login', 'signup', 'forgot' or 'reset'."""
    cfg = {
        "login":  {"title": "Log in", "action": "/login", "button": "Log in"},
        "signup": {"title": "Create your account", "action": "/signup", "button": "Sign up"},
        "forgot": {"title": "Reset your password", "action": "/forgot", "button": "Send code to Telegram"},
        "reset":  {"title": "Enter your reset code", "action": "/reset", "button": "Set new password"},
    }[kind]
    err = f'<div class="err">{error}</div>' if error else ""
    note = f'<div class="ok">{info}</div>' if info else ""

    if kind == "login":
        fields = ('<label>Email</label><input type="email" name="email" required autofocus/>'
                  '<label>Password</label><input type="password" name="password" required/>')
        switch = ('Forgot your password? <a href="/forgot">Reset via Telegram</a>')
    elif kind == "signup":
        fields = ('<label>Email</label><input type="email" name="email" required autofocus/>'
                  '<label>Password</label><input type="password" name="password" required/>'
                  '<div class="hint">Password must be at least 8 characters.</div>')
        switch = 'Already have an account? <a href="/login">Log in</a>'
    elif kind == "forgot":
        fields = ('<label>Email</label><input type="email" name="email" required autofocus/>'
                  '<div class="hint">If we have your Telegram on file, we\'ll send a 6-digit '
                  'code there.</div>')
        switch = 'Remembered it? <a href="/login">Back to log in</a>'
    else:  # reset
        fields = ('<label>Email</label><input type="email" name="email" required autofocus/>'
                  '<label>Code from Telegram</label><input name="code" required/>'
                  '<label>New password</label><input type="password" name="password" required/>')
        switch = 'Need a new code? <a href="/forgot">Send again</a>'

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{cfg["title"]} - Forex Bot</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
  :root {{ --ink:#262626; --muted:#696969; --accent:#cb3837; --line:#e6e6e6; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:15px/1.6 'IBM Plex Sans',Arial,sans-serif; background:#fafafa; color:var(--ink);
    display:flex; min-height:100vh; align-items:center; justify-content:center; padding:20px; }}
  .box {{ background:#fff; border:1px solid var(--line); padding:32px; width:100%; max-width:380px; }}
  .logo {{ background:var(--accent); color:#fff; font-weight:700; padding:6px 9px; display:inline-block; }}
  h1 {{ font-size:19px; margin:18px 0 4px; }}
  p.sub {{ color:var(--muted); font-size:13.5px; margin:0 0 20px; }}
  label {{ display:block; font-size:12.5px; font-weight:600; margin:14px 0 6px; }}
  input {{ width:100%; padding:11px 12px; border:1px solid #d1d5da; border-radius:0; font-size:14px;
    font-family:inherit; }}
  input:focus {{ outline:none; border-color:var(--accent); box-shadow:0 0 0 2px rgba(203,56,55,.2); }}
  button {{ width:100%; margin-top:20px; background:var(--accent); color:#fff; border:1px solid var(--accent);
    padding:12px; font-size:15px; font-weight:600; cursor:pointer; border-radius:0; font-family:inherit; }}
  button:hover {{ background:#b02a2a; }}
  .switch {{ margin-top:18px; font-size:13.5px; }}
  a {{ color:var(--accent); }}
  .err {{ background:#fff; border:1px solid var(--accent); border-left:4px solid var(--accent);
    padding:10px 12px; font-size:13px; margin-bottom:16px; }}
  .ok {{ background:#fff; border:1px solid #137333; border-left:4px solid #137333;
    padding:10px 12px; font-size:13px; margin-bottom:16px; }}
  .hint {{ font-size:12px; color:var(--muted); margin-top:6px; }}
</style></head><body>
  <div class="box">
    <span class="logo">fx</span>
    <h1>{cfg["title"]}</h1>
    <p class="sub">Forex Bot dashboard</p>
    {err}{note}
    <form method="POST" action="{cfg["action"]}">
      {fields}
      <button type="submit">{cfg["button"]}</button>
    </form>
    <div class="switch">{switch}</div>
  </div>
</body></html>"""


# ── Admin dashboard (manage all customers from the browser) ─────────────────────
_ADMIN_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Admin - Forex Bot</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
  :root { --ink:#262626; --muted:#696969; --accent:#cb3837; --line:#e6e6e6; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.6 'IBM Plex Sans',Arial,sans-serif; background:#fff; color:var(--ink); }
  input, select, button { font-family:'IBM Plex Sans',Arial,sans-serif; }
  header { padding:0 24px; height:56px; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:14px; }
  .logo { background:var(--accent); color:#fff; font-weight:700; padding:6px 9px; }
  header h1 { font-size:15px; margin:0; font-weight:600; }
  .spacer { flex:1; }
  header a { color:var(--accent); font-weight:600; text-decoration:none; font-size:13.5px; margin-left:14px; }
  main { max-width:none; padding:24px 40px; display:grid; gap:22px; }
  .card { border:1px solid var(--line); padding:22px 24px; }
  h2 { font-size:16px; margin:0 0 14px; }
  label { display:block; font-size:12px; font-weight:600; color:var(--ink); margin:0 0 5px; }
  input { width:100%; padding:9px 10px; border:1px solid #d1d5da; border-radius:0; font-size:13.5px; }
  input:focus { outline:none; border-color:var(--accent); box-shadow:0 0 0 2px rgba(203,56,55,.2); }
  .row { display:flex; gap:12px; flex-wrap:wrap; align-items:end; }
  .row > div { flex:1; min-width:130px; }
  button { background:var(--accent); color:#fff; border:1px solid var(--accent); padding:9px 15px;
    border-radius:0; font-weight:600; font-size:13.5px; cursor:pointer; }
  button:hover { background:#b02a2a; }
  button.ghost { background:#fff; color:var(--ink); border:1px solid #d1d5da; }
  button.ghost:hover { background:#f6f6f6; }
  .user { border:1px solid var(--line); padding:16px 18px; margin-bottom:14px; }
  .user h3 { margin:0 0 4px; font-size:15px; }
  .meta { font-size:12.5px; color:var(--muted); margin-bottom:12px; }
  .pill { display:inline-block; font-size:11px; font-weight:600; padding:2px 8px; border:1px solid var(--line); margin-left:6px; }
  .pill.on { color:#137333; border-color:#137333; }
  .pill.off { color:var(--accent); border-color:var(--accent); }
  details summary { cursor:pointer; color:var(--accent); font-weight:600; font-size:13px; margin-top:8px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:12px; margin:12px 0; }
  .actions { display:flex; gap:10px; flex-wrap:wrap; align-items:end; margin-top:10px; }
  .toast { position:fixed; bottom:20px; left:50%; transform:translateX(-50%); background:var(--ink); color:#fff;
    padding:11px 18px; opacity:0; transition:.3s; pointer-events:none; }
  .toast.show { opacity:1; }
  @media (max-width:720px){ header{padding:0 16px;} main{padding:18px 16px;} .card{padding:16px;} .row>div{min-width:100%;} }
</style></head>
<body>
<header>
  <span class="logo">fx</span><h1>Admin</h1>
  <span class="spacer"></span>
  <a href="/">Dashboard</a><a href="/logout">Log out</a>
</header>
<main>
  <div class="card">
    <h2>Add a customer</h2>
    <div class="row">
      <div><label>Email</label><input id="newEmail" type="email" placeholder="jane@example.com"/></div>
      <div><label>Temporary password</label><input id="newPass" placeholder="min 8 characters"/></div>
      <div style="flex:0"><label>&nbsp;</label><button id="addBtn">Create</button></div>
    </div>
    <div class="meta" style="margin-top:10px">After creating, open the customer below to attach their MT5 account, Telegram, and turn their subscription on.</div>
  </div>

  <div class="card">
    <h2>Platform Telegram bot</h2>
    <div class="meta" style="margin-bottom:10px">The bot token (from @BotFather) used to send trade alerts &amp; reset codes to all users. Stored on the server only, never in code. <span id="tokStatus"></span></div>
    <div class="row">
      <div><label>Bot token</label><input id="platTok" placeholder="12345:AA... (leave blank to keep current)"/></div>
      <div style="flex:0"><label>&nbsp;</label><button id="platTokSave">Save token</button></div>
    </div>
  </div>

  <div class="card">
    <h2>Customers (<span id="count">0</span>)</h2>
    <div id="users"></div>
  </div>
</main>
<div class="toast" id="toast"></div>
<script>
const $=s=>document.querySelector(s);
function toast(m){const t=$("#toast");t.textContent=m;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),2200);}
async function api(action, body){
  const r=await fetch("/api/admin/action",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({action,...body})});
  return r.json();
}
function esc(v){ return (v==null?"":String(v)).replace(/"/g,"&quot;"); }

async function loadUsers(){
  const r=await (await fetch("/api/admin/users")).json();
  if(!r.ok){ $("#users").innerHTML="<div class='meta'>Admins only.</div>"; return; }
  $("#count").textContent=r.users.length;
  $("#users").innerHTML = r.users.map(u=>{
    const active = u.active ? '<span class="pill on">active</span>' : '<span class="pill off">inactive</span>';
    const connected = u.mt5_login ? '<span class="pill on">broker connected</span>'
                                  : '<span class="pill off">broker not set</span>';
    return `<div class="user">
      <h3>${u.email} ${active} <span class="pill">${u.role}</span> ${connected}</h3>
      <div class="meta">The customer enters their own MT5 details. On file, server: ${u.mt5_server||"-"} , instrument: ${u.instrument||"-"} , telegram: ${u.telegram_chat_id||"-"} , expires: ${u.expires_at||"-"}</div>
      <details><summary>Manage</summary>
        <div class="grid">
          <div><label>Pairs (1-5, comma-separated)</label><input id="in_${u.email}" value="${esc(u.instrument)}" placeholder="EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD"/></div>
          <div><label>Telegram chat id (alerts + reset)</label><input id="tg_${u.email}" value="${esc(u.telegram_chat_id)}" placeholder="e.g. 987654321"/></div>
          <div><label>Subdomain (for go-live)</label><input id="sd_${u.email}" value="${esc(u.subdomain)}" placeholder="e.g. jane"/></div>
          <div><label>Notes (private)</label><input id="nt_${u.email}" value="${esc(u.notes)}"/></div>
        </div>
        <div class="meta">Telegram needs the numeric <b>chat id</b> (not the @username) so the bot can message them. They can get it from a bot like @userinfobot.</div>
        <div class="actions">
          <button onclick="saveUser('${u.email}')">Save</button>
          <div style="flex:0"><label>Active until (optional)</label><input id="mu_${u.email}" placeholder="YYYY-MM-DD" style="width:150px"/></div>
          <button onclick="activate('${u.email}')">Activate</button>
          <button class="ghost" onclick="deactivate('${u.email}')">Deactivate</button>
        </div>
        <div class="meta" style="margin-top:8px">Password resets are self-service: the customer uses "Forgot password" to get a code on their Telegram.</div>
      </details>
    </div>`;
  }).join("") || "<div class='meta'>No customers yet.</div>";
}
$("#addBtn").onclick=async ()=>{
  const r=await api("create",{email:$("#newEmail").value,password:$("#newPass").value});
  if(r.ok){ toast("Customer created"); $("#newEmail").value="";$("#newPass").value=""; loadUsers(); }
  else toast(r.message||r.error||"Error");
};
async function saveUser(email){
  const g=id=>document.getElementById(id+"_"+email).value;
  const r=await api("set",{email, instrument:g("in"), telegram_chat_id:g("tg"), subdomain:g("sd"), notes:g("nt")});
  toast(r.ok?"Saved":"Error"); loadUsers();
}
async function activate(email){
  const until=document.getElementById("mu_"+email).value.trim();
  const r=await api("activate",{email, until:until||null}); toast(r.ok?"Activated":"Error"); loadUsers();
}
async function deactivate(email){ const r=await api("deactivate",{email}); toast(r.ok?"Deactivated":"Error"); loadUsers(); }

async function loadTokenStatus(){
  try{ const r=await (await fetch("/api/admin/platform-token")).json();
    $("#tokStatus").innerHTML = r.set ? '<b style="color:#137333">token is set</b>' : '<b style="color:#cb3837">not set yet</b>';
  }catch(e){}
}
$("#platTokSave").onclick=async ()=>{
  const tok=$("#platTok").value.trim(); if(!tok){ toast("Enter a token"); return; }
  const r=await (await fetch("/api/admin/platform-token",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:tok})})).json();
  if(r.ok){ $("#platTok").value=""; toast("Token saved"); loadTokenStatus(); } else toast(r.error||"Error");
};
loadTokenStatus();
loadUsers();
</script>
</body></html>
"""


# ── Single-page dashboard (no external assets, no CDN) ──────────────────────────
_INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Forex Bot , Practice</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
  /* npm-style palette: white, npm red #CB3837, light gray borders. */
  :root { --bg:#ffffff; --card:#ffffff; --ink:#262626; --muted:#696969;
          --accent:#cb3837; --good:#262626; --bad:#cb3837; --line:#e6e6e6; }
  * { box-sizing: border-box; }
  body { margin:0; font:15px/1.6 'IBM Plex Sans', Arial, sans-serif;
         background:var(--bg); color:var(--ink); }
  a { color:var(--accent); }
  /* One font for everything, including form controls (browsers override these by default). */
  input, select, textarea, button, optgroup, option {
    font-family:'IBM Plex Sans', Arial, sans-serif; }

  header { padding:0 24px; height:56px; border-bottom:1px solid var(--line);
           display:flex; align-items:center; gap:14px; }
  header .logo { background:var(--accent); color:#fff; font-weight:700; font-size:15px;
                 padding:6px 9px; letter-spacing:.3px; }
  header h1 { font-size:15px; margin:0; font-weight:600; }
  header .spacer { flex:1; }
  .badge { font-size:12px; font-weight:600; color:var(--accent); background:#fff;
           border:1px solid var(--accent); padding:3px 9px; }
  .userbox { font-size:12.5px; color:var(--muted); display:flex; align-items:center; gap:10px; }
  .userbox a { color:var(--accent); font-weight:600; text-decoration:none; }

  main { max-width:none; margin:0; padding:32px 48px; display:grid; gap:26px; }
  .intro { background:#fafafa; border:1px solid var(--line);
           padding:20px 22px; color:var(--ink); font-size:14px; }
  .card { background:var(--card); border:1px solid var(--line); padding:28px 30px; }
  .step { display:flex; align-items:center; gap:12px; margin:0 0 6px; }
  .step .num { width:26px; height:26px; background:var(--accent);
    color:#fff; font-weight:700; font-size:13px; display:flex; align-items:center; justify-content:center; }
  .card h2 { font-size:17px; margin:0; font-weight:600; }
  p.sub { margin:4px 0 22px 38px; color:var(--muted); font-size:13.5px; }
  label { display:block; font-size:12.5px; color:var(--ink); font-weight:600; margin-bottom:7px; }
  input, select { width:100%; padding:11px 12px; background:#fff; color:var(--ink);
    border:1px solid #d1d5da; border-radius:0; font-size:14px; }
  input:focus, select:focus { outline:none; border-color:var(--accent); box-shadow:0 0 0 2px rgba(203,56,55,.2); }
  .row { display:flex; gap:20px; flex-wrap:wrap; align-items:end; }
  .row > div { flex:1; min-width:150px; }
  button { background:var(--accent); color:#fff; border:1px solid var(--accent); padding:11px 20px;
    border-radius:0; font-size:14px; font-weight:600; cursor:pointer; }
  button:hover { background:#b02a2a; border-color:#b02a2a; }
  button.big { width:100%; padding:15px; font-size:15px; margin-top:6px; }
  button.ghost { background:#fff; border:1px solid #d1d5da; color:var(--ink); }
  button.ghost:hover { background:#f6f6f6; }
  button:disabled { opacity:.6; cursor:default; }
  @keyframes fxspin { to { transform: rotate(360deg); } }
  .spin { display:inline-block; width:13px; height:13px; border:2px solid rgba(255,255,255,.45);
    border-top-color:#fff; border-radius:50%; animation:fxspin .7s linear infinite;
    vertical-align:-2px; margin-right:7px; }
  .spin.dark { border-color:rgba(0,0,0,.2); border-top-color:var(--accent); }
  .loading { color:var(--muted); font-size:13px; padding:10px 0; }
  .hint { font-size:12.5px; color:var(--muted); margin-top:8px; }

  /* Info marker + tooltip (functional, needed for the hover help) */
  .info { display:inline-flex; align-items:center; justify-content:center; width:15px; height:15px;
    background:#fff; color:var(--accent); border:1px solid var(--accent); font-size:10px; font-weight:700;
    cursor:help; position:relative; margin-left:5px; vertical-align:middle; font-style:normal; }
  .info:hover, .info:focus { background:var(--accent); color:#fff; outline:none; }
  .info::after { content:attr(data-tip); position:absolute; bottom:150%; left:50%;
    transform:translateX(-50%); background:#fff; color:var(--ink); border:1px solid var(--line);
    padding:10px 12px; width:250px; font-size:12.5px; line-height:1.5;
    font-weight:400; text-align:left; opacity:0; pointer-events:none; transition:.12s; z-index:20;
    box-shadow:0 3px 10px rgba(0,0,0,.15); border-radius:0; }
  .info:hover::after, .info:focus::after { opacity:1; }
  @media (max-width:560px){ .info::after{ width:200px; left:auto; right:0; transform:none; } }

  .stats { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:16px; margin-top:20px; }
  .stat { background:#fafafa; border:1px solid var(--line); padding:18px; border-radius:0; }
  .stat .n { font-size:22px; font-weight:700; }
  .stat .l { font-size:11.5px; color:var(--muted); margin-top:2px; }
  .good { color:var(--good); } .bad { color:var(--bad); }
  .verdict { font-size:16px; font-weight:600; margin-top:22px; padding:18px 20px;
    background:#fafafa; border:1px solid var(--line); border-left:4px solid var(--accent); border-radius:0; }
  img { width:100%; border-radius:0; margin-top:20px; border:1px solid var(--line); }
  table { width:100%; border-collapse:collapse; font-size:13px; margin-top:16px; }
  th,td { text-align:right; padding:11px 10px; border-bottom:1px solid var(--line); }
  th { border-bottom:2px solid var(--ink); font-weight:600; }
  th:first-child, td:first-child { text-align:left; }
  details { margin-top:10px; }
  summary { cursor:pointer; color:var(--accent); font-weight:600; font-size:13.5px; padding:8px 0; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:18px; margin-top:16px; }
  .warn { background:#fff; border:1px solid var(--accent); border-left:4px solid var(--accent);
    color:var(--ink); font-size:12.5px; padding:10px 12px; margin:10px 0; border-radius:0; }
  .toast { position:fixed; bottom:20px; left:50%; transform:translateX(-50%);
    background:var(--ink); color:#fff; padding:11px 18px;
    border-radius:0; opacity:0; transition:.3s; pointer-events:none; z-index:50; }
  .toast.show { opacity:1; }

  /* Top mode switcher */
  .tabs { display:flex; gap:0; border-bottom:2px solid var(--line); overflow-x:auto; }
  .tab { background:#fff; color:var(--muted); border:0; border-bottom:3px solid transparent;
    padding:14px 22px; font-size:14px; font-weight:600; cursor:pointer; border-radius:0; white-space:nowrap; }
  .tab:hover { color:var(--ink); background:#fff; }
  .tab.active { color:var(--accent); border-bottom-color:var(--accent); }
  .view { display:grid; gap:26px; }
  .view[hidden] { display:none; }

  /* Live/practice status panel */
  .statusbar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:16px; }
  .dot { width:10px; height:10px; background:var(--muted); display:inline-block; }
  .dot.on { background:#137333; }
  .dot.off { background:var(--accent); }
  .kpis { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:14px; margin:16px 0; }
  .logbox { background:#1b1f23; color:#e6edf3; font:12.5px/1.6 'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace;
    padding:14px 16px; height:220px; overflow:auto; white-space:pre-wrap; border:1px solid var(--ink); }
  .chartwrap { border:1px solid var(--line); padding:12px; margin-bottom:16px; }
  .chart { width:100%; height:240px; display:block; }
  .legend { display:flex; gap:16px; font-size:11.5px; color:var(--muted); margin-top:10px; flex-wrap:wrap; }
  .legend i { display:inline-block; width:12px; height:3px; margin-right:5px; vertical-align:middle; }
  .banner { padding:14px 16px; border:1px solid var(--line); border-left:4px solid var(--accent);
    background:#fafafa; font-size:13.5px; margin-bottom:16px; }

  /* Phone-friendly */
  @media (max-width:720px){
    header { padding:0 16px; }
    main { padding:18px 16px; gap:20px; }
    .card { padding:18px 16px; }
    p.sub { margin-left:0; }
    .tab { padding:12px 16px; }
    .row > div { min-width:100%; }
    .row > div[style*="flex:0"] { min-width:0; }
    button.big { padding:14px; }
    .info::after { width:min(78vw,250px); }
  }
</style>
</head>
<body>
<header>
  <span class="logo">fx</span>
  <h1>Forex Bot</h1>
  <span class="spacer"></span>
  <span class="badge">Practice mode, no real money</span>
  <span id="userbox" class="userbox"></span>
</header>
<main>

  <div class="intro">
    This is a safe <b>practice tool</b>. It replays <b>real past prices</b> to show how a set of
    trading rules <i>would have</i> performed, like a flight simulator. Nothing here touches real
    money or connects to any bank or broker. Hover any <span class="info" data-tip="Hover these markers anywhere on the page to get a plain-English explanation.">i</span>
    marker for a plain-English explanation.
  </div>

  <div class="tabs">
    <button class="tab active" data-mode="backtest">Backtest</button>
    <button class="tab" data-mode="account">Account</button>
    <button class="tab" data-mode="practice">Practice</button>
    <button class="tab" data-mode="live">Live</button>
    <button class="tab" data-mode="history">History</button>
  </div>

  <div id="view-backtest" class="view">

  <!-- STEP 1 -->
  <div class="card">
    <div class="step"><span class="num">1</span><h2>Pick what to test</h2></div>
    <p class="sub">Download real historical prices. It's free and needs no account.</p>
    <div class="row">
      <div>
        <label>Currency pair
          <span class="info" data-tip="Two currencies compared, like Euro vs US Dollar (EURUSD). The bot tries to profit from the price moving up or down.">i</span>
        </label>
        <select id="pair"></select>
      </div>
      <div>
        <label>Timeframe
          <span class="info" data-tip="How much time each price 'bar' covers. '1 day' = one bar per day (calmer, fewer signals). '1 hour' = busier and noisier. Daily often works better for these rules.">i</span>
        </label>
        <select id="interval"></select>
      </div>
      <div>
        <label>How much history
          <span class="info" data-tip="How far back to pull prices for the test. More history = a more trustworthy result.">i</span>
        </label>
        <select id="period">
          <option>60d</option><option>1y</option><option selected>2y</option>
          <option>5y</option><option>10y</option>
        </select>
      </div>
      <div style="flex:0"><label>&nbsp;</label><button id="fetchBtn">Download</button></div>
    </div>
    <div class="hint" id="fetchHint">Good starting point: <b>EURUSD</b>, <b>1d</b>, <b>10y</b>. Already downloaded some? Just move to step 2.</div>
    <div id="fetchStatus"></div>
  </div>

  <!-- STEP 2 -->
  <div class="card">
    <div class="step"><span class="num">2</span><h2>Run the test</h2></div>
    <p class="sub">See how the rules would have done on the prices you picked.</p>
    <div class="row">
      <div>
        <label>Which data
          <span class="info" data-tip="The price history to test on. Files you downloaded in step 1 appear here.">i</span>
        </label>
        <select id="btFile"></select>
      </div>
      <div>
        <label>Which rules
          <span class="info" data-tip="The set of buy/sell rules to test. 'my_formula' is your editable formula (see step 4).">i</span>
        </label>
        <select id="btStrategy"></select>
      </div>
      <div style="flex:0"><label>&nbsp;</label><button id="refreshBtn" class="ghost" title="Reload the data list">Refresh</button></div>
    </div>
    <div style="margin-top:14px"><button id="btBtn" class="big">Run the Test</button></div>
    <div class="hint">Uses whatever is set in <b>Step 4, Your formula</b> below.</div>
    <div id="btOut"></div>
  </div>

  <!-- STEP 3 -->
  <div class="card">
    <div class="step"><span class="num">3</span><h2>Auto-improve <span style="font-weight:400;color:var(--muted);font-size:13px">(optional)</span></h2></div>
    <p class="sub">Let the computer try many settings and show which did best on your data.</p>
    <div class="row">
      <div>
        <label>Which data
          <span class="info" data-tip="The price history to search over. Use the same file you tested in step 2.">i</span>
        </label>
        <select id="optFile"></select>
      </div>
      <div style="flex:0"><label>&nbsp;</label><button id="optBtn" class="ghost">Find Best Settings</button></div>
    </div>
    <div class="warn">"Best on past data" is <b>not</b> a promise about the future. Use this as a
      starting point, then always re-test. Good results here never mean guaranteed profit.</div>
    <div id="optOut"></div>
  </div>

  <!-- STEP 4: THE FORMULA (a simple form , no code) -->
  <div class="card">
    <div class="step"><span class="num">4</span><h2>Your formula
      <span class="info" data-tip="These choices ARE the formula: which trend lines to use, whether to add a momentum filter, how the safety stop works, and how much to risk. Fill in values , no coding.">i</span></h2></div>
    <p class="sub">New here? Start with a ready-made recipe, then press <b>Run the Test</b>.
      Or fine-tune the boxes yourself, hover any info marker for what it means.</p>
    <div style="background:#fafafa;border:1px solid var(--line);padding:14px 15px;margin-bottom:6px">
      <label>Start from a ready-made recipe
        <span class="info" data-tip="Each recipe fills in every box below with sensible values. Pick one, then just press Run the Test. You can adjust afterwards.">i</span>
      </label>
      <select id="preset"><option value="">choose a starting point</option></select>
      <div id="presetDesc" class="hint"></div>
    </div>
    <div id="formula"></div>
    <div style="margin-top:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <button id="saveBtn">Save formula</button>
      <button id="resetBtn" class="ghost">Reset to defaults</button>
      <span id="formulaStatus" class="hint" style="margin:0"></span>
    </div>
  </div>

  </div><!-- /view-backtest -->

  <!-- ACCOUNT (broker connection, telegram, password) -->
  <div id="view-account" class="view" hidden>
    <div class="card">
      <div class="step"><span class="num">A</span><h2>Account</h2></div>
      <p class="sub">Your subscription and connection details live here.</p>
      <div id="acctInfo" class="banner">Loading...</div>
    </div>

    <div class="card">
      <h2 style="font-size:16px;margin:0 0 4px">Broker connection
        <span class="info" data-tip="You enter your own MT5 account. We never see or hold your money, you deposit and withdraw at your broker.">i</span></h2>
      <p class="sub" style="margin-left:0">Enter your own MetaTrader 5 details. Start with a DEMO account.</p>
      <div class="grid">
        <div><label>MT5 login
          <span class="info" data-tip="Your MT5 account NUMBER (e.g. 51234567). Your broker gives you this when you open the account.">i</span>
        </label><input id="mb_login"/></div>
        <div><label>MT5 password
          <span class="info" data-tip="Your MT5 trading password, the one you use to log into the MetaTrader 5 app. NOT your broker website login.">i</span>
        </label><input id="mb_password" type="password" placeholder="(unchanged)"/></div>
        <div><label>MT5 server
          <span class="info" data-tip="Your broker's server name, shown in the MT5 app on your account, e.g. ICMarkets-Demo or Exness-MT5Real.">i</span>
        </label><input id="mb_server" placeholder="e.g. ICMarkets-Demo"/></div>
        <div><label>Telegram chat id
          <span class="info" data-tip="A number (not your phone or @username) so the bot can send you trade alerts and password-reset codes.">i</span>
        </label><input id="mb_telegram"/></div>
        <div><label>Pairs to trade
          <span class="info" data-tip="The pair(s) the bot scans for setups. Enter one (EURUSD) or up to five, comma-separated (EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD). The bot checks each one and trades whichever gives a setup — one position per pair.">i</span>
        </label><input id="mb_instrument" placeholder="EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD"/></div>
      </div>
      <div class="banner" style="margin-top:12px">
        <b>Where to find your MT5 details</b>
        <ol style="margin:8px 0 0; padding-left:20px; font-size:13px; color:var(--muted)">
          <li>Install <b>MetaTrader 5</b> and open your broker account inside it.</li>
          <li>Your <b>login</b> (account number) and <b>server</b> are shown on the account (Tools &rarr; Options &rarr; or the account list).</li>
          <li>The <b>password</b> is the one you set when the account was created.</li>
          <li>Start with a <b>DEMO</b> account, the server name usually ends in "-Demo".</li>
        </ol>
      </div>
      <div class="banner" style="border-left-color:#137333;margin-top:12px">
        <b>How to get your Telegram chat id</b>
        <ol style="margin:8px 0 0; padding-left:20px; font-size:13px; color:var(--muted)">
          <li>Open Telegram and search for <b>@userinfobot</b>.</li>
          <li>Press <b>Start</b>, it instantly replies with your <b>Id</b> (a number like 872148198).</li>
          <li>Paste that number above and save.</li>
          <li>Also open <b>our bot</b> and press <b>Start</b> once, so it's allowed to message you.</li>
        </ol>
      </div>
      <div style="margin-top:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <button id="mbSave">Save broker details</button>
        <button id="tgTest" class="ghost">Send test Telegram alert</button>
        <span id="mbStatus" class="hint" style="margin:0"></span>
      </div>
    </div>

    <div class="card">
      <h2 style="font-size:16px;margin:0 0 12px">Change password</h2>
      <div class="row">
        <div><label>Current password</label><input id="pwCur" type="password"/></div>
        <div><label>New password</label><input id="pwNew" type="password" placeholder="min 8 characters"/></div>
        <div style="flex:0"><label>&nbsp;</label><button id="pwSave">Update password</button></div>
      </div>
      <div id="pwStatus" class="hint"></div>
    </div>
  </div>

  <!-- PRACTICE (paper trading on the simulator) -->
  <div id="view-practice" class="view" hidden>
    <div class="card">
      <div class="step"><span class="num">P</span><h2>Practice (paper trading)
        <span class="info" data-tip="Runs your formula forward on simulated prices with fake money. No broker or account needed. This is the safest way to watch how the bot behaves.">i</span></h2></div>
      <p class="sub">Watch the bot trade in real time with fake money. Uses your current
        formula from the Backtest tab. Nothing here is real.</p>
      <div class="row">
        <div>
          <label>Data to play through
            <span class="info" data-tip="The price history the practice run will step through, one bar at a time.">i</span>
          </label>
          <select id="pracFile"></select>
        </div>
        <div>
          <label>Speed
            <span class="info" data-tip="How fast to step through the bars so you can watch.">i</span>
          </label>
          <select id="pracTick">
            <option value="0.3">Fast</option>
            <option value="0.7" selected>Normal</option>
            <option value="1.5">Slow</option>
          </select>
        </div>
        <div style="flex:0"><label>&nbsp;</label><button id="pracStart">Start</button></div>
        <div style="flex:0"><label>&nbsp;</label><button id="pracStop" class="ghost">Stop</button></div>
      </div>
      <div id="pracPanel" style="margin-top:18px"></div>
    </div>
  </div>

  <!-- LIVE (real broker via MT5) -->
  <div id="view-live" class="view" hidden>
    <div class="card">
      <div class="step"><span class="num">L</span><h2>Live trading
        <span class="info" data-tip="Connects to your real MetaTrader 5 broker. Whether it is a demo (fake money) or funded (real money) account depends on which account your MT5 terminal is logged into.">i</span></h2></div>
      <p class="sub">Connects to your MetaTrader 5 broker. Use a DEMO account first. Real
        money only after the strategy has proven itself.</p>
      <div id="liveReady" class="banner">Checking connection...</div>
      <div class="row">
        <div style="flex:0">
          <label>Safety
            <span class="info" data-tip="Dry-run connects and shows what it WOULD do, without placing any orders. Always start here.">i</span>
          </label>
          <select id="liveDry">
            <option value="true" selected>Dry-run (no orders)</option>
            <option value="false">Place real orders</option>
          </select>
        </div>
        <div style="flex:0"><label>&nbsp;</label><button id="liveStart">Start</button></div>
        <div style="flex:0"><label>&nbsp;</label><button id="liveStop" class="ghost">Stop</button></div>
      </div>
      <div id="livePanel" style="margin-top:18px"></div>
    </div>
  </div>

  <!-- HISTORY (per-account trade record + download) -->
  <div id="view-history" class="view" hidden>
    <div class="card">
      <div class="step"><span class="num">H</span><h2>Trade history</h2></div>
      <p class="sub">Every completed trade on your account (practice and live).</p>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:6px">
        <a href="/api/my-history.csv"><button>Download CSV</button></a>
        <button id="histRefresh" class="ghost">Refresh</button>
        <span id="histSummary" class="hint" style="margin:0"></span>
      </div>
      <div id="histTable"></div>
    </div>
  </div>

</main>
<div class="toast" id="toast"></div>

<script>
const $ = s => document.querySelector(s);
let STATE = null;
let ROLE = "user";

// Tooltip text for each result number (this is where newbies get lost).
const TIP = {
  net:"Profit or loss in dollars, on the pretend practice balance. Green = made money, red = lost money.",
  ret:"The profit or loss as a percentage of the starting balance.",
  trades:"How many completed buy/sell trades happened during the test.",
  win:"The share of trades that made money. Note: a LOW win rate can still be profitable if the wins are bigger than the losses.",
  pf:"Profit factor = total money won ÷ total money lost. Above 1.0 means profitable overall. 1.5 or higher is good.",
  dd:"Max drawdown = the worst drop from a high point during the test , how far 'down' you'd have been at the scariest moment. Lower is safer."
};

function toast(msg){ const t=$("#toast"); t.textContent=msg; t.classList.add("show");
  setTimeout(()=>t.classList.remove("show"), 2400); }
function busy(btn, label){ if(!btn) return; btn.disabled=true; btn.dataset.orig=btn.innerHTML;
  const dark = btn.classList.contains("ghost") ? " dark" : "";
  btn.innerHTML = `<span class="spin${dark}"></span>${label||"Working..."}`; }
function unbusy(btn){ if(!btn) return; btn.disabled=false;
  if(btn.dataset.orig!=null){ btn.innerHTML=btn.dataset.orig; } }
function loadingBox(el, msg){ if(el) el.innerHTML = `<div class="loading"><span class="spin dark"></span>${msg||"Loading..."}</div>`; }

function opts(sel, arr, sel0){ sel.innerHTML=""; arr.forEach(v=>{ const o=document.createElement("option");
  o.value=v; o.textContent=v; if(v===sel0)o.selected=true; sel.appendChild(o); }); }

async function load(){
  STATE = await (await fetch("/api/state")).json();
  try{ const me=await (await fetch("/api/me")).json();
    if(me.email){ ROLE=me.role||"user";
      const adminLink = ROLE==="admin" ? '<a href="/admin">Admin</a>' : '';
      $("#userbox").innerHTML = `<span>${me.email}</span>${adminLink}<a href="/logout">Log out</a>`; }
  }catch(e){}
  if(ROLE!=="admin"){
    // Customers don't get the research tools; they only manage their account + run the bot.
    const bt=document.querySelector('.tab[data-mode="backtest"]');
    if(bt) bt.style.display="none";
    document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));
    document.querySelector('.tab[data-mode="account"]').classList.add("active");
    $("#view-backtest").hidden=true;
    $("#view-account").hidden=false;
    loadAccount();
  }
  opts($("#pair"), STATE.pairs, "EURUSD");
  opts($("#interval"), STATE.intervals, "1d");

  renderFormula();
  renderPresets();
  refreshFiles();
  opts($("#btStrategy"), STATE.strategies, STATE.config.STRATEGY);
  resumeLive();  // if the bot is already running server-side, re-attach after refresh
}

// After a browser refresh the bot keeps running on the server; re-connect the UI to it
// so the live panel, open trades and log show again instead of starting blank.
async function resumeLive(){
  try{
    const s=await (await fetch("/api/live/state")).json();
    if(s.running){
      const mode = s.mode==="practice" ? "practice" : "live";
      const tab = document.querySelector('.tab[data-mode="'+mode+'"]');
      if(tab) tab.click();                 // switch to the running mode's tab
      startPolling(mode==="practice" ? "pracPanel" : "livePanel");
    }
  }catch(e){}
}

function renderPresets(){
  const sel=$("#preset");
  (STATE.presets||[]).forEach((p,idx)=>{ const o=document.createElement("option");
    o.value=String(idx); o.textContent=p.name; sel.appendChild(o); });
  sel.onchange=()=>{
    const p=STATE.presets[sel.value];
    if(!p){ $("#presetDesc").textContent=""; return; }
    Object.entries(p.values).forEach(([k,v])=>{ const el=$("#set_"+k); if(el) el.value=String(v); });
    $("#presetDesc").innerHTML = `<b>${p.name}:</b> ${p.desc} <span style="color:var(--good)">Filled in below , press Save formula or Run the Test.</span>`;
    toast("Recipe loaded: "+p.name);
  };
}

function fieldHtml(s){
  const tip = s.help.replace(/"/g,'&quot;');
  const cur = String(STATE.config[s.key]);
  let control;
  if(s.kind==="choice"){
    control = `<select id="set_${s.key}">` +
      s.options.map(o=>`<option value="${o}" ${o===cur?"selected":""}>${o.toUpperCase()}</option>`).join("") +
      `</select>`;
  } else if(s.kind==="bool"){
    control = `<select id="set_${s.key}">
      <option value="true" ${cur==="true"?"selected":""}>Yes</option>
      <option value="false" ${cur==="false"?"selected":""}>No</option></select>`;
  } else {
    control = `<input id="set_${s.key}" value="${cur}"/>`;
  }
  return `<div><label>${s.label}<span class="info" data-tip="${tip}">i</span></label>${control}</div>`;
}

function renderFormula(){
  const box = $("#formula"); box.innerHTML="";
  const groups = {};
  STATE.settings.forEach(s=>{ (groups[s.group]=groups[s.group]||[]).push(s); });
  Object.keys(groups).forEach(g=>{
    const head=document.createElement("div");
    head.style.cssText="font-size:12px;letter-spacing:.5px;text-transform:uppercase;color:var(--accent);margin:14px 0 6px;font-weight:700";
    head.textContent=g;
    box.appendChild(head);
    const grid=document.createElement("div"); grid.className="grid";
    grid.innerHTML = groups[g].map(fieldHtml).join("");
    box.appendChild(grid);
  });
}

function gatherFormula(){
  const body={}; STATE.settings.forEach(s=>{ const el=$("#set_"+s.key); if(el) body[s.key]=el.value; });
  return body;
}

function refreshFiles(){
  const files = STATE.datafiles || [];
  const list = ["__synthetic__ (sample data)"].concat(files);
  [ $("#btFile"), $("#optFile") ].forEach(sel=>{
    sel.innerHTML="";
    list.forEach(f=>{ const o=document.createElement("option");
      o.value = f.startsWith("__synthetic__")?"__synthetic__":f;
      o.textContent=f; sel.appendChild(o); });
    if(files.length){ sel.value = files[files.length-1]; }
  });
}

async function reloadState(){ STATE = await (await fetch("/api/state")).json(); refreshFiles(); }

$("#refreshBtn").onclick = async ()=>{ await reloadState(); toast("Data list refreshed"); };

$("#fetchBtn").onclick = async ()=>{
  const b=$("#fetchBtn"); busy(b,"Downloading...");
  const st=$("#fetchStatus"); loadingBox(st, "Fetching real market prices...");
  // Yahoo only serves ~2 years of intraday history , warn before trying.
  const iv=$("#interval").value, pd=$("#period").value;
  if(iv!=="1d" && ["5y","10y"].includes(pd)){
    st.innerHTML=`<div class="warn">Heads up: for ${iv} bars, providers usually cap history near 2 years. Try <b>1d</b> for 5–10 years.</div>`;
  }
  try{
    const r = await (await fetch("/api/fetch",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({pair:$("#pair").value, interval:iv, period:pd})})).json();
    if(r.ok){
      await reloadState();
      $("#btFile").value = r.file; $("#optFile").value = r.file;
      st.innerHTML=`<div class="verdict" style="margin-top:12px">Downloaded <b>${r.candles}</b> price bars into <b>${r.file}</b>.
        <div style="font-weight:400;color:var(--muted);font-size:13px;margin-top:6px">It's now selected in step 2. Scroll down and press <b>Run the Test</b>.</div></div>`;
      toast("Ready to test "+r.file);
    } else {
      st.innerHTML=`<div class="warn">Couldn't download: ${r.error}</div>`;
    }
  } catch(e){ st.innerHTML=`<div class="warn">Download failed: ${e}</div>`; }
  finally { unbusy(b); }
};

async function saveFormula(){
  await fetch("/api/save-config",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(gatherFormula())});
}
$("#saveBtn").onclick = async ()=>{
  const b=$("#saveBtn"); busy(b,"Saving...");
  try{ await saveFormula();
    const st=$("#formulaStatus"); st.style.color="var(--good)"; st.textContent="Formula saved.";
    toast("Formula saved");
  } finally { unbusy(b); }
};
$("#resetBtn").onclick = async ()=>{
  const defaults={}; STATE.settings.forEach(s=> defaults[s.key]=String(s.default ?? ""));
  // Defaults live server-side; simplest reliable reset is to re-read + repaint current, then
  // set each control to its documented default via the settings list.
  STATE.settings.forEach(s=>{ const el=$("#set_"+s.key); if(el && s.default!==undefined) el.value=String(s.default); });
  toast("Reset. Press Save formula to keep");
};

function stat(label, val, tipKey, cls){
  return `<div class="stat"><div class="n ${cls||''}">${val}</div>
    <div class="l">${label}<span class="info" data-tip="${TIP[tipKey]}">i</span></div></div>`;
}

$("#btBtn").onclick = async ()=>{
  const b=$("#btBtn"); busy(b,"Running the test...");
  loadingBox($("#btOut"), "Crunching the numbers...");
  try{
    // Save the formula form first, so the test uses exactly what's on screen.
    await saveFormula();
    const r = await (await fetch("/api/backtest",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({file:$("#btFile").value, strategy:$("#btStrategy").value})})).json();
    if(!r.ok){ toast("Error: "+r.error); $("#btOut").innerHTML=`<div class="warn">${r.error}</div>`; return; }
    const s=r.result; const good=s.net_pnl>=0; const cls=good?"good":"bad";
    const verdict = good
      ? `On this past data, these rules <b>made money</b> (+$${s.net_pnl}).`
      : `On this past data, these rules <b>lost money</b> ($${s.net_pnl}).`;
    $("#btOut").innerHTML =
      `<div class="verdict">${verdict}<div style="font-weight:400;color:var(--muted);font-size:13px;margin-top:6px">
        Remember: past results never guarantee the future. This is practice only.</div></div>
      <div class="stats">
        ${stat("Profit / Loss ($)", (good?"+":"")+s.net_pnl, "net", cls)}
        ${stat("Return (%)", (s.return_pct>=0?"+":"")+s.return_pct+"%", "ret", cls)}
        ${stat("Trades", s.trades, "trades")}
        ${stat("Win rate", s.win_rate+"%", "win")}
        ${stat("Profit factor", s.profit_factor??"∞", "pf")}
        ${stat("Worst dip", s.max_drawdown_pct+"%", "dd", "bad")}
      </div>
      <div class="hint">Tested on ${s.source}, ${s.candles} price bars, practice balance $${s.start_balance} to $${s.end_balance}</div>
      ${r.has_image?`<img src="/api/equity.png?t=${Date.now()}" alt="account balance over time"/>`:""}`;
  } catch(e){ toast("Error running test"); $("#btOut").innerHTML=""; }
  finally { unbusy(b); }
};

$("#optBtn").onclick = async ()=>{
  const b=$("#optBtn"); busy(b,"Searching...");
  loadingBox($("#optOut"), "Trying many settings, this can take a moment...");
  try{
    const r = await (await fetch("/api/optimize",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({file:$("#optFile").value})})).json();
    if(!r.ok){ toast("Error: "+r.error); $("#optOut").innerHTML=`<div class="warn">${r.error}</div>`; return; }
    if(!r.rows.length){ $("#optOut").innerHTML="<div class='hint'>No setting made enough trades to judge. Try more history.</div>"; return; }
    let html = "<table><tr><th>Settings it tried</th><th>Profit/Loss</th><th>Profit factor</th><th>Win%</th><th>Trades</th></tr>";
    r.rows.forEach(row=>{
      const p=row.params; const cls=row.net_pnl>=0?"good":"bad";
      const ps=Object.entries(p).map(([k,v])=>`${k}=${v}`).join(", ");
      html += `<tr><td>${ps}</td><td class="${cls}">${row.net_pnl}</td><td>${row.profit_factor??"∞"}</td><td>${row.win_rate}%</td><td>${row.trades}</td></tr>`;
    });
    html += "</table><div style='margin-top:12px'><button class='ghost' id='applyBest'>Use the best settings</button></div>";
    $("#optOut").innerHTML = html;
    $("#applyBest").onclick = ()=>{
      const best=r.best; if(!best) return;
      const map={range_lookback:"CRT_RANGE_LOOKBACK",target_mode:"CRT_TARGET_MODE",risk_reward:"CRT_RISK_REWARD",min_rr:"CRT_MIN_RR",stop_buffer_pct:"CRT_STOP_BUFFER_PCT"};
      Object.entries(best).forEach(([k,v])=>{ const el=document.getElementById("set_"+(map[k]||k.toUpperCase())); if(el) el.value=v; });
      const st=$("#formulaStatus"); st.style.color="var(--muted)"; st.textContent="Best settings filled into Step 4, review, then Save / Run.";
      $("#formula").scrollIntoView({behavior:"smooth"});
      toast("Filled into Step 4, review, then Run the Test");
    };
  } catch(e){ toast("Error"); $("#optOut").innerHTML=""; }
  finally { unbusy(b); }
};

// ── Mode switcher (Backtest / Practice / Live) ──
document.querySelectorAll(".tab").forEach(t=>t.onclick=()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));
  t.classList.add("active");
  const mode=t.dataset.mode;
  $("#view-backtest").hidden = mode!=="backtest";
  $("#view-account").hidden = mode!=="account";
  $("#view-practice").hidden = mode!=="practice";
  $("#view-live").hidden = mode!=="live";
  $("#view-history").hidden = mode!=="history";
  if(mode==="account") loadAccount();
  if(mode==="practice") fillPracFiles();
  if(mode==="live") checkLiveReady();
  if(mode==="history") loadHistory();
});

async function loadHistory(){
  loadingBox($("#histTable"), "Loading your trades...");
  // Show the CURRENT open trade (if any) at the top, pulled from the live run.
  let openHtml="";
  try{
    const st=await (await fetch("/api/live/state")).json();
    const ps=st.positions||(st.position?[st.position]:[]);
    if(ps.length){
      openHtml=`<div class="verdict" style="border-left-color:#137333"><b>Open now (${ps.length}):</b>`+
        ps.map(p=>{const uc=(p.unrealized||0)>=0?"good":"bad";
          return `<div style="padding:3px 0">${p.side} ${p.units} ${p.symbol||st.instrument||""} @ ${p.entry}, `+
            `stop ${p.stop}, target ${p.target??"none"}, `+
            `<span class="${uc}">${p.unrealized>=0?"+":""}${p.unrealized}</span></div>`;}).join("")+
        `</div>`;
    } else if(st.running){ openHtml=`<div class="hint">No open trade right now (bot is running, waiting for a setup).</div>`; }
  }catch(e){}
  const r=await (await fetch("/api/my-history")).json();
  const ts=r.trades||[];
  const wins=ts.filter(t=>(t.pnl||0)>0).length;
  const pnl=ts.reduce((a,t)=>a+(t.pnl||0),0);
  $("#histSummary").textContent = ts.length
    ? `${ts.length} trades, ${wins} winners, net ${pnl>=0?"+":""}${pnl.toFixed(2)}`
    : "No closed trades yet.";
  if(!ts.length){ $("#histTable").innerHTML=openHtml; return; }
  let h="<table><tr><th>Closed</th><th>Mode</th><th>Pair</th><th>Side</th><th>Units</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Reason</th></tr>";
  ts.forEach(t=>{ const cls=(t.pnl||0)>=0?"good":"bad";
    h+=`<tr><td>${(t.closed_at||"").replace("T"," ").slice(0,16)}</td><td>${t.mode||""}</td>`+
       `<td>${t.instrument||""}</td><td>${t.side||""}</td><td>${t.units??""}</td>`+
       `<td>${t.entry??""}</td><td>${t.exit??""}</td>`+
       `<td class="${cls}">${(t.pnl>=0?"+":"")+(t.pnl??0)}</td><td>${t.exit_reason||t.reason||""}</td></tr>`; });
  h+="</table>"; $("#histTable").innerHTML=openHtml+h;
}
$("#histRefresh").onclick=loadHistory;

async function loadAccount(){
  try{
    const s=await (await fetch("/api/my-broker")).json();
    const me=await (await fetch("/api/me")).json();
    $("#mb_login").value=s.mt5_login||""; $("#mb_server").value=s.mt5_server||"";
    $("#mb_telegram").value=s.telegram_chat_id||"";
    $("#mb_instrument").value=s.instrument||"";
    $("#mb_password").placeholder = s.has_password ? "(saved, leave blank to keep)" : "your MT5 password";
    const sub = s.active ? '<b style="color:#137333">Active</b>'
                         : '<b style="color:#cb3837">Inactive</b>';
    $("#acctInfo").innerHTML = `Email: <b>${me.email}</b><br>Subscription: ${sub}` +
      (s.expires_at ? ` (until ${s.expires_at.slice(0,10)})` : "") +
      (s.active ? "" : "<br>Contact support to activate your subscription.");
  }catch(e){}
}
$("#pwSave").onclick=async ()=>{
  const b=$("#pwSave"); busy(b,"Updating...");
  try{
    const r=await (await fetch("/api/my-password",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({current:$("#pwCur").value, new:$("#pwNew").value})})).json();
    const st=$("#pwStatus");
    if(r.ok){ st.style.color="var(--good)"; st.textContent="Password updated.";
      $("#pwCur").value=""; $("#pwNew").value=""; toast("Password updated"); }
    else { st.style.color="var(--bad)"; st.textContent=r.error; }
  } finally { unbusy(b); }
};

$("#mbSave").onclick=async ()=>{
  const b=$("#mbSave"); busy(b,"Saving...");
  try{
    const body={mt5_login:$("#mb_login").value, mt5_server:$("#mb_server").value,
      telegram_chat_id:$("#mb_telegram").value, instrument:$("#mb_instrument").value};
    const pw=$("#mb_password").value; if(pw) body.mt5_password=pw;
    await fetch("/api/my-broker",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    $("#mbStatus").textContent="Saved."; toast("Broker details saved"); loadAccount();
  } finally { unbusy(b); }
};
$("#tgTest").onclick=async ()=>{
  const b=$("#tgTest"); busy(b,"Sending...");
  try{
    const r=await (await fetch("/api/test-telegram",{method:"POST"})).json();
    const st=$("#mbStatus");
    if(r.ok){ st.style.color="var(--good)"; st.textContent="Test alert sent, check Telegram."; toast("Sent"); }
    else { st.style.color="var(--bad)"; st.textContent=r.error; toast("Not sent"); }
  } finally { unbusy(b); }
};

function fillPracFiles(){
  const pf=$("#pracFile"); if(!pf) return; pf.innerHTML="";
  ["__synthetic__ (sample data)"].concat(STATE.datafiles||[]).forEach(f=>{
    const o=document.createElement("option");
    o.value=f.startsWith("__synthetic__")?"__synthetic__":f; o.textContent=f; pf.appendChild(o); });
  if((STATE.datafiles||[]).length) pf.value=STATE.datafiles[STATE.datafiles.length-1];
}

// ── Live/practice status rendering + polling ──
let pollTimer=null, pollTarget=null;
function renderPanel(el, s){
  const on=s.running;
  const pnlCls=s.pnl>=0?"good":"bad";
  const ps=s.positions||(s.position?[s.position]:[]);
  let pos = ps.length ? ps.map(p=>{ const uc=(p.unrealized||0)>=0?"good":"bad";
      return `<div style="padding:4px 0">`+
        `<b>${p.side}</b> ${p.units} ${p.symbol||s.instrument} @ ${p.entry}, `+
        `stop ${p.stop}, target ${p.target??"none"}, `+
        `<span class="${uc}">unrealized ${p.unrealized>=0?"+":""}$${p.unrealized}</span></div>`;
    }).join("") : '<span class="hint">No open trades right now.</span>';
  el.innerHTML=`
    <div class="statusbar">
      <span class="dot ${on?"on":(s.finished?"off":"")}"></span>
      <b>${on?"Running":(s.finished?"Stopped":"Idle")}</b>
      ${s.mode?`, ${s.mode}${s.dry_run?" (dry-run)":""}`:""}
      ${s.error?`, <span class="bad">${s.error}</span>`:""}
    </div>
    <div class="kpis">
      <div class="stat"><div class="n">$${s.balance}</div><div class="l">Balance</div></div>
      <div class="stat"><div class="n ${pnlCls}">${s.pnl>=0?"+":""}$${s.pnl}</div><div class="l">Profit / Loss</div></div>
      <div class="stat"><div class="n">${s.instrument}</div><div class="l">Instrument</div></div>
    </div>
    <div class="chartwrap">
      <canvas class="chart"></canvas>
      <div class="legend">
        <span><i style="background:#262626"></i>price</span>
        <span><i style="background:#8a8a8a"></i>your entry</span>
        <span><i style="background:#cb3837"></i>stop-loss</span>
        <span><i style="background:#137333"></i>take-profit</span>
      </div>
    </div>
    <div style="margin:8px 0 10px"><b>Open trades (${ps.length}):</b> ${pos}</div>
    <div class="logbox">${(s.log||[]).join("\n")||"No activity yet."}</div>`;
  const cv=el.querySelector(".chart"); if(cv) drawChart(cv, s.prices, s.position);
  const lb=el.querySelector(".logbox"); if(lb) lb.scrollTop=lb.scrollHeight;
}

// Lightweight canvas price chart (no libraries). Draws the recent price line plus
// horizontal lines for the open trade's entry, stop-loss and take-profit.
function drawChart(cv, prices, pos){
  const ctx=cv.getContext("2d");
  const W=cv.width=cv.clientWidth||600, H=cv.height=240;
  ctx.clearRect(0,0,W,H);
  if(!prices || prices.length<2){
    ctx.fillStyle="#999"; ctx.font="13px sans-serif";
    ctx.fillText("Waiting for price data...", 12, 24); return;
  }
  let lo=Math.min(...prices), hi=Math.max(...prices);
  if(pos){ [pos.entry,pos.stop,pos.target].forEach(v=>{ if(v){ lo=Math.min(lo,v); hi=Math.max(hi,v); } }); }
  const span=(hi-lo)||0.0001, padv=span*0.12; lo-=padv; hi+=padv;
  const PADL=6, PADR=6, PADT=8, PADB=8;
  const x=i=> PADL + i/(prices.length-1)*(W-PADL-PADR);
  const y=v=> H-PADB - ((v-lo)/(hi-lo))*(H-PADT-PADB);
  function hline(v,color){ if(v==null) return; ctx.strokeStyle=color; ctx.lineWidth=1;
    ctx.setLineDash([5,4]); ctx.beginPath(); ctx.moveTo(0,y(v)); ctx.lineTo(W,y(v)); ctx.stroke(); ctx.setLineDash([]); }
  if(pos){ hline(pos.entry,"#8a8a8a"); hline(pos.stop,"#cb3837"); hline(pos.target,"#137333"); }
  ctx.strokeStyle="#262626"; ctx.lineWidth=1.6; ctx.beginPath();
  prices.forEach((p,i)=>{ const xx=x(i),yy=y(p); i?ctx.lineTo(xx,yy):ctx.moveTo(xx,yy); }); ctx.stroke();
  const last=prices[prices.length-1];
  ctx.fillStyle="#cb3837"; ctx.beginPath(); ctx.arc(x(prices.length-1),y(last),3.5,0,Math.PI*2); ctx.fill();
}
function startPolling(elId){
  pollTarget=elId;
  if(pollTimer) clearInterval(pollTimer);
  const tick=async ()=>{
    try{
      const s=await (await fetch("/api/live/state")).json();
      const el=document.getElementById(pollTarget); if(el) renderPanel(el,s);
      if(!s.running){ clearInterval(pollTimer); pollTimer=null; }
    }catch(e){ clearInterval(pollTimer); pollTimer=null; }
  };
  tick(); pollTimer=setInterval(tick,1000);
}

// ── Practice controls ──
$("#pracStart").onclick=async ()=>{
  const b=$("#pracStart"); busy(b,"Starting...");
  loadingBox($("#pracPanel"), "Starting the simulator...");
  try{
    if(ROLE==="admin") await saveFormula();  // admins may have tweaked the formula
    const r=await (await fetch("/api/live/start",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({mode:"practice", file:$("#pracFile").value, tick:parseFloat($("#pracTick").value)})})).json();
    if(!r.ok){ toast(r.message||"Could not start"); $("#pracPanel").innerHTML=`<div class="warn">${r.message||"Could not start"}</div>`; return; }
    toast("Practice started"); startPolling("pracPanel");
  } finally { unbusy(b); }
};
$("#pracStop").onclick=async ()=>{ await fetch("/api/live/stop",{method:"POST"}); toast("Stopping..."); };

// ── Live controls ──
async function checkLiveReady(){
  const el=$("#liveReady");
  try{
    const s=await (await fetch("/api/live-status")).json();
    const yes='<b class="good">yes</b>', no='<b class="bad">no</b>';
    el.innerHTML =
      `Broker details set: ${s.mt5_configured?yes:no}<br>`+
      `MetaTrader 5 available on this computer: ${s.mt5_available?yes:no+' (Windows / VPS only)'}<br>`+
      `Instrument: <b>${s.instrument}</b> &nbsp; Timeframe: <b>${s.granularity}</b>`+
      (s.alerts.length?`<br>Alerts on: ${s.alerts.join(", ")}`:"");
    $("#liveStart").disabled = !(s.mt5_configured && s.mt5_available);
  }catch(e){ el.textContent="Could not check connection."; }
}
$("#liveStart").onclick=async ()=>{
  const dry=$("#liveDry").value==="true";
  if(!dry && !confirm("This will place REAL orders on your broker account. Continue?")) return;
  const b=$("#liveStart"); busy(b,"Connecting to MT5...");
  loadingBox($("#livePanel"), "Connecting to your broker...");
  try{
    if(ROLE==="admin") await saveFormula();
    const r=await (await fetch("/api/live/start",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({mode:"live", dry_run:dry})})).json();
    if(!r.ok){ $("#livePanel").innerHTML=`<div class="warn">${r.message}</div>`; toast("Could not start"); return; }
    toast("Live started"); startPolling("livePanel");
  } finally { unbusy(b); }
};
$("#liveStop").onclick=async ()=>{ await fetch("/api/live/stop",{method:"POST"}); toast("Stopping..."); };

load();
</script>
</body>
</html>
"""
