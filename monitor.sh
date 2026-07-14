#!/bin/bash
# QuitSponsor watchdog: runs from a systemd timer. Checks the service and the
# Telegram API path; restarts on failure and alerts the operator via the bot
# API directly (which works even when the bot process is down).
set -u
cd "$(dirname "$0")"
source secrets.env

alert() {
  echo "$(date -Is) ALERT: $1" >> monitor.log
  if [ -n "${OPERATOR_CHAT_ID:-}" ]; then
    curl -s -m 10 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d chat_id="${OPERATOR_CHAT_ID}" --data-urlencode text="⚙️ Ops (operator only, not a sponsor message): $1" >/dev/null
  fi
}

# 1. service running?
if ! systemctl --user is-active --quiet quitsponsor-bot.service; then
  alert "the bot process was down. I restarted it automatically; if this repeats, check: journalctl --user -u quitsponsor-bot"
  systemctl --user restart quitsponsor-bot.service
  exit 0
fi

# 2. telegram api reachable with our token?
if ! curl -s -m 15 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | grep -q '"ok":true'; then
  alert "Telegram is unreachable from the rig (network or token problem). The bot is running but may be deaf."
fi

# 3. LLM chain actually answering? Mirror the bot's failover: primary route
# from secrets.env (thinking disabled, short timeout, like the bot), then the
# historical Virtuals fallback (ccr key). Users only see the emergency
# fallback message when EVERY route fails, so alert only on a full-chain
# outage: a single flaky rail is the failover's job, not the operator's.
if [ -n "${LLM_PING:-1}" ]; then
  OK=0
  if [ -n "${LLM_URL:-}" ] && [ -n "${LLM_API_KEY:-}" ]; then
    BODY=$(curl -s -m 20 "${LLM_URL}" \
      -H "Authorization: Bearer ${LLM_API_KEY}" -H 'Content-Type: application/json' \
      -d "{\"model\":\"${SPONSOR_MODEL:-glm-5-turbo}\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":64,\"thinking\":{\"type\":\"disabled\"}}")
    echo "$BODY" | grep -q '"choices"' && OK=1
  fi
  if [ "$OK" != "1" ]; then
    VKEY=$(python3 -c "import json;c=json.load(open('/home/openclaw/.claude-code-router/config.json'));print((c.get('Providers') or c.get('providers'))[0]['api_key'])" 2>/dev/null)
    if [ -n "$VKEY" ]; then
      BODY=$(curl -s -m 30 "https://compute.virtuals.io/v1/chat/completions" \
        -H "Authorization: Bearer ${VKEY}" -H 'Content-Type: application/json' \
        -d '{"model":"z-ai-glm-5-turbo","messages":[{"role":"user","content":"ping"}],"max_tokens":64}')
      echo "$BODY" | grep -q '"choices"' && OK=1
    fi
  fi
  if [ "$OK" != "1" ]; then
    alert "the AI brain CHAIN is down: primary and Virtuals fallback both failed. Users currently receive the emergency fallback message. Check ${LLM_URL:-the LLM routes}."
  fi
fi
