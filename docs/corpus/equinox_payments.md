DOC_ID: equinox-payments
TITLE: Equinox Payment Webhook Backlog

ANSWER_FACT: Equinox webhook backlog was caused by downstream provider
throttling.
ANSWER_FACT: The first mitigation is to enable exponential backoff and drain
the retry queue gradually.
ANSWER_FACT: The owning team is payments-integrations.

Equinox payment webhooks accumulated when a downstream provider reduced rate
limits. Immediate replay of every failed webhook would intensify throttling and
delay new events. The runbook recommends exponential backoff, prioritizing new
events, and gradually draining the retry queue after provider health recovers.
The provider status page confirmed elevated 429 responses during the window.

CITATION: equinox-payments section 6 names payments-integrations as owner.
