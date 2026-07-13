# quit-sponsor bot (private beta)

Telegram bot running the open quit-sponsor protocol (SKILL.md + SAFETY.md from
github.com/metrox-eth/quit-sponsor) as its brain. Live instance: @QuitSponsorBot
(free private beta, 20 spots). Open source (MIT) so the care is auditable end to
end: ETHICS.md binds the operators, TERMS.md is the beta contract, and the
protocol repo carries the evidence (references, model fit test).

## Design

- Single process, long polling, standard library only.
- Brain: the full skill as system prompt, inference via Virtuals compute
  router (GLM-5-turbo by default, chosen by measured fit, see the protocol's
  MODEL_FIT.md). Model and privacy status disclosed in /about.
- One directory per user under `data/`: `logbook.jsonl` (every message and
  event, timestamped, content encrypted at rest) and `profile.json` (consent,
  settings). Honest scope of the encryption: the key lives on the same server
  (the bot must read the logbook to think), so it protects against disk theft
  and stray backups, not against the operator. /export decrypts: the person's
  data reaches them readable.
- Consent gate before any sponsoring: nobody talks to the sponsor without
  accepting the ground rules (adult, not medical, not emergency, data terms).
- /export sends the person their full logbook; /delete erases everything
  after confirmation. Both real (ETHICS.md).
- LLM failure never yields silence: a static fallback names the failure and
  the human crisis lines (a blank reply mid-crisis is abandonment).
- Evening close anchor (21:00 server time), off by default, /anchors on.

## Run your own

1. Clone the protocol next to this repo: `git clone https://github.com/metrox-eth/quit-sponsor.git` (or set SKILL_DIR).
2. Create a bot with @BotFather on Telegram, get the token.
3. `cp secrets.env.example secrets.env`, fill TELEGRAM_BOT_TOKEN and LLM_API_KEY (any OpenAI-compatible endpoint via LLM_URL; pick a model that passes the protocol's MODEL_FIT.md test before trusting it with a crisis).
4. `python3 bot.py --selftest` (offline state-machine test, no network).
5. `python3 bot.py`

## Founding documents

ETHICS.md binds the operators. TERMS.md is the beta terms draft. Both are
served in-bot via /ethics and /terms.

## Next milestones

- Negotiated outbound cadence (the skill's check-in arc, per-user) instead of
  the fixed evening anchor; silence protocol scheduling.
- Verified-privacy inference route before public launch (Venice API direct
  with published no-storage modes, or local inference); gate written in TERMS.
- Retention/analytics: aggregate, opt-in only.
- Pricing after first retention signal; crisis path never gated (ETHICS 4).
