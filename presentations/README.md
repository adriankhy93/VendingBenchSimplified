# Participant presentation

- [PowerPoint deck](participant-briefing.pptx): editable 16:9 slides with speaker notes.
- [PDF deck](participant-briefing.pdf): compressed vector PDF from the same content and layout.
- [Speaker notes](participant-speaker-notes.md): explanations and implementation references.
- [Organizer checklist](ORGANIZER-CHECKLIST.md): event policies to finalize before evaluation.

The deck has 19 briefing slides and 3 REST reference slides, designed for roughly
20 minutes plus questions. It covers business rules, scoring, the structured Pi
controller, bounded stocking and pricing policies, recovery, usage visibility,
practice commands, and the viewer's daily activity and inventory snapshots.

Numbers are labeled as settings in the public `configs/environment.json` practice
configuration, not private evaluation parameters or universal defaults. The current
Pi starter does not enforce an overall token or model-call budget, and its viewer
does not attribute tokens to individual actions or simulated days. Event policies
remain organizer decisions.

Edit [participant-briefing.json](participant-briefing.json), then regenerate all
exports and notes together:

```sh
python3 -m pip install -r presentations/requirements.txt
python3 presentations/build_deck.py
# Optional isolated output directory:
python3 presentations/build_deck.py --output-dir /tmp/vending-deck
python3 -m pytest tests/test_presentations.py
```

The builder checks repository references, text bounds, graph node bounds and
collisions, edge endpoints, table widths, and graph sidebar height. It renders into
a temporary directory before publishing validated artifacts. `layout-check.json`
records the checks and the content source hash. These checks do not replace visual
review or prove that every factual claim is correct; review claims against the
cited implementation when it changes.

Rendering uses DejaVu Sans and DejaVu Sans Mono. Linux fonts default to
`/usr/share/fonts/truetype/dejavu`; override with `VENDING_SLIDE_FONT_DIR`.
Install those fonts when editing the PPTX. The PDF embeds font subsets; text and
diagrams remain vector objects. PowerPoint can render font metrics differently,
so check the deck in the intended presentation application before the event.
