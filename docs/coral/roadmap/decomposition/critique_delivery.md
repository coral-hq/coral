# Critique of master v1: delivery lead lens (parallelization and critical path)

Input: `decomposition/master_v1.md` and `decomposition/master_v1.json` (85 features, K1-K20). Scripts used for every number below are in `wf2/delivery/`:

- `sched.py`: critical path (CPM) over hard deps, weights S=1, M=2, L=4.5.
- `level.py`: resource-leveled list scheduler. Milestone-first priority, then longest tail. ENG-04 is staffed by two engineers. Phase windows are not enforced.
- `revise.py`: applies the edge changes and splits proposed here and writes `revised.json`.

The baseline CPM reproduces the script results (M1 13.5, M2 18.5, M4 23).

## 1. Verdict

The feature set is sound and coverage is complete. The schedule shape is not.

The dependency graph turns the M2 plan into a big-bang integration:

- the walking skeleton is modelled as the last M2 feature;
- the parallelization levers named in §6 are not encoded as edges;
- three serial L features (SES-03 > SES-04 > SES-06) form the critical path, although each could be built against contracts that already exist (K4 FakeOmni, K5, K13).

After PH2 the load collapses. In PH3 only WS-HARNESS is busy: Platform, Workspace, Brand and Ops have no features, and Engine, Web and Integration are light. PH4 then starts the M4 critical chain from zero.

I propose 9 edge changes and 7 splits (a split means one feature becomes two). With them:

- The CPM to M2 drops from 18.5 to 14.0 weeks.
- At the same assumed staffing (17 engineers), the leveled M2 moves from about week 20 to about week 16. With Platform at 3 and Ops at 2, it moves to week 14.
- The topology-fallback contingency costs about 1 week instead of 3.5.
- Starting WSP-02 at M2 and contract-splitting K20 pulls the M4 workspace chain in by about 6-8 weeks.

The **shortest credible M2 is about week 16**: a CPM floor of 14, plus integration buffer at IM-3, plus a 1-week credentialed soak. The roadmap as written gives 18.5 + soak + big-bang risk. Realistically that is week 20-22.

## 2. Unnecessary serialization (hard edges that can be soft)

| Edge in v1 (hard) | Why it is not needed | Stub or contract to build against | Effect |
|---|---|---|---|
| ENG-04 → ENG-02 | The reducer consumes the frozen CompiledGraph, not the loader | K1 compiled-IR golden fixtures from ENG-01 (MVP template, D§5.6, deadlock) | M1 path 13.5 → 11.5; tools chain −2 |
| SES-04 → SES-03 | Dispatch through `_post_event_impl` does not depend on how the session was created. §6 already says "build SES-04 … against FakeOmni" (master_v1.md:1066) | K4 FakeOmni, plus HTTP-created sessions carrying coral.* labels; the K4 conformance suite runs against both | Breaks the 13.5-week serial L chain |
| GTE-01 → SES-03 | The S5/S6 seams are Omnigent-side. A gate on an HTTP-created run session is enough until the facade lands (SPK-02 probe (e) proves rendering) | K4, K14, K10 | GTE-01 starts at week ~7, not 9.5 |
| SES-06 → SES-04, SES-06 → DUR-05 | The restart ladder needs create (SES-03), generation (DUR-03) and salvage/reset (K13 fake). Drift checks need labels and policies. Resync integration is late wiring | K4, K5, K13 fake | Removes the longest M2 chain |
| TLS-03 → ENG-05 | The choose_arrow handler validates labels against K2 decision requests. Loop semantics are proven at IM-3 | K2 | Tools chain −2 |
| EVD-02 → WSP-01 | Capture (S68/S69) and evaluation need K13 and S71, not repo bindings or the run branch | K13 fake backend, S71 split out | Evidence chain −2.5 |
| WSP-02 → WSP-01 | The host channel needs the S71 reaper guard and K13, not repo bindings | S71 feature, K13 | Head of the M4 chain is free from PH2 |
| API-02 → DUR-02 | Runs need only the K5 workflow-store protocol to resolve a pinned version | K5 | Platform chain 16 → 11.5 |
| RUL-02 → EVD-02 | Labels need the K11 evidence IR and the K9 matrix fixture, not capture code | K9 frozen fixture, K11 | M3 chain 18 → 11; RUL-02 can start in PH2 |

Recomputed M2 CPM after each step (`revise.py`): baseline 18.5 → ENG-04 edge 18.5 → SES-04/GTE-01 edges 18.0 → SES-06 split 16.0 → S71 split 16.0 → TLS-03 split 16.0 → API-02 edge **14.0** → SES-05 split 14.0.

