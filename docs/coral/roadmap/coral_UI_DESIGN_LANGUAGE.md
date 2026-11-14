# Coral UI design language

Design reference for rebuilding Coral’s **visible frontend** on a fresh Omnigent fork. This document covers only what we changed for brand, color, type, logos, and desk chrome — not Omnigent’s underlying product architecture, harnesses, or server topology.

Use this alongside a technical MD and a product MD later. Scope here: **what you see**.

---

## 1. Brand identity

| Item | Coral choice | Omnigent baseline (replace) |
| --- | --- | --- |
| Product name | **Coral** | Omnigent / Omnigents |
| Default hero heading | **Direct the run…** | Operator-configurable; often “What should we do?” |
| Personality | Editorial, warm, organic, “Clay Score” parchment | Cooler product chrome / pink starfish mascot |
| Logo mark | Circular organic leaf / mosaic emblem (earth tones) | Pink + green starfish (Otto) |
| Wordmark | Serif text **Coral** next to the mark (not an SVG Omnigent wordmark) | Official Omnigent wordmark image |

**Do not** keep Omnigent pink as a brand accent. Terracotta clay is the brand accent.

---

## 2. Color palette

### 2.1 Core Clay Score ramp (canonical)

These five hues are the accent language. Cream is the **main** surface; the others are accents only.

| Token (Tailwind / CSS) | Hex | Role |
| --- | --- | --- |
| Cream ground | `#FEF7F1` | Main app background (`--background`) |
| Forest | `#4D7356` | Primary green accent, success, chart-1 |
| Sage | `#9EAB92` | Soft green accent, info |
| Mustard | `#C19A55` | Warm gold accent, warning, dark-mode primary |
| Terracotta / clay | `#864A31` | Brand accent, primary CTA, ring, brand-accent |
| Ink | `#523E31` | Body text / foreground |

CSS custom properties (current prototype names — rename to `coral-*` if desired on rebuild):

```css
--concerto-forest: #4d7356;
--concerto-sage: #9eab92;
--concerto-mustard: #c19a55;
--concerto-clay: #864a31;
--concerto-ink: #523e31;
```

Tailwind utilities (via `@theme`): `bg-concerto-forest`, `text-concerto-mustard`, etc.

### 2.2 Light theme surfaces (default “Coral” palette)

Mapped onto Omnigent’s `omni` theme slot (`themePalette.ts` label **Coral**).

| Token | Hex / value | Use |
| --- | --- | --- |
| `background` | `#FEF7F1` | Page canvas |
| `card` | `#FFFDF9` | Raised panels |
| `cardSolid` | `#FFFFFF` | Opaque cards |
| `foreground` / ink | `#523E31` | Primary text |
| `muted` | `#EFE4D8` | Soft fills |
| `mutedForeground` | `#8A7566` | Secondary text |
| `secondary` / sidebar base | `#F5EBE1` | Sidebar, secondary surfaces |
| `border` | `#E0D2C4` | Hairlines / inputs |
| `borderStrong` | `#C9B5A4` | Stronger dividers |
| `primary` | `#864A31` | Buttons, key actions |
| `primaryForeground` | `#FEF7F1` | Text on primary |
| `link` | `#6F3C28` | Links (slightly deeper clay) |
| `ring` / `brandAccent` | `#864A31` | Focus + brand moments |
| `selectionBackground` | `rgba(134, 74, 49, 0.12)` | Text selection wash |
| `accent` (UI hover wash) | `#F6EEE6` | Quiet hover / accent surface |
| `tag-pink` (legacy name) | `rgba(134, 74, 49, 0.08)` | Clay wash (not Omnigent pink) |
| `primary-cta` | `#864A31` | Primary CTA fill |

### 2.3 Dark theme surfaces

| Token | Hex / value |
| --- | --- |
| `background` | `#2A211C` |
| `card` / `cardSolid` | `rgba(58,47,40,0.72)` / `#3A2F28` |
| `foreground` | `#FEF7F1` |
| `primary` / `ring` | `#C19A55` (mustard reads better on dark) |
| `brandAccent` | `#864A31` (clay stays brand) |
| `border` | `#4A3C33` |
| Sidebar | `#241C18` with soft clay/forest gradient overlays |

Dark accent ramp (slightly lifted for contrast):

- forest → `#9EAB92`
- sage → `#6B8574`
- mustard → `#C19A55`
- clay → `#C47A58`
- ink → `#FEF7F1`

### 2.4 Status & charts (repointed to Clay, not Omnigent blue/pink)

