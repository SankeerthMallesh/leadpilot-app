# Assumptions (conservative defaults; change any of them)

| # | Unfilled item | Default | Reason |
|---|---|---|---|
| 1 | Agency / app name, URL, support email | `LeadPilot`, `http://localhost:8000`, `support@example.com` (env `APP_NAME`, `APP_URL`, `SUPPORT_EMAIL`) | Replace before OAuth verification and before any real send. |
| 2 | Technical level / OS | Beginner; double-click launchers (`start.command`, `start.bat`, `start.sh`) around `run.py`; Windows launcher is untested | No terminal commands needed to run locally. |
| 3 | Test client | Fictional "Northwind Bookkeeping (DEMO)" with PLACEHOLDER address and proof | Demo only. Real sends are blocked later by the pre-send gate until a real postal address exists. |
| 4 | Regions | US only; CA/UK/EU off | Per spec. Not legal advice. |
| 5 | Volume / budget | Client daily cap default 30; monthly cost cap $40 per client | Per-client cap enforced on every AI call already. |
| 6 | Notifications | Telegram (email fallback) | Wired in Phase 8. |
| 7 | Search provider | Brave Search API | Wired in Phase 3. |
| 8 | DRY_RUN | `true` by default | Safest default. |
| 9 | LLM prices | Env vars `PRICE_*`, defaults are estimates | Only used for cost tracking. Check Anthropic pricing and adjust. |
| 10 | Login throttling | Per-account lockout (DB) + per-IP limit (in-process memory) | The per-IP limiter is per process. A Redis-backed limiter arrives with the job queue in Phase 3. |
| 11 | Phase 1 tables | users, clients, client_icp_versions, audit_log, api_costs, assistant_messages | Remaining tables arrive with the phase that uses them, as additive Alembic migrations. |
| 12 | Docker | app + postgres + redis in Phase 1 | worker/scheduler services are added in Phase 3 when the job code exists. |
| 13 | AI panel | Right-hand side panel on every admin page, uses the main Claude model | Per your request. History is stored per admin and per client. |
| 14 | Rate limiters | In-process sliding window (login per IP: 20/15 min, AI chat: 20/min per admin) | Fine for one app process. Moves to Redis in Phase 3. |
| 15 | Pausing a client | Requires a written reason; status change is audited | Phase 7 auto-pause will reuse the same status field. |
| 16 | CSP header | Not set | The Tailwind and HTMX CDN scripts need inline allowances. Revisit when assets are self-hosted. |
| 17 | Overall budget | `MONTHLY_BUDGET_USD` (default 150) shown on dashboard/costs; informational, per-client caps are what block calls | Matches the example budget. |
| 18 | Email generation | One model call writes the whole sequence (tool-use structured output), code lints it, one LLM self-check scores it, at most one rewrite. Typical 2 calls, worst case 4. | Fastest path that still enforces quality. |
| 19 | Greeting, signature, footer | Added by code, never by the model. Footer includes postal address and an "Unsubscribe: {{unsubscribe_url}}" placeholder. | Cannot be forgotten or hallucinated. Phase 6 supplies the real link. |
| 20 | Grounding | Emails may only use the facts entered in Email Studio. Numbers must appear in facts, client proof, price range or CTA. | Anti-hallucination. Phase 5 will fill facts from crawled, re-verified pages. |
| 21 | Self-check pass mark | accuracy >= 4, compliance >= 4, spam safety >= 4, tone >= 3 | Strict on facts and honesty, looser on style. |
| 22 | Prompt caching | System prompt marked cacheable; context block is compact and deterministic | Cheaper and faster repeat turns. Savings depend on prompt length reaching the provider's minimum. |
| 23 | Studio drafts | Not stored | Persistence and the approval queue arrive in Phase 5. |
| 18 | Studio facts | Typed by the operator, one per line (`fact | url`) | Phase 5 will crawl and re-verify facts automatically. Until then you are responsible for their accuracy. |
| 19 | Number grounding | Any digit in an email must appear in the facts, client proof, price range, CTA or offer | Blocks invented statistics. May flag legitimate numbers (for example "15-minute call") unless they are in the CTA text. |
| 20 | Self-check model | `SELFCHECK_MODEL` (default: main model) | Accuracy matters more than speed for the reviewer. Set it to the fast model to cut cost. |
| 21 | Pass bar | Accuracy>=4, compliance>=4, spam safety>=4, tone>=3 | Strict on facts and honesty, lenient on style. |
| 24 | Ollama hardware / model | Assumed one machine with 8-12 GB VRAM or 16 GB RAM; default `llama3.1:8b` (Q4_K_M), `num_ctx` 4096 | Change `OLLAMA_MODEL` / `OLLAMA_NUM_CTX` to fit your hardware. |
| 25 | Ollama structured output | ICP and email generation use Ollama's JSON-schema `format`, validated by Pydantic, one retry | Small local models follow schemas less reliably than Claude; keep Claude for emails if quality drops. |
| 26 | Ollama cost tracking | Logged as $0 with token counts | Per-client caps do not limit local usage. |
