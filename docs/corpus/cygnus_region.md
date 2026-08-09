DOC_ID: cygnus-region
TITLE: Cygnus Single-Region Latency

ANSWER_FACT: Cygnus latency was isolated to the eu-west region.
ANSWER_FACT: The first mitigation is to shift read traffic away from eu-west
and keep writes pinned until replication lag is verified.
ANSWER_FACT: The owning team is edge-routing.

The Cygnus incident showed high p95 latency in one region while deploy history
was clean. The edge routing dashboard showed increased upstream connection
setup time from eu-west only. Other regions served normal latency and error
rates. The runbook says to shift read traffic first when the fault is regional
and to avoid moving writes until replication lag has been checked.

CITATION: cygnus-region section 4 names edge-routing as owner and describes
the read-traffic shift mitigation.
