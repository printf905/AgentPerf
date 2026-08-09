DOC_ID: borealis-jobs
TITLE: Borealis Delayed Jobs Investigation

ANSWER_FACT: Borealis delayed jobs were caused by database CPU saturation,
not by worker process crashes.
ANSWER_FACT: The first mitigation is to pause low-priority enrichment jobs and
increase the job poll interval.
ANSWER_FACT: The owning team is data-platform.

The Borealis queue delay started after a batch enrichment campaign increased
write amplification. Workers stayed healthy, but the database primary reached
92 percent CPU and slow query logs showed repeated enrichment writes. The
runbook recommends pausing non-critical enrichment and reducing poll pressure
before scaling workers, because additional workers would increase pressure on
the database.

CITATION: borealis-jobs section 2 names data-platform as owner and lists the
first mitigation as pausing enrichment jobs.
