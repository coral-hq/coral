# Coral engineering roadmap — start here

This folder is the complete plan for building Coral on Omnigent: the roadmap, the three design documents it was built from, and the evidence behind it. Nothing outside this folder is needed except the Omnigent code.

## 1. Get the code

Every code reference (`path:line`) points at commit `2a9cbe2c2` on `main` of `github.com/omnigent-ai/omnigent`. Paths are relative to the repository root.

```
git clone https://github.com/omnigent-ai/omnigent.git
cd omnigent
git checkout -b coral 2a9cbe2c2
```

If you work from a newer commit, line numbers will drift. The file and symbol names usually still hold.

## 2. What to read, by role

The roadmap is about 170,000 words. Nobody needs all of it.

| Who | Read |
|---|---|
| Everyone | Section A (executive summary) |
| Tech lead and PM | A, then B (where the design documents conflict with the code), I (milestones), J (decisions, open questions, risks) |
| Workstream leads | H.1 (tracks and staffing), the H section for the current phase, K (who owns what) |
| Engineers | Your features in section F (search for `#### FND-01 ·`, for example), plus F.0 for the shared definition of done. Contracts K1-K21 are defined in sections D and G. |
| Anyone asking "why?" | The workpapers below |

Each feature spec in F has: objective, product requirements with source references, technical scope, implementation steps, dependencies, ownership, acceptance criteria and definition of done. They are close to ready to become tickets.

## 3. Before week 0

The plan does not start with feature code. Weeks 0-3 are decisions, contracts and spikes (roadmap H.3).

**How weeks are counted.** Week 0 is the start point. "Week 1" is the first working week, the schedule span 0-1 (roadmap A.8), and "day 4 of week 1" is its fourth working day. A feature planned for "1-3" starts at the end of week 1.

1. **Staff the tracks.** The plan assumes 20 engineers in 8 workstreams on 21 tracks (the BRAND engineer covers two), plus a decision track (OPS-T0) for the tech lead and PM (H.1). It names no people. These tracks have work on day 1: PLT-T1, INT-T1, INT-T2, HRN-T1, WSP-T1, WSP-T2, OPS-T1 and BRD-T1. ENG-T2 starts on day 2, when FND-01's skeleton lands. The rest start at the end of week 1 or later; H.1 gives each track's first window. With fewer people the dates in section I do not hold; H.1's staffing notes show the effect.
2. **Re-estimate.** The week estimates were produced during planning, not by the engineers doing the work. Each lead should check their tracks before week 0.
3. **Run sign-off through SPK-01** (the decision-records feature on OPS-T0). Records go in `docs/coral/decisions/`, with statuses `proposed`, `signed`, `defaulted` and `superseded`.
   - All 21 working decisions (TLD-01..TLD-21, J.2.1) are recorded by day 5 of week 1. One its owner accepts is `signed` with its condition. One still unanswered is `defaulted`, and its recommendation stands until a later record supersedes it, by the owner's deadline in J.2.1. TLD-02 comes first: ADR-05 v1 is signed on day 4.
   - SPK-01 also carries 19 week-1 open questions (its spec in section F lists them). Five product questions are due on day 3 of week 1 (J.3.1: OQ-3, 4, 12, 13, 19).
   - OQ-53 (an isolated development database for Coral) can be signed only by a human maintainer (A.6).
4. **Start the external questions now** (J.3.2):
   - OQ-28: auth for Claude steps and whether subscriptions are allowed. A default is recorded by week 2; a written vendor answer is needed by week 13.5, or claude-native steps ship on API keys only.
   - OQ-29: OpenAI terms for the Codex app server, by week 13.5, or `codex_steps` stays dark.
   - OQ-30: attribution and naming, with counsel.
5. **Requirements baseline (OQ-1).** `coral-design.md` refers to a `coral-requirements.md` that does not exist. The PM owns the baseline; J.3.1 has the proposed default.
6. **Day 1** (H.3):
   - SPK-02, the session-topology spike, on INT-T1 and INT-T2. ADR-05 v1 is signed on day 4 by the tech lead and the INTEGRATION lead; the addendum follows in week 2. Its probe (a) needs SPK-03's mock (day 2) or an Anthropic API key on the spike branch, so have a key ready.
   - FND-01, the code skeleton. It lands on day 2, so ENG-T2 can start the K1-K3 fixtures; the contract packs ENG-01, SES-01 and API-01 start at the end of week 1.
   - SPK-01 (decision records and threat-model checkpoint), OPS-01 (fork guard), SPK-03 and SPK-04 (harness and workspace spikes) and BRD-01 (web skin).
   - The PH0 contracts freeze at IM-0 in week 3. K4's create, access and watch sections depend on ADR-05, so SES-01 writes them last.

## 4. Files

