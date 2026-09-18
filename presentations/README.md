# Participant presentation

- [PowerPoint deck](participant-briefing.pptx): editable 16:9 slides with speaker notes.
- [PDF deck](participant-briefing.pdf): matching vector PDF for easy sharing.
- [Speaker notes](participant-speaker-notes.md): notes and implementation references.
- [Organizer checklist](ORGANIZER-CHECKLIST.md): event policies to confirm before evaluation.

The deck has 19 briefing slides and 3 API reference slides, designed for roughly
20 minutes plus questions. It explains participant harness design, a pre-generated
test environment, information boundaries, business rules, scoring, lifecycle handling,
resource budgets, per-action/per-day token tracking, practice commands, and the run viewer.

Actual test parameters are not embedded in the deck. Numerical values are labeled
as current implementation defaults. Submission packaging, allowed models, official
budgets, lifecycle handoff, repeats, and tie-breaks remain organizer decisions.

The editable content is [participant-briefing.json](participant-briefing.json).
To rebuild the PowerPoint and PDF:

```sh
python3 -m pip install -r presentations/requirements.txt
python3 presentations/build_deck.py
```

Rendering uses DejaVu Sans and DejaVu Sans Mono. On Linux the fonts are read from
`/usr/share/fonts/truetype/dejavu`; set `VENDING_SLIDE_FONT_DIR` for another folder.
The fonts should be installed when editing the PPTX to preserve layout; the PDF
embeds its font subsets. All diagrams and text are native shapes/text, not flattened
slide images. `layout-check.json` records the generator's text-bounds checks.
