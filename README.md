# LeadPilot: AI Lead Finder & Outreach Agent (v0.5)

> **Not legal advice.** The operator and each client are responsible for compliance with CAN-SPAM, CASL, GDPR/UK-GDPR and local laws.
> Have a lawyer review the terms, consent text and regional settings before enabling any non-US region.

## Quick start (no terminal commands)

1. Install **Python 3.12 or newer** from https://www.python.org/downloads/ (Windows: tick "Add python.exe to PATH").
2. Unzip or clone this folder, then **double-click the launcher**:
   - **macOS:** `start.command` (first time: right-click it, choose **Open**, then **Open** again)
   - **Windows:** `start.bat`
   - **Linux:** `./start.sh`
3. The first run installs everything (a minute or two), creates your private settings file `.env`, and opens it so you
   can paste an AI key (or set `LLM_PROVIDER=ollama`) and your email settings. Save it, press Enter in the launcher window.
4. Your browser opens. On first run you see a **Welcome** page: create your admin email and password there.
5. Next time, just double-click the launcher again. Keep its window open while you use the app; close it to stop.

Prefer a terminal? `python3 run.py` does exactly the same thing.

### AI choices
- **Free and local:** install Ollama (https://ollama.com), run `ollama pull llama3.1:8b`, and set `LLM_PROVIDER=ollama` in `.env`.
- **Anthropic:** set `ANTHROPIC_API_KEY=...` in `.env`.
The **System** page shows whether the AI is reachable.

### Sending email from the AI panel (optional)
In `.env` set `CHAT_EMAIL_ENABLED=true` and fill in `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`.
For Gmail: turn on 2-Step Verification, create an App Password at https://myaccount.google.com/apppasswords, and paste the
16 letters as `SMTP_PASSWORD` (spaces are fine; never use your normal password). Restart the app.
Then either click **Email** under the chat (review, tick the box, send), or type a command that **starts with "send" or "email"**
and contains an address, for example `send hi to name@example.com` or `email name@example.com saying the meeting moved to 3pm`.
You always get one OK/Cancel confirmation first. The **System** page shows "Operator email: ready" when it is set up.
These one-off emails are separate from `DRY_RUN` (which is for the campaign pipeline), and every send is written to the audit log.

### Putting it on GitHub
- `.gitignore` already blocks `.env` (your keys), `.venv`, and the local database. **Never commit `.env`.**
  If a key or app password ever lands in a commit, revoke it and create a new one.
- Anyone who clones the repo does the Quick start above with their own `.env`; no secrets travel with the code.
- GitHub stores the code; it does not run the app. Others run it on their own computer, or deploy it with Docker (below).
- The `/setup` page only works from the computer running the app and only until the first admin exists. On a server, create the
  admin with `python scripts/create_admin.py` (see Docker below).

Phase 1 delivers: scaffold, database + migrations, admin login (argon2, CSRF, lockout, optional TOTP),
client intake (form + JSON/YAML import), AI-generated ICP with edit and approve, cost tracking,
and the **AI assistant panel on the right side of every page**.

## What's in v0.2
**UI:** left navigation, dashboard (clients, pending approvals, spend vs budget, recent activity), costs page,
system status page, grouped intake form, readable ICP view with an "Edit JSON" tab, progress steps and activity feed on
each client, toasts, busy buttons on slow actions, search and status filter, branded login and error pages.
**AI panel (right side):** collapsible (Hide button, or Ctrl+K to open), remembers open/closed, instant message echo,
typing indicator, safe markdown rendering of replies, Copy button, per-client context.
**Backend:** request IDs + JSON access logs, security headers (HSTS when `COOKIE_SECURE=true`), HTML/JSON error handling,
`/healthz` and `/readyz`, pause/resume with required reason and audit trail, per-user AI chat rate limit,
reusable rate limiter, cost reporting queries, and a Redis-free limiter that Phase 3 will swap for Redis.

## What's in the AI upgrade
- **Streaming chat** with Stop (Esc), Regenerate, live safe-markdown, and partial replies saved if you stop.
- **Structured output:** ICP and email generation use forced tool-use with validated schemas (no fragile JSON parsing).
- **Email Studio** (client page, once the ICP is approved): paste verified facts about a prospect, get a 3-email sequence with
  3 subject variants each. Pipeline: one generation call, instant code lint (length, links, spam words, fake "Re:", invented
  numbers, unknown fact ids), one LLM self-check, at most one rewrite, otherwise flagged "needs review".
- **Efficiency:** pooled keep-alive HTTP client, prompt caching with cache-aware cost tracking, compact deterministic context,
  history character budget, grouped queries, no model call when the lint already fails.
- Prompts live in `prompts/` (`assistant_v2`, `icp_v2`, `draft_sequence_v1`, `selfcheck_v1`) and the version is logged.

## What's in v0.3 (AI upgrade)
- **Streaming chat** with Stop (Esc), Regenerate, live safe-markdown, partial replies saved if you stop.
- **Email Studio** (client page, needs an approved ICP): paste verified facts about a prospect and get a 3-email sequence
  with 3 subject variants each. Every email is grounded: it can only cite your facts; a deterministic lint rejects invented
  numbers, spam phrases, fake "Re:" subjects, extra links, and greetings; a separate AI reviewer scores accuracy, tone, spam
  safety and compliance; failures trigger one rewrite, then go to you flagged. Greeting, signature, postal address and the
  unsubscribe/promotional footer are added by code so they can never be forgotten.
- **Structured output** through forced tool-use (ICP and emails) instead of parsing free text.
- **Efficiency:** prompt caching, pooled keep-alive connection, one call writes the whole sequence, lint runs before the
  AI reviewer (no model spend on obviously bad drafts), compact deterministic chat context, history character budget.
- Drafts are not stored or sent yet: the approval queue (Phase 5 persistence) and compliance gate (Phase 6) come next.

## Run it manually (advanced; the launcher above does all of this)

```bash
cd leadpilot
python3 -m venv .venv && source .venv/bin/activate
make install          # installs dependencies
make init             # creates .env with a fresh SECRET_KEY
```
Open `.env` and set `ANTHROPIC_API_KEY=...` (needed for ICP generation and the AI panel).
Then:
```bash
make migrate          # creates the database tables
make admin            # create your admin login (add --totp via: python scripts/create_admin.py --totp)
make seed             # optional: demo client with an approved ICP (no API key needed)
make dev              # starts http://127.0.0.1:8000
```

## Test and lint
```bash
make test
make lint
```

## Docker (production-style)
```bash
cp .env.example .env && python scripts/gen_key.py --write-env
export POSTGRES_PASSWORD='choose-a-long-password'
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml exec app python scripts/create_admin.py
```
Put Caddy in front for HTTPS (`docker/Caddyfile`) and set `COOKIE_SECURE=true`.

## Using the AI panel
It sits on the right of every admin page. On a client page it knows that client's intake and approved ICP;
elsewhere it gives general help. It cannot take actions. Chat history is stored per admin and client; use **Clear** to delete it.
On small screens tap the **AI** button in the header.

## Security notes
Secrets come only from environment variables. Sessions are signed cookies; every POST needs a CSRF token.
Login locks the account after repeated failures. Never commit `.env`.

## v0.4: Ollama (local / self-hosted model) support
Set `LLM_PROVIDER=ollama` (everything) or `ASSISTANT_PROVIDER=ollama` (AI panel only, Claude keeps writing emails).
The **server** calls Ollama; browsers never do, so there are no CORS or mixed-content problems. Keep Ollama on
`127.0.0.1` or a private Docker network. Quick start:
```bash
ollama pull llama3.1:8b          # or: ollama create leadpilot -f ops/Modelfile
# in .env: LLM_PROVIDER=ollama  OLLAMA_MODEL=llama3.1:8b
python scripts/ollama_bench.py   # time to first token + tokens/second
```
The System page shows whether Ollama is reachable, the model is installed, and the model is loaded in memory.
Docker: `docker compose -f docker/docker-compose.yml -f docker/docker-compose.ollama.yml up -d`.
Remote GPU box: see `docker/Caddyfile.ollama-remote` (bearer token, no response buffering).