After these changes there is no single critical chain. Several chains finish within half a week of each other:

| Finish (week) | Chain |
|---|---|
| 14.0 | WEB: FND-01 > FND-03 > DUR-01 > DUR-02 > WEB-03 |
| 14.0 | WEB: FND-01 > ENG-01 > WEB-01 > WEB-04 > WEB-05 |
| 13.5 | tools: FND-01 > ENG-01 > ENG-04 > TLS-02 > TLS-03 > SES-05b |
| 11.5 | Platform: FND-01 > FND-03 > DUR-01 > DUR-04 > DUR-05 |

That wide front is why integration milestones (§5) matter.

**Contingency check.** Topology fallback, modelled as SES-03 +3.5 weeks: v1 M2 18.5 → 22.0; revised 14.0 → 15.0. A failed SPK-04, modelled as WSP-01 +3 weeks: v1 19.0; revised 14.5.

## 3. Workstream load per phase

Script loads, in weighted single-owner weeks. A dash means no features in that phase.

| WS | PH0 | PH1 | PH2 | PH3 | PH4 | PH5 | PH6 |
|---|---|---|---|---|---|---|---|
| ENGINE | 2 | 14.5 | **—** | 2 | 9 | 2 | 6.5 |
| PLATFORM | 2 | **16** | 6.5 | **—** | **—** | 2 | 2 |
| INTEGRATION | 3 | 6 | **24** | 4.5 | 8.5 | 2 | 4.5 |
| HARNESS | 1 | 2 | 5.5 | 10.5 | **—** | 9 | — |
| WORKSPACE | 1 | 2 | 11 | **—** | 13.5 | **—** | 6.5 |
| WEB | **—** | 9 | 13 | 4 | 11 | **—** | 4.5 |
| BRAND | **—** | 4 | **—** | **—** | **—** | 2 | — |
| OPS | 3 | 5 | **—** | **—** | **—** | 6.5 | — |

Findings:

- **Engine** has nothing to do from about week 11 (ENG-07 done) until PH4. RUL-02 (pure), the semantics half of ENG-08 (reducer, validator and Simulate for repeat and parallel, keyed by TLD-21 scope keys) and ENG-10 (versions and diff) have no PH3+ hard dependencies.
- **PH3 is a Harness-only phase.** Platform, Workspace, Brand and Ops have zero features, and the other teams are light. Teams will start PH4 work early anyway, so the roadmap should say so and pick which work: WSP-02, WEB-08, SES-07, TLS-04, DUR-06, GTE-03.
- **Harness is idle in PH4**, while HRN-05 (codex-native) is in PH5 even though the M4 proving journey needs codex-native reviewers in the PH4 structure run. Move HRN-05 to PH4.
- **Platform is front-loaded.** It has 24.5 weeks before M2: FND-01, API-01, FND-02, FND-03, DUR-01..05 and API-02. In the leveled run with 2 engineers, API-02 and DUR-05 become the binding M2 items (week 14-16). Then Platform is idle in PH3 and PH4. Staff it with 3 through M2 and move one engineer to WSP-02, OPS-04 load and GTE-03 at M2.
- **Integration is overloaded only in PH2.** It has 24 weeks of work, all on near-critical chains. It sheds SES-05's acceptance half to Ops. Once the SES-03 edges become soft, 4 engineers suffice.
- **Ops** runs at 100% in weeks 0-8 (SPK-01, OPS-01, FND-04, OPS-02, OPS-03 with one owner) and has no features in PH2-PH4, although upstream merges are continuous work. Changes: give SPK-01 to the tech lead or PM; move the I1-I8 reducer invariant harness from FND-04 to Engine; give Ops the acceptance lanes and the real-merge cadence.
- **Brand** is idle in PH2-PH4. Desktop builds stay disabled until BRD-03 (OPS-02; R-18). BRD-03 has a single hard dependency, BRD-01.
- **Hidden web work.** The load table hides web work that sits in non-WEB features: ENG-10 (restart dialog), RUL-05 (start-dialog budget), GTE-03 and HRN-04 (settings UI), and PRF-01 (picker hooks). GTE-02, a WEB feature, hides backend work (inbox API, alert producers). WEB is therefore not really idle in PH5.

## 4. Contract-first opportunities

1. **K19 alert model ships too late and from the wrong team.**
   - Its producer is GTE-02 (WEB, PH2, ES 9.5 → 11.5).
   - A consumer, DUR-05, starts earlier (ES 9.5). It is the only contract with a consumer ahead of its producer (contract scan in `delivery/`).
   - ENG-06's watchdog ("remind once, then alert") emits alerts in PH1, and `coral_alerts` is already in DUR-01's coral_0002.
   - Fix: publish K19 in PH1 from DUR-01.
