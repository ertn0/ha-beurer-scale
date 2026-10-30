"""Constants for the Beurer BF500 scale integration."""

DOMAIN = "beurer_scale"

CONF_USER = "user"
CONF_CONSENT = "consent_code"

# Sync attempts after the scale reports new data for the user, and the pause
# between them. Afterwards wait for new data or the "Fetch measurements" button.
MAX_ATTEMPTS = 3
RETRY_DELAY = 20
# Seconds to keep retrying the first write while the user presses SET.
PAIRING_WAIT = 30
# After connecting, how long to wait for the scale's pairing request, and how
# long to let the link settle after the agent confirmed it.
PAIRING_PROMPT = 8
PAIRING_SETTLE = 2
# How long to wait for the scale to answer the consent request (it sends all
# stored records first, then the response).
RESPONSE_TIMEOUT = 30
# Seconds between checks for a fresh advertisement (see coordinator).
POLL_INTERVAL = 5
# Only advertisements younger than this (seconds) trigger a sync.
FRESH_ADV = 15
# Seconds to wait for the scale to be seen again after removing the stale bond.
REDISCOVER_WAIT = 15
# Connection timeout; includes pairing, so the user has time to press SET.
CONNECT_TIMEOUT = 30
