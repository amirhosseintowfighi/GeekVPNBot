# RTL and Persian conventions

The rules below are not style preferences. Each exists because breaking it
produces a specific, reproducible bug.

---

## 1. Direction is set once, at the root

`<html lang="fa" dir="rtl">` in `app/layout.tsx`.

Everything downstream uses Tailwind logical properties, which resolve against
that attribute:

| Use | Never use |
| --- | --- |
| `ps-*` / `pe-*` | `pl-*` / `pr-*` |
| `ms-*` / `me-*` | `ml-*` / `mr-*` |
| `start-*` / `end-*` | `left-*` / `right-*` |
| `text-start` / `text-end` | `text-left` / `text-right` |
| `rounded-ss-*` / `rounded-ee-*` | `rounded-tl-*` / `rounded-br-*` |

Because of this there is no mirrored stylesheet anywhere in the project.

Exception: icon-to-label spacing uses `gap`, not a directional margin. A gap
has no direction to get wrong.

---

## 2. Things that must NOT flip

Direction applies to text, not to physics or to Latin identifiers.

| Element | Treatment | Why |
| --- | --- | --- |
| Coupon codes | `dir="ltr"` + monospace | Otherwise the code reorders into nonsense |
| Crypto addresses | `dir="ltr"`, `break-all` | One transposed character loses the money |
| Card numbers | `dir="ltr"`, wide tracking | Read in groups of four, left to right |
| Telegram usernames | `dir="ltr"` | The at-sign jumps to the wrong end |
| Signed amounts | `dir="ltr"` | Plus and minus must stay glued to the number |
| Progress bars | fill from the right | Reading direction |
| Back chevron | points right | Back is toward the start of the line |
| Menu chevron | points left | Forward is toward the end of the line |

`globals.css` sets `[dir="ltr"] { unicode-bidi: isolate }` so an embedded LTR
run cannot drag neighbouring Persian punctuation around with it.

---

## 3. Numerals

All customer-facing numbers go through `fa.ts`. Never interpolate a raw
JavaScript number into Persian copy.

| Separator | Codepoint | Used for |
| --- | --- | --- |
| Thousands | U+066C | grouping in prices |
| Decimal | U+066B | fractional volumes |
| Percent | U+066A | discount and load figures |

The `.nums` class applies `font-variant-numeric: tabular-nums`, so a column of
amounts does not jitter as digits change width.

Input is normalised, not rejected. `normalizeInput()` folds Persian (U+06F0..)
and Arabic-Indic (U+0660..) digits to ASCII before parsing. These look nearly
identical and land on different keyboards; telling a customer their own
numerals are invalid is unacceptable.

---

## 4. Dates

Jalali only. `lib/jalali.ts` is a hand-written port of the bot algorithm,
pinned by `tests/jalali.test.ts` to the same anchors as the Python suite:

- 2026-03-21 maps to 1405-01-01
- 2026-03-20 maps to year 1404, month 12

Gregorian dates never appear in the interface.

`WEEKDAYS` is indexed by `Date.prototype.getDay()`, where 0 is Sunday, not by
the Persian week, which begins on Saturday. The table is ordered to match the
JavaScript index, not the cultural one.

---

## 5. Typography

- Vazirmatn, loaded through `next/font` with `display: swap`.
- Persian needs more line height than Latin. Body copy uses `leading-loose`;
  nothing smaller than `leading-relaxed`.
- ZWNJ (U+200C) is used inside compounds, never a plain space.
- Persian has no italics. Emphasis is weight or colour.
- The Persian question mark is U+061F, not the ASCII one.

---

## 6. Persian source strings are written as escapes

Every Persian literal in `.ts` and `.tsx` is written as a `\uXXXX` escape
rather than inline.

This is defensive, and it comes from a real incident: a large Persian blob was
corrupted mid-write and produced a truncated-escape SyntaxError that took the
whole module down. Escaped source is pure ASCII, so a dropped byte becomes a
visible broken escape instead of silently mangled text that ships.

The cost is readability, so `fa.ts` is the exception. It is the one place that
may hold readable Persian, and everything else composes from it.

---

## 7. Copy tone

- Formal plural address, never informal singular, except in the referral share
  text, which is written to be forwarded to a friend.
- Never blame the customer. Say the balance is insufficient, not that the
  customer has no money.
- State what happens next, not just what failed.
- No untranslated English in the interface. TxID survives only because it is
  what every exchange labels the field.

---

## 8. Colour semantics, fixed app-wide

| Colour | Meaning | Example |
| --- | --- | --- |
| Green | Settled, nothing to do | active subscription, approved payment |
| Amber | Waiting on us | pending review, quota above 75% |
| Red | The customer must act | expired, rejected, suspended, quota above 90% |

A customer should be able to learn these three once and read any screen.

---

## 9. Touch targets and the keyboard

- Minimum interactive height is 44px (`h-11`), the default `Button` size.
- Text inputs are `text-base` (16px) on mobile. Below 16px, iOS Safari zooms
  the webview on focus and there is no way to zoom back out inside Telegram.
- Primary actions sit in a sticky footer above the tab bar, within thumb
  reach, not at the top of a scrolled page.
- Bottom sheets are used instead of centred dialogs for the same reason.