2. **No effect-executor contract.**
   - K2 fixes effect types and K5 fixes queue claim, lease and finish.
   - Nobody fixes how effect handlers register by kind, how idempotency is keyed on effect_key, how a result turns back into a reducer observation, or the error classes (transient retry, permanent, paused(infra)). Lease renewal for long handlers is also unowned.
   - Six features across three teams implement handlers: SES-03, SES-04, GTE-01, WSP-01, EVD-02, PRF-01.
   - Fix: add K21 as DUR-04's first PR (PH1), with a fake drainer.
3. **K20 host-op frames** ship as WSP-02's first PR in PH4. The draft appendix already exists in K13 from PH0. Freeze K20 v1 at M2 so EVD-04 builds against a fake host channel while WSP-02 is built.
4. **PH0 contracts are co-authored at once.** SES-01 consumes K2 and API-01 consumes K1 and K14 in the same week ENG-01 and SES-01 produce them. That is fine for a contract sprint, but it needs one dated freeze point (IM-0) rather than three independent "v1" dates.
5. **Downstream web consumers could soften their hard edges:**
   - WEB-06 → RUL-02 becomes soft via a label-API fixture.
   - WEB-07 → PRF-02 becomes soft via the K7 profile endpoints.
   - WEB-03 → DUR-02 becomes soft via the K7 MSW fixtures.

## 5. Proposed integration milestones

| IM | Week (revised plan) | Converging teams | Proving test |
|---|---|---|---|
| IM-0 Contract freeze | 3 | ENG, INT, PLAT, WSP, HRN | K1-K4, K6-K8, K10, K12-K14 and K16 at v1. FakeOmni passes K4 conformance. The OpenAPI drift check runs. A consumer stub in each team compiles against them |
| IM-1 Seam and store spine | 6 | INT, PLAT, ENG | A scripted coral_ test tool on an HTTP-created session (TLS-01) drives an ENG-04 skeleton transition committed by DUR-03 with CAS. An SES-02 observer sees the edge |
| M1 | 10-11 | all | As defined |
| IM-2 Walking skeleton (SES-05a) | 10-11 | INT, PLAT, ENG, OPS | One-step workflow → facade session → submit → gate answered via /approve → end, on the Tier B mock LLM. The kill/restart variant follows once DUR-05 and the SES-06 relaunch land |
| IM-3 MVP template headless | 13 | INT, HRN, WSP, ENG | Tier B run of the TLD-01 template: orchestrator loop to limit 3, evidence reject then accept, reviewer write denied, SIGTERM recovery |
| IM-4 UI on live backend | 14 | WEB, PLAT, INT | Start dialog → live run view over SSE → Inbox gate answer, against a real server |
| M2 | ~16 | all | IM-3 plus IM-4 on credentialed claude-sdk, with five nightly passes in a row (a one-week soak tail) |
| IM-5 Native step | M2+4 | HRN, INT | E2E-3 and E2E-4 inside the MVP template, with labels switching to Verified |
| IM-6 Backend swap | M2+6 | WSP | The evaluator gives identical verdicts on the session-shell and host-channel K13 backends |
| IM-7 Structure showcase | M2+10-12 | ENG, WSP, HRN, INT, WEB | PR-review loop: repeat (3 of N), parallel claude-sdk and codex-native reviewers, two writers, serial merges, post-merge checks |
| IM-8 Release rehearsal | before M4 | OPS, all | A real upstream merge through the playbook with all lanes green; security findings closed |

## 6. Splits that unblock parallel teams

- **SES-05.** SES-05a is the walking skeleton (S, INT, IM-2). SES-05b is the M2 acceptance lane (M, moved to WS-OPS). This reverses decision 15, because the merged feature carries 12 hard deps, so its "skeleton first" text cannot start before week 16.5.
- **SES-06.** One half is the restart ladder plus own-runner child relaunch (M). The other is drift and the outcomes of user actions on run sessions (M).
- **TLS-03.** coral_choose_arrow with the seeded orchestrator (M) stays. coral_ask_user (M) becomes its own feature. This makes the declared cut line real.
- **WSP-01.** Move S71 into its own S feature in PH1. The gap analysis lists it as XS and "can start immediately" (gap_analysis §MVP critical path).
- **GTE-02.** The alerts backend (K19, /v1/coral/inbox, ack, producers) splits from the web Inbox kind.
- **WEB-02.** The desk and library (M) split from the YAML editor (M or L). WEB-03 then depends only on the desk, and the cut line becomes real.
- **ENG-08.** The semantics half (repeat and parallel in the reducer, validator and Simulate; PH2-PH3, Engine) splits from the template, E2E-5 and integration half (PH4).