| Role | Light |
| --- | --- |
| success | `#4D7356` (forest) |
| warning | `#C19A55` (mustard) |
| info | `#9EAB92` (sage) |
| status-red / destructive brand-adjacent | `#864A31` (clay) — keep true destructive red only where Omnigent already uses error red for failures |
| charts 1–5 | forest → sage → mustard → clay → ink |

### 2.5 Atmosphere (shell washes)

Do **not** ship a flat white Omnigent canvas. Keep cream as the base, then add soft radial washes so accents appear without overpowering:

**Light shell**

```text
radial forest ~8% top-left +
radial mustard ~10% top-right +
radial clay ~7% bottom-right +
#FEF7F1
```

**Light sidebar**

```text
soft vertical forest wash + diagonal mustard wash on #F5EBE1
```

Connect / setup page uses the same idea: cream ground + forest / mustard / clay radials.

---

## 3. Typography

### 3.1 Body / UI chrome (unchanged stack)

Keep Omnigent’s native UI sans — do not restyle all product text as serif.

```text
ui-sans-serif, system-ui, sans-serif, …emoji stacks
```

Mono (code): Geist Mono Variable / JetBrains Mono (as upstream).

### 3.2 Display / headings (Coral addition)

| Item | Spec |
| --- | --- |
| Family | **Newsreader** (`@fontsource/newsreader` 400/500/600) |
| Fallbacks | `"Iowan Old Style", Palatino, Georgia, "Times New Roman", serif` |
| CSS / Tailwind | `--font-heading` → utility `font-heading` |
| Weight | Medium (`500`) for titles |
| Tracking | Slightly tight, e.g. `-0.03em` |

**Where serif appears (only these brand moments):**

- Sidebar wordmark “Coral”
- New-session hero (“Direct the run…”)
- Desk page titles via `CoralPageHeader` (State Schema, Agent Profiles, Inbox, Automations)
- Connect / setup brand title

**Where serif does not appear:** chat transcript body, composer, settings forms, tables, monospace IDs.

### 3.3 Alignment rule for logo + type

Logo and adjacent serif text must share one flex row with optical vertical centering:

- Container: `inline-flex` / `flex` + `items-center`
- Image: `display: block`, fixed square size, `object-contain`
- Text: `leading-none` (avoid serif em-box drift)
- Hero: size logo with `h-[1em] w-[1em]` against the same `text-[…]` parent as the heading so they scale together

---

## 4. Logo & desktop icon

### 4.1 UI mark (everywhere except dock)

- Asset: circular, organic, multi-segment leaf/mosaic mark
- Colors inside mark: forest, sage, mint, mustard, terracotta, deep red accents on **transparent** background (no black plate in UI)
- Used in: sidebar, new-session hero, onboarding panels, Powered-by, Auth shells, connect page
- Component: `CoralLogo` (fallback when no operator custom logo)

### 4.2 Sidebar brand row

```
[ mark ~28px ]  [ “Coral” Newsreader ~20px medium ]
```

- Gap ~10px
- Hover: slight opacity drop on the whole home link
- Custom operator `branding.app_name` replaces the word “Coral” but keeps the same layout

### 4.3 New-session landing

```
[ mark ]  Direct the run…
```

- Side-by-side (not stacked), matching Omnigent’s starfish-beside-heading pattern
- Large Newsreader heading (~34px / ~2.55em desktop)
- Mark height locked to `1em` of that heading size

### 4.4 Desktop / dock icon (separate treatment)

- **Do not** use the raw transparent UI mark as a full-bleed dock tile
- Cream plate `#FEF7F1` with rounded corners + transparent outer margin for macOS squircle
- Mark cropped of baked-in padding, sized ~**72%** of the plate (between “too tiny” and “over-zoomed” vs Chrome/Discord)
- Files: `web/electron/icons/icon.png` + `icon.icns`
- Rebuild UI logos freely; leave dock icon alone unless intentionally regenerating

---

## 5. Navigation labels & tab / page headings

Treat **sidebar labels** and **in-page titles** as one naming system. They should match (or be obvious siblings).

### 5.1 Left-rail labels (prototype)

Preserve Omnigent sidebar structure; Coral adds / restyles desk entries in the primary nav cluster (near Inbox):

| Sidebar label | Route | Icon (lucide) | In-page heading (serif) |
| --- | --- | --- | --- |
| **Inbox** | `/inbox` | (upstream) | Inbox |
| **Automations** | `/tasks` | (upstream) | Automations |
| **State Schema** | `/schemas` | Workflow | State Schema |
| **Agent Profiles** | `/profiles` | UserRound | Agent Profiles |