| File | What it is |
|---|---|
| `CORAL_ENGINEERING_ROADMAP.md` | **The plan.** Sections A-K plus appendix V. Authoritative. |
| `REBRAND_PROMPT.md` | Agent prompt for a fresh Omnigent clone. It commits this package under `docs/coral/roadmap/`, rebrands the user-visible surfaces to Coral with Apache-2.0 attribution, and adds an empty skills placeholder at `.claude/skills/coral-workflows/`. Each Coral skill goes in its own folder directly under `.claude/skills/`, named `coral-<name>`. |
| `coral-design.md` | Source document: Coral design, Draft 4. Cited as `D§` and `design:NN` (line). |
| `CORAL_WORKFLOW_ENGINE_DEEP_DIVE.md` | Source document: engine deep dive. Cited as `DD§` and `DD:NNN`. |
| `coral_UI_DESIGN_LANGUAGE.md` | Source document: UI design language. Cited as `UI§` and `UI:NNN`. |
| `master_feature_list.json` | Machine-readable plan ("master v3"; older files call it `master_v3.json`): 108 features, contracts K1-K21, schedule, staffing, integration milestones, migration train, failure modes, UI surfaces, and the resolution, challenge and canon logs. Roadmap sections E, G and K are generated from it. Use it to import tickets; see section 5 for its fields. |
| `decisions_log.md` / `.json` | The 202 harmonization decisions (`RES-nnn`) that resolved cross-feature issues. Residual items are in roadmap J.6. |
| `naming_canon.md` | Canonical routes, payloads, module paths and contract contents (FR-01..FR-50). |
| `investigation/gap_analysis.md` | Gap analysis: G-01..G-90, the seam ledger, X-1..X-32, D1..D34 and OQ-1..OQ-54. |
| `investigation/current_state.md` | Current-state map of Omnigent and the verified-claims ledger at `2a9cbe2c2`. |
| `investigation/*.md` (other ten) | Specialist reports, cited in the roadmap by short name: `prod` = product.md, `arch` = architect.md, `adv` = adversarial.md, `sess` = eng_sessions.md, `tools` = eng_tools.md, `pers` = eng_persistence.md, `harn` = eng_harness.md, `ws` = eng_workspace.md, `web` = eng_web.md, `test` = eng_testing.md. |
| `decomposition/decomp_*.md` | The three independent decompositions (contract-first, vertical-slice, risk-first). |
| `decomposition/master_v1.*`, `master_v2_fix1.*` | The feature list before and after the five critiques (Markdown and JSON). |
| `decomposition/critique_*.md`, `changelog_v2.md` | The five critiques and the decision on every critique issue. |
| `verification/verifier_issues.md`, `reviewer_notes.md` | Issues raised when each feature spec was checked against the code. `decisions_log.md` cites them by line. |
| `verification/coverage.json` | Which decision covers each verifier issue. |

## 5. Importing tickets from `master_feature_list.json`

- One ticket per entry in `features`. `tracks` is the H.1 track (two for the paired features ENG-04 and SPK-02); `calendar_weeks` is set only on those two and gives their elapsed weeks with two engineers.
- `planned_start_week` and `planned_finish_week` use the week counting in section 3. `milestone_weeks` gives each milestone's levelled and planned week, including post-M4.
- `hard_deps` and `soft_deps` are feature ids. `slice_deps` such as `SES-03#skeleton` mean "this slice of that feature" (roadmap F.0): link to the base feature and keep the slice as a label.
- `objective`, `included` and `key_paths` are summaries. Where they differ from the feature's spec in roadmap section F, the spec wins; put the spec text in the ticket body.

## 6. Conventions in the older files

- Paths to these files are relative to this folder.
- `master_v3.json` is `master_feature_list.json`. `canon_instructions.json` was a working file whose edits are already applied, and section files such as `D.md` or `I.md` are now roadmap sections.
- The planning ran in stages, and older files name them: `wf1` = investigation (`investigation/`), `wf2` = decomposition (`decomposition/`), `wf3` = writing and verifying the feature specs (now roadmap section F; issues in `verification/`), `wf4` = harmonization (`decisions_log.*`, `master_feature_list.json`).
- `decisions_log.md` names spec files such as `dur.md` or `web-b.md`. Those specs are now in roadmap section F.
- A few files mention working scripts (`wf2/adv/`, `wf2/arch_tmp/`, `wf2/delivery/`, `wf2/eng_critique/`, `wf3/tmp_seams.tsv`, `wf4/challenge/`). They were throwaway and are not included.
- The engineer critique's ids appear in the roadmap as `SEN-nn`; `critique_engineer.md` and `changelog_v2.md` call them `ENG-nn`. Roadmap feature ids `ENG-nn` are different things.
- Some ids and line references in the older files were corrected later. Where they disagree, the roadmap and `master_feature_list.json` win.

## 7. Known limits

- The word UNVERIFIED appears 42 times in the roadmap. It marks claims nobody could confirm in the code; check them before relying on them.
- 27 items remain open after harmonization, plus 2 found when this package was reviewed (PKG-01 and PKG-02). All are in roadmap J.6.
- The three source documents are copies taken on 2026-11-12. If the originals change, re-sync them.

## 8. Viewing and checking

- Open the roadmap in an editor with a Markdown preview that renders Mermaid, such as VS Code with a Mermaid preview extension. The diagrams are in C, D, G.1-G.3, H.2 and I.3. The file is 1.2 MB, which some web previews will not render in full.
- Quick completeness check, run in this folder:

```
grep -c '^#### [A-Z]\{3\}-[0-9][0-9] · ' CORAL_ENGINEERING_ROADMAP.md
awk '/^## K\./,/^## Appendix/' CORAL_ENGINEERING_ROADMAP.md | grep -c '^| [A-Z]\{3\}-[0-9][0-9] |'
python3 -c "import json; print(len(json.load(open('master_feature_list.json'))['features']))"
```

All three should print `108`.
