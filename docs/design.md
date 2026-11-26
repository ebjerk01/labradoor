# lab design guide (for module authors)

lab is a dense control room, not a dashboard template. A screen shows a lot of information with little text. Every
module looks like part of one app because every module uses the same tokens, components and words. Read this guide
before you build a view, a tile or a facet. The shell code that sets these rules is in `ui/src/app.css`,
`ui/src/lib/*` and `ui/src/shell/*`.

## 1. Tokens

Use colours only through CSS variables. Never write a hex value in a module. Both themes follow the system setting,
and a user can force either one. Every variable has a value in both themes.

| token | dark | light | use |
|---|---|---|---|
| `--bg` | `#0F0E14` | `#F4F2F8` | page ground, input fields |
| `--panel` | `#15141C` | `#FBFAFD` | rail, tiles, object panel, drawers |
| `--raise` | `#1D1B27` | `#FFFFFF` | hover and selected rows |
| `--line` | `#28253A` | `#DDD8E8` | hairlines between sections, tile borders |
| `--q` | `#1B1924` | `#ECE9F3` | quiet separators between table rows, code blocks |
| `--ink` | `#ECE9F2` | `#17151E` | primary text |
| `--dim` | `#9C98AB` | `#5C5869` | secondary text, labels, units |
| `--faint` | `#3D3950` | `#CBC5DA` | tertiary marks (`~/`, `·`, empty values). Never put readable text in it |
| `--sig` / `--sig2` | `#B69CFF` / `#7C5CFF` | `#6A3FD6` / `#8B66F0` | the signal colour: the active thing, links, focus, primary buttons |
| `--sigink` | `#0F0E14` | `#FFFFFF` | text on `--sig` |
| `--ok` `--warn` `--bad` | green / amber / red | darker versions | status only (see §3) |
| `--track` | | | the empty part of bars and gauges |
| `--shade` | | | the dimmed backdrop behind dialogs and drawers |

Purple is the only accent colour. Never add a second one (no blue links, no teal headers). If something needs
attention, give it a status colour, not a new hue.

**Type.** Text is Geist. Numbers, ids, paths, units, timestamps and labels are Geist Mono: use class `mono`, or
`cap` for small section labels. Mono uses tabular figures, so columns of numbers line up. Use these sizes:

| size | use |
|---|---|
| 22–26px | big numbers (KPIs, tile values) |
| 13–14px | body text, names |
| 11–12px | mono details |
| 10–10.5px | badges and source tags |

Nothing is smaller than 10px.

**Shape.**
- Use hairlines (1px `--line`), not cards with shadows.
- The corner radius is 4px (6px on dialogs). Never use pill-shaped buttons. The only round shape is the on/off toggle.
- The spacing scale is 4, 6, 8, 10, 12, 14, 16 and 20px. Pages have 20px side padding, or 16px when there is little
  room.

## 2. Components (`$lab/…`)

| component | what it is |
|---|---|
| `Glyph status=` | the status mark: ● ▲ ■ ○ in its colour, with a title |
| `Section title= src=` | a facet or panel section: a `~/title` label on the left, the module tag on the right, a hairline below |
| `Lines items=` | a compact list of `{p (prefix glyph), s (status), t (text)}` |
| `Metric`, `Stats` | a big mono value with a dim unit and a sub-line |
| `Bar value= color=` | a 0–100 bar (memory, disk, quota). It grows in on first paint |
| `Gauge`, `Spark` | a ring gauge and an 80×18 sparkline |
| `Icon name=` | 1.8px stroke icons. The set is in `icons.js`; add an icon there instead of using inline SVG |