Active state: same Omnigent sidebar active wash (`--sidebar-active`), not a new selected style.

### 5.2 In-page heading style (locked)

Every desk page above uses the same visual title treatment via `CoralPageHeader`:

| Property | Spec |
| --- | --- |
| Type | Newsreader / `font-heading` |
| Size | ~24px |
| Weight | Medium (500) |
| Tracking | ~`-0.03em` |
| Accent rail | Five dots above title: forest → sage → mustard → clay → ink |
| Subcopy | ~13px muted sans under the title |
| Chrome | Full-width header band, `border-b`, title left / primary actions right |

**Do not** leave Inbox or Automations on the old Omnigent plain `text-2xl font-semibold` sans header — they must share this Coral heading pattern with State Schema and Agent Profiles.

### 5.3 Naming is provisional

The **visual** heading pattern is locked. The **words** on those tabs are not final:

- “State Schema” might become Score, Flow, Pipeline, Graph, etc.
- “Agent Profiles” might become Agents, Runners, Personas, Harness profiles, etc.
- “Automations” / “Inbox” can stay Omnigent-native unless product renames them

When renaming later, change sidebar label + page `<h1>` together so they stay in sync.

---

## 6. Desk page chrome pattern

Shared header for Coral desk surfaces (Inbox, Automations, State Schema, Agent Profiles):

**`CoralPageHeader`**

1. Full-bleed page column: `flex flex-1 flex-col bg-background`
2. Header bar: `border-b border-border`, `px-6 py-4`, title left / actions right
3. **Accent rail** above the title — five 6px dots in palette order:  
   forest → sage → mustard → clay → ink  
   (decorative only, `aria-hidden`)
4. Title: `font-heading` ~24px medium, tracking `-0.03em`
5. Description: ~13px `text-muted-foreground`, max-width ~2xl
6. Content below scrolls independently (list pages keep a centered column; schema keeps a split pane)

This is the visual unifier that made Inbox/Automations match State Schema / Agent Profiles.

---

## 7. Connect / onboarding chrome

Electron connect (legacy setup + v2 selector) should feel Coral before the SPA loads:

- Title: **Coral — Connect**
- Cream background + soft forest/mustard/clay radials
- Brand row: logo + Newsreader “Coral”, horizontally centered as one unit
- Accent rail (same five dots)
- Copy: “Run a Coral server…” (no Omnigent product name in user-facing strings)
- Primary actions use clay primary (`#864A31` light / mustard dark)

Onboarding blob graphic: floating washes in forest / mustard / terracotta / sage (no Omnigent pink blobs).

---

## 8. Firm vs loose (prototype intent)

Not everything in this fork is a final product decision. When rebuilding, treat the lists below differently.

### 8.1 Firm (carry into a fresh fork as design law)

- Cream ground + Clay Score accent ramp (forest / sage / mustard / clay / ink)
- Terracotta as brand/primary (mustard as dark primary)
- Newsreader for brand wordmark + desk page headings only; body stays system sans
- Circular organic mark + serif “Coral” wordmark; logo/text vertically aligned
- Dock icon: cream rounded plate, mark ~72% of plate (not full-bleed UI PNG)
- Shared desk heading chrome (accent rail + Newsreader title) across Inbox / Automations / Schema / Profiles
- Soft shell/sidebar washes (not flat white)

### 8.2 Loose — State diagram / score drawer

**What we know we want**

- A free-flow, drag-and-drop graph surface in the spirit of **Lucidchart / Simulink / Figma**: movable nodes, pan/zoom canvas, **directed connection arrows** between states
- Nodes represent steps in a run / score (phases, gates, notes, something orchestrator-like)
- Edges can carry some notion of flow (messages, artifacts, approvals) — exact contract model TBD

**What is intentionally up in the air**

- Exact product name (“State Schema”, “Score”, “Flow”, …)
- Surrounding chrome: left palette vs toolbar vs empty-canvas CTAs; whether inspector is a right rail, bottom sheet, or modal
- Node taxonomy and labels (phase / gate / note / orchestrator are prototype guesses)
- How tightly profiles, I/O ports, and orchestrator channels are edited on-canvas vs elsewhere
- Persistence format, validation UX, empty states, and onboarding for first graph
- Whether the canvas is the whole page or sits inside a larger desk layout

**Rebuild guidance:** ship a Lucid-like directed graph as the *interaction metaphor*; do not freeze the prototype’s React Flow layout, copy, or IR as product law until the product MD settles it.