## 7. Can M1 and M2 be reached without PH3+ work?

Yes, by the graph. No M1 or M2 feature has a hard dependency on a PH3+ feature. The only forward soft edge is ENG-07 (M1) → ENG-06 (M2), which is harmless. Four caveats:

1. **Phase labels.** Five M2 features labelled PH2 have earliest starts in weeks 3-5: SES-03, HRN-02, PRF-01, WSP-01 and EVD-03. Peers with the same start, such as TLS-01, SES-02, RUL-01 and HRN-01, are labelled PH1. If PH2 is read as "after M1", M2 moves to week 29 (phase-gated CPM); if PH2 opens at week 9.5, it moves to week 25.
2. **M1 exit 7 depends on M2-tagged features.** It requires K9 and K18, whose producers (HRN-01, SES-02) are M2-tagged.
3. **The M2 exit depends on an undecided question.** It needs a credentialed nightly whose budget and keys (OQ-51) have no default and are not in SPK-01.
4. **M3 dates are misleading.** M3's CPM of 18 is shorter than M2's 18.5, which is impossible because milestones are cumulative. M3's real date is M2 plus the RUL-04 → HRN-03 tail (6.5 weeks), or M2 + 4.5 if RUL-04 is pulled into PH2.

## 8. Shortest credible critical path to M2

Based on the revised graph, leveled with 17 engineers, Platform 3 and Ops 2 (leveled week numbers):

1. Weeks 0-1: FND-01. Its first PR is the package skeleton, so the contracts can start on day 2-3.
2. Weeks 1-3: ENG-01, SES-01 and API-01 contract sprint, ending at IM-0. SPK-02 probes (a)-(d) decide by day 4.
3. Weeks 3-5.5: ENG-04 with two engineers. The skeleton slice is ready by week 4.5.
4. In parallel from week 3: SES-03 and SES-04, the latter against FakeOmni and HTTP-created sessions.
5. Weeks 7-9: TLS-02, GTE-01, then SES-06 and SES-08 (the two halves of SES-06).
6. Weeks 9.5-11.5: TLS-03 (choose_arrow). PRF-01 must be done by week 9.5.
7. Week ~10.5: IM-2.
8. Week ~11.5: DUR-05 and API-02 done.
9. Week 13: IM-3. Week 14: IM-4, with WEB-03 and WEB-05 done.
10. Weeks 14-15: SES-05b fault suite and credentialed soak. Week ~16: M2 with a week of buffer.

The pure CPM floor is week 14. I would not plan below week 16, because the critical front is wide: the tools, web, platform and session chains all finish within about 2 weeks of each other.

## 9. TLD soundness from the delivery lens

No TLD is unsound. Two notes:

- **TLD-17** (merge-never-rebase from nightly^1) is under-implemented. v1 only rehearses into a scratch branch until PH5's OPS-05 drill. Upstream had 1,490 commits in the last 30 days. Hot files changed 41-75 times each: orchestration.py 75, app.py 64, connect.py 62, helpers.py 52, Sidebar.tsx 50, routes_events.py 41. A first real merge after about 30 weeks of drift sits on the M4 path.
- **TLD-02** (option B with a 4-day spike) is fine. It becomes robust only once the SES-03 edges are soft, because v1 puts the fallback straight on the critical path.

## 10. Issues

The issues are returned through StructuredOutput: DEL-01..DEL-28, ranked by priority.

