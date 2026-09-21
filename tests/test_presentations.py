"""Regression checks for the optional presentation build tooling."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("pptx")
pytest.importorskip("reportlab")
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_deck", ROOT / "presentations/build_deck.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def content():
    return json.loads((ROOT / "presentations/participant-briefing.json").read_text())


def test_build_exports_share_slide_content(tmp_path):
    data = content()
    report = builder.build(tmp_path)
    slides = builder.Presentation(tmp_path / "participant-briefing.pptx").slides
    assert len(slides) == report["slides"] == len(data["slides"])
    notes = (tmp_path / "participant-speaker-notes.md").read_text()
    for slide, source in zip(slides, data["slides"]):
        text = " ".join(shape.text.replace("\n", " ") for shape in slide.shapes if shape.has_text_frame)
        assert source["title"].replace("\n", " ") in text
        assert source["notes"] in slide.notes_slide.notes_text_frame.text
        assert source["notes"] in notes
    assert (tmp_path / "participant-briefing.pdf").read_bytes().startswith(b"%PDF-")
    assert json.loads((tmp_path / "layout-check.json").read_text()) == report


@pytest.mark.parametrize("fault,match", [
    ("overlap", "Overlapping"), ("bounds", "outside diagram"),
    ("endpoint", "endpoint"), ("reference", "Missing repository source"),
])
def test_rejects_bad_graphs_and_stale_references(fault, match):
    data = copy.deepcopy(content())
    graph = next(s for s in data["slides"] if s["layout"] == "graph")
    if fault == "overlap":
        graph["nodes"][1]["x"] = graph["nodes"][0]["x"]
    elif fault == "bounds":
        graph["nodes"][0]["x"] = 600
    elif fault == "endpoint":
        graph["edges"][0]["from"] = "missing-node"
    else:
        graph["sources"] = ["src/harness/nonexistent.py"]
    with pytest.raises(ValueError, match=match):
        builder.validate_spec(data)


def test_failed_render_does_not_replace_published_files(tmp_path, monkeypatch):
    artifact = tmp_path / "participant-briefing.pdf"
    artifact.write_bytes(b"previous export")
    def fail(*args):
        raise ValueError("render failed")
    monkeypatch.setattr(builder.Deck, "render", fail)
    with pytest.raises(ValueError, match="render failed"):
        builder.build(tmp_path)
    assert artifact.read_bytes() == b"previous export"
    assert list(tmp_path.iterdir()) == [artifact]
