DOC_ID: draco-auth
TITLE: Draco Authentication Error Budget

ANSWER_FACT: Draco authentication failures were caused by stale JWKS cache
entries.
ANSWER_FACT: The first mitigation is to flush the JWKS cache and temporarily
lower the key refresh interval.
ANSWER_FACT: The owning team is identity-platform.

Draco login failures rose after a signing key rotation. The identity provider
published the new key, but two API gateway replicas continued validating
tokens against stale JWKS entries. Restarting all gateways is not the preferred
first action because a targeted cache flush is faster and lower risk. The
runbook requires confirming token validation errors before changing global
authentication policy.

CITATION: draco-auth section 5 assigns mitigation to identity-platform.