| ID | Sev | Type | Features | Change (short) |
|---|---|---|---|---|
| DEL-01 | blocker | split | SES-05, ENG-04, SES-03, SES-04, TLS-02, GTE-01, DUR-05 | Split SES-05: skeleton S (IM-2, wk 10-11) and acceptance M (WS-OPS) |
| DEL-02 | major | dependency | SES-04, GTE-01, SES-03, SES-01 | SES-04, GTE-01 soft on SES-03 via K4 FakeOmni + HTTP-created sessions |
| DEL-03 | major | split | SES-06, SES-04, DUR-05, SES-05, SES-03 | Split SES-06 into ladder/relaunch M and drift/user-actions M; hard on SES-03 only |
| DEL-04 | major | reorder | SES-03, PRF-01, WSP-01, HRN-02, EVD-03, EVD-02 | Relabel early-start PH2 items as PH1; add start weeks; M2 = wk 29 if read literally |
| DEL-05 | major | dependency | ENG-04, ENG-02, ENG-01 | ENG-04 hard on ENG-01 only (K1 compiled fixtures); M1 13.5 -> 11.5 |
| DEL-06 | major | split | TLS-03, ENG-05, GTE-01, SES-05 | Split ask_user out of TLS-03; ENG-05 soft; tools chain 18 -> 13.5 |
| DEL-07 | major | split | WSP-01, EVD-02, EVD-03, WSP-02 | S71 as its own PH1 S feature; EVD-02 and WSP-02 soft on WSP-01 |
| DEL-08 | major | missing | SES-05, ENG-01, SES-01, API-01, TLS-01, DUR-03, WEB-03, WEB-04, GTE-02, HRN-03, WSP-02, ENG-08, OPS-05 | Integration milestones IM-0..IM-8 |
| DEL-09 | major | evidence | SES-05, HRN-03, RUL-04, WEB-06, WSP-03, OPS-04 | Milestone acceptance nodes, staffing, leveled dates, soak tail |
| DEL-10 | major | boundary | SES-05, HRN-03, RUL-04, ENG-08, OPS-04, WEB-04 | WS-OPS owns M2/M3/M4 acceptance lanes |
| DEL-11 | major | contract | GTE-02, DUR-01, DUR-05, ENG-06, GTE-03, ENG-09 | K19 to PH1 from DUR-01; split GTE-02 backend vs web |
| DEL-12 | major | contract | DUR-04, SES-03, SES-04, GTE-01, WSP-01, EVD-02, PRF-01, DUR-05 | Add K21 effect-executor interface as DUR-04's first PR |
| DEL-13 | major | dependency | SES-02, TLS-01, GTE-01, EVD-02, HRN-03, RUL-04, HRN-05 | Pre-plant M2 hot-file call sites in PH1 seam packs, or encode the train |
| DEL-14 | major | risk | OPS-02, OPS-05, OPS-01 | Real upstream merges on a cadence from PH1 (TLD-17) |
| DEL-15 | major | reorder | ENG-08, RUL-02, ENG-10, ENG-09 | Engine PH2 work: ENG-08 semantics split, RUL-02 to PH2, ENG-10 API in PH3 |
| DEL-16 | major | reorder | WSP-02, WEB-08, SES-07, TLS-04, HRN-05, DUR-06, GTE-03 | Open PH4 at M2 alongside PH3; HRN-05 to PH4; GTE-03 to Platform |
| DEL-17 | major | dependency | WSP-02, EVD-04, WSP-03 | K20 v1 at M2; EVD-04 soft on WSP-02; M4 about 6-8 wks earlier |
| DEL-18 | major | sizing | API-02, DUR-02, DUR-04, DUR-05, DUR-01, FND-03 | API-02 soft on DUR-02; Platform 3 engineers through M2 |
| DEL-19 | major | risk | SES-05, SPK-01, SPK-03, HRN-01, FND-04 | OQ-51 into SPK-01; on-demand credentialed lane; schedule the soak |
| DEL-20 | major | reorder | OPS-04, TLS-01, GTE-01, PRF-01, WSP-02, SPK-02 | Threat-model checkpoints at M2 and at K20 freeze |
| DEL-21 | major | reorder | RUL-04, HRN-03 | RUL-04 to PH2 so HRN-03 starts at M2 |
| DEL-22 | minor | split | WEB-02, WEB-03, WEB-06, WEB-08 | Split WEB-02 desk vs YAML editor; WEB-03 soft on DUR-02 |
| DEL-23 | minor | boundary | SPK-01, OPS-01, FND-04, OPS-02, OPS-03, ENG-04 | SPK-01 to tech lead; invariant harness to Engine; Ops 2 engineers in PH1 |
| DEL-24 | minor | sizing | SPK-01, SPK-02, SPK-03 | Stage decisions by deadline; two engineers on SPK-02; resize SPK-03 |
| DEL-25 | minor | evidence | ENG-10, RUL-05, GTE-03, HRN-04, PRF-01, GTE-02, EXT-01 | Record secondary-workstream weeks; recompute load |
| DEL-26 | minor | evidence | HRN-01, SES-02, FND-01, ENG-01, SES-01, API-01 | K9/K18 first PRs as M1 deliverables; FND-01 skeleton-first PR |
| DEL-27 | minor | boundary | HRN-01, SES-05 | One owner per CI workflow file |
| DEL-28 | minor | reorder | BRD-03, OPS-02 | BRD-03 desktop part in PH3 |
