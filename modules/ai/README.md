# AI assistant (lab module `ai`)

Claude (`claude-opus-5-5`) inside lab: chat, alert triage, morning summary. Backend = `connectors/ai` on the lab CT
(127.0.0.1:8117, venv /opt/lab-venv-ai with `anthropic` pinned in deploy/install.sh, state /var/lib/lab/ai).

## Safety model

- **Who:** owner and admins (setting `admins`); guests never (manifest access + connector check).
- **Reads as the user:** the manifest says `delegate: true`, so the gateway gives the connector a 15-minute token with
  every request the user makes to it (bound to user, role, the session, `via ai`). The connector reads other modules
  only through `GET /api/delegate/m/<module>/<path>` on the gateway, which applies that user's own route rules plus:
  GET only, no `secret` routes, no delegating module (it cannot call itself), redacted answers (gateway/lab/redact.py),
  127.0.0.1 only, a role that dropped since the mint counts, logout ends it; each read is audited `<user> via ai`.
  The token secret (/var/lib/lab/delegation.key, user `lab`, 600) is unreadable for connectors (own users `lab-c-<id>`,
  /var/lib/lab inaccessible to them).
- **Never writes:** `propose_action` stores a proposal; the UI shows a card, and only a click runs it from the
  user's browser through the target module's normal route (confirm dialog, `ask` → owner approval, audit). The outcome
  goes back into the conversation and the assistant may check the effect.
- **Prompt injection:** tool results, alerts, objects and proposal outcomes reach the model inside
  `<tool_output … trust="untrusted-data">` / `<untrusted>` wrappers (closing tags in the data are defused), the system
  prompt says never to follow instructions in data, results are capped (`tool_result_chars`) and so are tool rounds
  (`max_tool_calls`). The real boundary is the click.
- **Money:** each call is priced from its usage ($4 in, $20 out, $0.20 cache read, $5/$8 cache write 5 min/1 h per
  MTok; fallback hops at their own model's price) into SQLite. Before every call: month-to-date total < `monthly_cap`
  and (chat) the user's spend < their share. Refused with HTTP 402 / an error line in the chat.

## Settings (lab → Settings → ~/modules → ai; owner only)

| key | default | |
|---|---|---|
| `admins` | true | admins may use it |
| `monthly_cap` | 90 | hard cap in $ (Max plan credits: $100/month, no rollover) |
| `owner_share` / `admin_share` | 100 / 25 | % of the cap one person may use per month (triage + summary only count against the cap) |
| `reset_day` | 1 | day the budget period starts |
| `chat_effort` | medium | low / medium / high |
| `triage` / `triage_warn` | true / false | triage NEW ■ alerts (and ▲ with triage_warn); first snapshot after an install only seeds |
| `triage_effort` | low | low / medium (task budget 20k tokens, ≤ 6 rounds) |
| `triage_daily_max` / `triage_cooldown_hours` | 20 / 12 | |
| `summary` / `summary_time` | true / 07:30 | written once a day on the first lab visit after the time; shown in lab (overview + wall tile + ~/ai triage) |
| `summary_email` | false | reserved, not sent yet |
| `auto_fix` | false | hook only: the gateway never delegates writes, so proposals still need the click |
| `retention_days` | 30 | conversations are deleted after this |
| `max_tool_calls` / `tool_result_chars` | 12 / 12000 | per answer / per tool result |

## Claude API use

Official SDK, streaming (`client.beta.messages.stream`), adaptive thinking with `display: "updates"` (progress notes
between tool calls), `output_config.effort` set per route, server-side refusal fallbacks (`fallbacks: "default"`),
`stop_reason` handled (refusal, max_tokens, pause_turn), strict tool schemas with `tool_choice: auto` and eager input
streaming (inputs validated before running), prompt caching (stable system prompt + per-conversation module list +
fixed sorted tool list, plus automatic caching of the conversation tail), append-only history (preserved thinking).
The browser polls the running turn (`/live`, ~3/s) because the gateway buffers answers.

## UI

Rail `~/ai`: chat (history per user; the owner sees everyone's read-only), triage (summary + triage list + "triage"
for alerts without one), usage. Every object panel gets an `ai` facet (triage notes + proposals, "ask ai about …").
Ctrl-K: `? question`. Overview: spend KPI + the summary; wall tiles: spend, summary.
