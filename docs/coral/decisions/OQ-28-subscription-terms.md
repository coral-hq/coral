# OQ-28 — Anthropic / vendor subscription terms for Coral

**Status:** defaulted (CRL-138 interim)  
**Deadline:** end of PH2 (week 13.5)  
**Fallback:** API-key-first; subscription Model-access option stays dark.

## Context

HRN-04 wants users to choose API key vs Claude subscription for steps. Vendor
terms for routing subscription traffic through Coral / Omnigent are not signed.

## Choice

Until Legal posts a written answer:

1. Coral Model access shows **API key** only.
2. `subscriptionOptionVisible` returns false even when `claude_native_steps` is on.
3. M3 journey steps that needed subscription run on an API key behind the flag
   (HRN-03 / OPS-08 consequence already recorded in the roadmap).

## When to reopen

A signed Legal record naming allowed subscription use for Coral steps. Then flip
`subscriptionOptionVisible` to honor `claude_native_steps` and update copy.
