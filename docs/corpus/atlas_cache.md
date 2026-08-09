DOC_ID: atlas-cache
TITLE: Atlas Cache Rollout Incident

ANSWER_FACT: Atlas cache rollout increased HTTP 503 responses in the checkout
service.
ANSWER_FACT: The first mitigation is to disable the new cache admission policy
and revert to the prior stable cache configuration.
ANSWER_FACT: The owning team is platform-cache.

The checkout service saw a rapid rise in 503 responses after the cache
admission policy was changed from conservative admission to aggressive
write-through admission. Queue depth stayed normal, and database CPU remained
below the alert threshold. The cache cluster emitted eviction spikes within two
minutes of the deployment. The runbook says to prefer reversible mitigation
before root-cause certainty when a customer-facing error rate is rising.

CITATION: atlas-cache section 3 records the mitigation owner as
platform-cache and the rollback target as the prior stable cache
configuration.
