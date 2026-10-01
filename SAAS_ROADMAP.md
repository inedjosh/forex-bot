# Turning this into a subscription SaaS — what's done, and what's missing

This is the honest gap list for going from "a bot I run" to "a paid product other people
trust with money." Read it before selling a single subscription.

---

## The safe product model (recommended)

**Each customer connects their OWN broker (MT5) account.** Their funds stay with their own
regulated broker. Your service only sends *trade instructions* to their account using
credentials they provide. You never hold, move, or withdraw their money.

Why this matters:
- **Withdrawals/deposits are the broker's job, not yours.** MT5's automation API cannot
  move money; it can only trade. So "withdraw from our dashboard" isn't technically
  possible through MT5 — and trying to custody client funds yourself is the most heavily
  regulated activity there is. Keep funds at the user's broker.
- You become a *software/signal tool*, not a *fund manager* — a lighter (though still
  possibly regulated) position.

---

## Update — what's built in the app now

The model is settled and much of the foundation is done:
- **Admin-only accounts.** No public signup. First admin is bootstrapped via
  `scripts/manage_users.py`; all other accounts are created by the admin.
- **Web admin dashboard** (`/admin`) — create customers, activate/deactivate
  subscriptions (with expiry dates), reset passwords, set subdomains/notes. Writes to the
  same `users.db` the bot reads, so **you manage everything from the browser, no SSH.**
- **Per-user isolation** — each login gets its own trading loop; customers **enter their
  own MT5 credentials** (stored encrypted; you never see their broker password).
- **Subscription gating** — live trading is blocked unless the account is active; you flip
  it off when someone stops paying.
- **Telegram password reset** — customers reset their own password via a code sent to the
  Telegram chat id on file.
- **Manual subscriptions** — no payment gateway. You collect the fee directly and mark the
  account active. Customers deposit/withdraw at their own broker; funds never touch you.
- **Subdomain gating** — an env flag (`SUBDOMAIN_GATING=off`) reserved for go-live.

Still to do before real customers: security hardening (HTTPS, 2FA, audit log, prod
server), monitoring/auto-restart, legal docs, and the subdomain routing itself.

---

## Status legend
✅ done  ·  🟡 partial  ·  ❌ not started

## 1. Accounts & access
- ✅ Login / signup / logout, hashed passwords, sessions (Phase 1, just built)
- ✅ Dashboard + all APIs gated behind login
- ❌ **Email verification** (confirm the address is real)
- ❌ **Password reset** ("forgot password" email flow)
- ❌ **2-factor authentication** (strongly recommended — this controls trading)
- ❌ **Rate limiting / lockout** on login (stop brute-force)
- ❌ Roles/permissions beyond the basic admin/user flag

## 2. Multi-tenant isolation (⚠️ BLOCKER before 2+ real users)
Right now settings and the trading loop are **global/single-tenant**. Two users would
overwrite each other's formula and share one bot. Needed:
- ❌ **Per-user settings** (each user's formula lives in the DB, not one global `.env`)
- ❌ **Per-user MT5 credentials**, stored **encrypted at rest** (see Security)
- ❌ **Per-user bot instance** (one trading loop per user, isolated, supervised)
- ❌ Resource limits so one user can't starve others
- ❌ Per-user data/logs separation

## 3. Payments & subscriptions
- ❌ **Payment provider** — Paystack or Flutterwave (Nigeria-friendly) or Stripe
- ❌ Subscription plans + billing cycle, receipts/invoices
- ❌ **Plan gating** (e.g. free = backtest only; paid = live trading)
- ❌ Handle failed payments, cancellations, refunds, dunning
- ❌ **Auto-disable trading when a subscription lapses**

## 4. Security (non-negotiable — this is money)
- 🟡 Session secret persisted; passwords hashed
- ❌ **Encrypt MT5 credentials at rest** (e.g. Fernet/KMS; never store plaintext)
- ❌ **HTTPS/TLS everywhere** (a real domain + certificate; never send creds over http)
- ❌ Secrets in a proper store (env/secret manager), not files in the repo
- ❌ CSRF protection on forms, secure/HTTPOnly/SameSite cookies
- ❌ Audit log (who logged in, who started/stopped trading, when)
- ❌ Dependency scanning, backups, incident plan
- ❌ Move off the Flask dev server to a production server (gunicorn/waitress + nginx)

## 5. Reliability & operations
- 🟡 Bot survives transient errors; logs to `bot.log`
- ❌ **Auto-restart** if the bot/VPS crashes (supervisor, or per-user process manager)
- ❌ **Monitoring & alerting** (is each user's bot alive? did MT5 disconnect?)
- ❌ Database backups (users, settings) + tested restore
- ❌ Health checks, status page
- ❌ Centralized logs per user

## 6. Product & UX
- ✅ Backtest, optimize, walk-forward, recipes, form-based formula
- ✅ Practice (paper) mode with live chart + log; Live mode (gated)
- ❌ Onboarding wizard ("connect your broker" step)
- ❌ Account page (subscription status, change password, connect/disconnect broker)
- ❌ Trade history table + downloadable statements per user
- ❌ Email/Telegram alerts wired per user (engine exists; needs per-user config)
- ❌ Admin panel (see users, suspend, support)

## 7. Legal & compliance (talk to a lawyer — seriously)
- ❌ **Regulatory check**: offering automated trading for a fee may require licensing
  (Nigeria SEC, plus each customer's jurisdiction). Do this *before* charging.
- ❌ **Terms of Service** + **Risk Disclaimer** users must accept (trading can lose money)
- ❌ **Privacy Policy** (you store emails + broker credentials)
- ❌ KYC/AML considerations depending on how you position the service
- ❌ Clear, honest performance claims (no "guaranteed profit" language, ever)
- ❌ Data-protection compliance (Nigeria NDPR, GDPR if any EU users)

## 8. White-label / custom domains
- ❌ Realistic version: one app, per-user **subdomains** (`user.yourbrand.com`) with
  wildcard TLS — much simpler than a separate custom domain per customer.
- ❌ Per-user branding (logo/name) if desired
- ❌ True per-customer custom domains (`theirbrand.com`) = significant ops (DNS + certs
  per tenant); do this only if a customer specifically needs it.

---

## Suggested build order

1. **Phase 2 — multi-tenant isolation** (blocker). Per-user settings + encrypted broker
   creds + per-user bot. Nothing else matters until this exists.
2. **Security hardening** — HTTPS, encrypted secrets, CSRF, 2FA, audit log, prod server.
3. **Legal** — ToS, risk disclaimer, privacy policy, and a regulatory consult.
4. **Payments** — Paystack/Flutterwave subscriptions + plan gating + lapse handling.
5. **Ops** — monitoring, auto-restart, backups.
6. **Polish** — onboarding, account page, trade history, admin panel.
7. **Deploy** — hosted app + subdomains.

## The one-line reality
The bot and the dashboard are the *easy* 30%. The other 70% — isolation, security,
payments, reliability, and law — is what makes it safe to take people's money. Do not
skip it.
