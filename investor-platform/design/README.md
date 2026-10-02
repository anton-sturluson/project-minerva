# Homepage Club

**Selected direction, 1 October 2026.** The user chose Homepage Club after reviewing three rounds of concepts: “Yes homepage club!!!” This is the investor platform's visual baseline. The application shell follows this direction.

## Open the reference

- [homepage-club.html](homepage-club.html) — self-contained browser preview; open directly or serve this directory locally.
- [homepage-club.fragment.html](homepage-club.fragment.html) — original editable fragment, preserved from the selected concept.
- [Investor Platform Design skill](../../.claude/skills/investor-platform-design/SKILL.md) — project-scoped instructions for applying this direction. Invoke as `$investor-platform-design`.

From the repository root:

```sh
python3 -m http.server 5181 --bind 127.0.0.1 --directory investor-platform/design
```

Open `http://127.0.0.1:5181/homepage-club.html`. No account, service, API key, portfolio sheet, or live data is required. The standalone wrapper provides local preview state; the design follows the browser's light/dark appearance.

The HTML export was produced with the bundled visualize renderer. To regenerate it after editing the fragment, use the installed visualize skill's `scripts/render.py`:

```sh
python3 <visualize-skill>/scripts/render.py \
  investor-platform/design/homepage-club.fragment.html \
  investor-platform/design/homepage-club.html --title "Homepage Club" --force
```

The exported file is committed so viewing the reference does not require that renderer. Keep it in sync with the fragment when deliberately revising the reference. Do not copy its preview runtime into the application.

## Character

A personal corner of the early web, kept by a patient investor. Plain, useful, slightly eccentric, and carefully aligned. The funkiness lives in the italic `minerva!` wordmark, its subtle yellow offset, asterisk ornaments, bracket links, tiny badges, and occasional tilted `NEW!` label. Data remains calm and legible.

The approved composition uses a centered page, double rules, compact blue links, a holdings table beside a small notebook column, and a two-column directory below. Research becomes a readable document. Navigation is text, not a collection of dashboard cards. On smaller screens the columns stack; the financial table can scroll horizontally within its own container.

## Palette and type

The fragment is the exact visual reference. These are the main tokens it uses:

| Role | Light | Dark |
| --- | --- | --- |
| Paper | `#fffef9` | `#222421` |
| Ink | `#191b20` | `#eeeeda` |
| Link blue | `#00009b` | `#b1bfff` |
| Plum | `#62256c` | `#dcafe4` |
| Butter yellow | `#f5dc62` | `#6b5929` |
| Lilac | `#e8dcf2` | `#44364e` |
| Rules | `#aaa69a` | `#686b61` |
| Neutral fill | `#e8e6dd` | `#363933` |

- **Times New Roman / Times:** body, headings, and expressive italic wordmark.
- **Courier New:** dates, small labels, badges, and selected numeric summaries.
- **Arial:** dense financial tables and supporting annotations.
- Body text is approximately 15–16px. Supporting text in the study bottoms out at 11px; treat this as a lower bound, not a target for new content.

## Applying it to the product

- Use familiar underlined links and square native-looking controls. Preserve visible focus and keyboard operation.
- Use decoration sparingly, particularly around figures. Do not use `NEW!` or an endorsement-style badge to imply unverified product or financial facts.
- Keep values aligned and financial status explicit. The reference's amounts, note titles, and badge copy are illustrative; they must not seed real accounts or masquerade as implemented features.
- Preserve responsive layouts and adequate touch targets. Avoid blinking, marquees, novelty cursors, autoplay, and noisy textures.
- Keep the homepage's warmth and personality. Large rounded cards, oversized metric tiles, pill navigation, glossy gradients, and a generic SaaS sidebar would move away from the selected direction.
- Homepage Club alone is selected. Other experimental CSS embedded in the original fragment is inactive; Odd Lot and The Little Review are not additional approved themes.

## Verification

The saved standalone export was exercised in a browser at desktop and 320px widths. Checks covered portfolio, notebook, and source-index navigation; topic changes; marking a note for follow-up; and restoring the selected note and mark after reload. The narrow source-index view had no page-level horizontal overflow, and no browser console errors were observed. The original selected concept also had its narrow holdings layout checked. Skill validation and reference-link checks passed.

Recheck the committed standalone export when updating it. Application styling and its automated tests belong to a separate implementation ticket; the application test suite was not run for this reference-only change.

## References

### Historical visual inspiration

- [Excite in 1997 — Web Design Museum](https://www.webdesignmuseum.org/gallery/excite-in-1997): distinctive masthead, compact directory links, and small footer badges informed this original interpretation. The date is the museum's screenshot label, not an independently verified capture date.

### Project decision

- User approval in the Minerva investor-platform design conversation, 1 October 2026: “Yes homepage club!!! Can we store that in the repo?” The committed fragment preserves the approved concept.
