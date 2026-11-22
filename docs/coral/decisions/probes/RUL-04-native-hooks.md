# RUL-04 native hooks — spike 5 & 6 verdicts

Recorded for CRL-138 / RUL-04. Live CLI probes may refine these later.

## Spike 5 — UserPromptSubmit on `/clear`

**Question.** Does Claude Code fire `UserPromptSubmit` when the user or agent runs `/clear`, so a run-owned DENY could block rotation?

**Verdict (CRL-138 default).** **Follow `/clear`** (OQ-46 follow-by-default). Do not enable a UserPromptSubmit DENY for `/clear` until a live probe confirms the event fires reliably on the supported CLI floor. HRN-07 re-attaches policies after supersession instead.

## Spike 6 — native ASK re-publish after restart

**Question.** After a server restart, does a parked native ASK re-publish so the step can resume without re-running the tool?

**Verdict (CRL-138 default).** Treat re-publish as **unverified**. If an ASK is still open after restart and does not reappear, the holding step uses SES-06’s relaunch ladder rather than silently allowing the tool. Fail-closed mode denies when the evaluate path cannot return a verdict, so a lost ASK cannot become an implicit allow.

## Floor

Claude Code fail-closed launches require CLI ≥ `2.1.295` (see `coral/omni/harness/hook_preflight.py`).
