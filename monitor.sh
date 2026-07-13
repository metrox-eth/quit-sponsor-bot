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

# 3. LLM router actually answering? Judge the body (router returns 201 on
# success) and retry once before alerting: a single blip is not an outage.
if [ -n "${LLM_PING:-1}" ]; then
  KEY="${LLM_API_KEY:-$(python3 -c "import json;c=json.load(open('/home/openclaw/.claude-code-router/config.json'));print((c.get('Providers') or c.get('providers'))[0]['api_key'])")}"
  OK=0
  for try in 1 2; do
    BODY=$(curl -s -m 25 "https://compute.virtuals.io/v1/chat/completions" \
      -H "Authorization: Bearer ${KEY}" -H 'Content-Type: application/json' \
      -d '{"model":"z-ai-glm-5-turbo","messages":[{"role":"user","content":"ping"}],"max_tokens":8}')
    if echo "$BODY" | grep -q '"choices"'; then OK=1; break; fi
    sleep 10
  done
  if [ "$OK" != "1" ]; then
    alert "the AI brain is not answering (checked twice). Users currently receive the emergency fallback message. Check the Virtuals router and the credits."
  fi
fi