Global classes:
- `btn`, `btn primary`: buttons.
- `seg`: a segmented switch; the active button has `aria-pressed=true`.
- `field`: an input.
- `lnk`: a text button.
- `row`: a hover row.
- `scroll-x`: a horizontal scroller for wide tables.
- `spin`: the `|/-\` spinner.
- `fade`, `grow`, `pulse`: motion.

## 3. Status vocabulary

Status is always **shape + colour**, so it still reads in grayscale and for colour-blind users:

| mark | status | means |
|---|---|---|
| ● | `ok` | working |
| ▲ | `warn` | needs a look soon |
| ■ | `bad` | broken now |
| ○ | `off` | stopped or disabled on purpose |
| · | `unknown` | no data yet |

- These five are the only statuses. Map whatever your backend says onto them.
- An object is never shown greener than its worst open alert. The shell enforces this.
- Use `--warn`/`--bad` only for status. A big number that is fine stays `--ink`.
- An alert has a `title` (what is wrong, in words), a `detail` (the evidence), `since`, an optional `object`, and an
  optional `snooze` action.

## 4. Wording and density

- **Labels are lowercase mono nouns.** Write `cpu`, `mem`, `updates`, `backup`, `alerts`. Never abbreviate a
  column header into something people have to guess (`al`, `upd`, `zz`). If the word does not fit, the column is too
  narrow.
- **Every button says what it does.** Name the verb and, when it matters, the amount or target: `snooze 1d`,
  `upgrade 5`, `reboot`, `backup now`. Never use a bare number or an icon alone for something that changes state.
  A row of time buttons needs its verb once: `snooze 1h · 1d · 7d`.
- **Ages read as ages.** Write `3h ago` in lists and `since 3h` in tooltips. Write a duration as `4d 2h`, never as
  a timestamp.
- **Paths, not titles.** Section labels look like `~/alerts`, `~/objects · 42`. The `~/` prefix is `--faint`. Counts
  go after a `·`.
- **Little text.** Put a number before a sentence. Put a sentence in a tooltip or a detail line, not in the main row.
  An empty state is one dim mono line that says what is missing (`no machines yet`, `all quiet ●`), never an
  illustration.
- **Linux touches, used sparingly.** These are:
  - `user@lab:~$` in the brand;
  - `$ grep …` as the placeholder of every filter box;
  - `tail -f events` over event lists;
  - the `|/-\` spinner while loading.

  Do not add more jokes than that.
- **Names.** A view's label is the noun of what it shows (`Policies`, `Task sequences`). The shell makes labels
  unique by adding the module name when two modules use the same label, so do not prefix your own module's name. A
  module with one view is listed under the module's name.

## 5. Navigation contract

- The rail groups modules by the manifest's `category`:
  - `infrastructure`
  - `network`
  - `monitoring`
  - `identity`
  - `media`
  - `apps`
  - `tools`

  Pick the one a user would look under.
- Declare pages as `views: [{id, label, icon, component, min?, props?}]`. A view id is global, so prefix it with the
  module id (`<module>-<page>`). Use `min: 'admin' | 'owner'` to hide a view from lower roles.
- A module without views still appears in the rail. Its entry opens the generated module page, which shows its kpis,
  alerts, tiles and objects. Add views only when that generated page is not enough.
- Links: `#/<module>` opens a one-view module (or the module page), `#/<view-id>` opens a view, and
  `#/<view>/<object-id>` opens an object in the panel.
- **KPIs jump.** Give every kpi a `view` (a view id or a module id) or `open` (an object id). Without either, the
  shell sends it to the module's first page. A kpi that goes nowhere renders as plain text with no hover and no
  arrow.
- **Ticker items** with `object`/`open` or `view` can be clicked. Set them whenever an event is about something.
- **Actions** (`actions(object)`) appear in the object panel header and in Ctrl-K tasks. Each verb shows once: when
  two modules offer the same label, the more specific module's action wins and the button names the module. So:
  - Start labels with the verb: `reboot`, `restart <service>`, `console`, `snapshot`, `backup now`, `upgrade 3`.
    Ctrl-K matches "restart x" and "snapshot x" on that first word.
  - Do not repeat a header action as a button inside your facet. Put details in the facet and the verb in
    `actions()`.
  - Owner-only routes give admins an "ask owner" verdict automatically. Never hide an action because of a role; the
    verdict handles it.
- **Search.**
  - `search()` returns static rows. A row that names an `object` folds into that object's row in Ctrl-K, as a badge.
  - `lookup()` is async and limited to 4 rows per module. It ranks below objects and pages, so return your best
    matches first.
  - Do not return a row for every file you have.

## 6. Tiles

- Tiles declare `w` (columns of 12) and `h` (rows of about 136px). `h` is a **maximum**. A tile is as tall as its
  content, so keep the content natural-height. A list that should scroll inside the tile must fill it
  (`flex: 1; min-height: 0; overflow: auto`). The wall then gives it the full declared height.
- The wall sorts tiles worst-first, using the module's backend health and its worst open alert, and keeps the
  user's order within each band. Tiles do not need to signal urgency themselves.
- One idea per tile: a big value, its unit and one sub-line, and optionally a sparkline or a short list (at most
  about 8 rows).

## 7. Phone (≤ 860px, designed for 390px)

- The top bar is one row: brand, view switch (icons), live dot, approvals, search, ☰. The rail opens as a drawer.
- **No horizontal page scroll, ever.** Wide tables go inside `scroll-x`, and long words and URLs get
  `overflow-wrap: anywhere`. Fixed widths must give way: use `min-width: 0` on flex and grid children.
- Tap targets are at least 32px high in lists and drawers.
- Tiles span the full width. Multi-column layouts stack. The object panel becomes a full-screen sheet with a close
  button.
- Never rely on hover. A tooltip may only repeat what is already visible.

## 8. Motion

There is a little motion, never much:
- the spinner while loading;
- a blinking cursor in the brand;
- a scrolling ticker that pauses on hover;
- a pulse on the live dot;
- bars that grow in;
- a 0.3s fade on new content.

All of it stops under `prefers-reduced-motion`. Nothing moves to decorate.

## 9. Checklist before you ship a module page

- [ ] Uses only tokens and shared components. Both themes checked.
- [ ] Every status uses ● ▲ ■ ○ with its colour. No colour without a shape.
- [ ] No cryptic labels. Every button names its verb (and amount).
- [ ] KPIs have `view`/`open`. Alerts have `object` when they are about one.
- [ ] Actions are in `actions()` and not repeated as facet buttons. Labels start with the verb.
- [ ] Works at 390px with no horizontal scroll. Works as admin (ask-owner verdicts) and, if the module allows guests,
      as a guest.
- [ ] No console errors. A backend that says "no access" leaves the module quietly empty.