### 8.3 Loose — Agent Profiles

**What we know roughly**

- Reusable bindings that say “this kind of agent run uses this harness / model / instructions / sandbox-ish settings”
- Referenced from graph steps so a phase can pick a profile instead of hard-coding a harness every time
- Lives as its own desk surface in the left rail (prototype: **Agent Profiles**)

**What is intentionally up in the air**

- Exact fields (provider list, sandbox model, permissions, skills, MCP, etc.)
- Whether profiles are local-only desk objects, server resources, or YAML agents under the hood
- How they appear in pickers on the graph (dropdown vs search vs cards)
- Naming, defaults, and relationship to Omnigent’s native agent catalog
- How much of the Profiles page is a full editor vs a thin pointer into Omnigent agent config

**Rebuild guidance:** keep a Profiles-like desk entry and a “bind profile on a node” affordance; treat the current form fields and localStorage store as disposable scaffolding.

### 8.4 State Schema canvas (current prototype look — not binding)

For visual continuity with this prototype only:

| Node kind (provisional) | Accent treatment |
| --- | --- |
| Phase | Forest border / wash |
| Gate | Mustard border / wash |
| Note | Sage border / wash |
| Orchestrator | Clay border / wash |

- Directed arrows in ink; broken contracts can read as warning/destructive
- Prototype layout: left add-palette, center canvas, right inspector
- Cream/muted dashed board — not white Omnigent cards

Replace freely once product terms land.

---

## 9. What to keep from Omnigent UI

Do **not** redesign these as part of Coral brand work:

- Chat transcript, composer, approval cards structure
- Sidebar session list / DnD / projects model
- Settings information architecture
- Density, radii, and control sizes from the Omnigent design system (`--radius*`, otto easing) unless a brand moment needs it
- Appearance theme picker infrastructure — keep it; only replace the default `omni` slot with Coral Clay tokens

Coral is a **skin + desk chrome + nav additions**, not a new component library.

---

## 10. Implementation map (for a fresh fork)

| Concern | Upstream touchpoint (prototype) |
| --- | --- |
| App name / heading | `web/src/lib/branding.ts` |
| Default theme tokens | `web/src/lib/themePalette.ts` (`omni` id, label Coral) + regenerate `themePalettes.generated.css` |
| Accent CSS + heading font | `web/src/index.css` (`--font-heading`, `--concerto-*`, status remaps) |
| Logo component | `web/src/components/CoralLogo.tsx` + asset under `web/src/assets/` |
| Sidebar brand + tab labels | `web/src/shell/Sidebar.tsx` |
| Landing hero | `web/src/shell/NewChatDialog.tsx` |
| Page / tab heading pattern | `web/src/components/concerto/CoralPageHeader.tsx` |
| Desk routes | `web/src/App.tsx` → `/schemas`, `/profiles` |
| Electron name / connect | `web/electron/package.json` `productName`, `setup/index.html`, `main.js` strings |
| Dock icon | `web/electron/icons/icon.png` / `.icns` (cream plate, ~72% mark) |

---

## 11. Design checklist (rebuild acceptance)

**Firm**

- [ ] Default canvas is cream `#FEF7F1`, not white
- [ ] Primary buttons / brand accent are terracotta `#864A31` (mustard in dark)
- [ ] Five accent dots appear on desk page headers in forest→sage→mustard→clay→ink order
- [ ] Desk tab pages (Inbox, Automations, State Schema, Agent Profiles) share Newsreader ~24px headings + accent rail
- [ ] Sidebar labels match (or clearly pair with) those in-page headings
- [ ] “Coral” wordmark is Newsreader beside the circular mark, vertically centered
- [ ] “Direct the run…” sits beside the mark at matching visual height
- [ ] Sidebar includes desk entries for schema/graph and profiles (names may change)
- [ ] No Omnigent starfish / pink brand moments in default theme
- [ ] Dock icon is rounded cream plate with moderately padded mark (not full-bleed square)
- [ ] Body UI remains system sans; only brand/titles use Newsreader

**Loose (pass if directionally true)**

- [ ] Schema/graph surface is a free-flow directed node graph (Lucid/Simulink-like), even if chrome/terms differ
- [ ] Profiles exist as reusable agent bindings selectable from graph steps, even if fields differ

---

## 12. One-line summary

**Coral = cream parchment ground, earth accent ramp (forest / sage / mustard / clay / ink), Newsreader for brand + desk tab headings, circular organic mark, and shared accent-rail page chrome — with a Lucid-like state graph and reusable agent profiles as product directions still open to rename and reshape.**
