# OQ-46 — Run-owned `/clear` policy

**Status:** defaulted (CRL-138)  
**Decision:** **Follow** native `/clear` rotation for Coral-bound steps.

## Context

RUL-04 spike 5 asked whether `UserPromptSubmit` fires reliably on `/clear` so
Coral could DENY clear and keep the same session. The spike memo
(`docs/coral/decisions/probes/RUL-04-native-hooks.md`) did not confirm a
reliable UserPromptSubmit on the supported CLI floor.

## Choice

HRN-07 follows Omnigent's existing supersession path: after `/clear`, Coral
rebinds the step binding (and re-attaches session policies) onto the
replacement session. A block-mode DENY remains available only if a later probe
proves UserPromptSubmit on `/clear`.

## Consequences

- Coral must re-attach policies/labels after rotation (HRN-07).
- Native Enforced labels stay off until D25 / fail-closed gates are trusted.
