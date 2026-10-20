"""Policy passages: parsing, anchored lookup and lexical search."""

from __future__ import annotations

import pytest

from nexora.config import ROOT
from nexora.services.retrieval import KnowledgeBase, parse_document, retrieve


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return KnowledgeBase.from_directory(ROOT / "data" / "knowledge_base")


def test_documents_are_split_into_numbered_sections(kb):
    assert len(kb.passages) == 36
    passage = kb.by_id["NX-PUR-001 §5"]
    assert passage.doc_title == "Global Procurement Policy"
    assert passage.section_title == "Competitive sourcing thresholds"
    assert "At least three written quotes" in passage.text
    assert "## 6." not in passage.text


def test_front_matter_is_required_for_an_id():
    text = "---\ndoc_id: NX-X-1\ntitle: T\n---\n## 1. A\n\nAlpha.\n\n## 2. B\n\nBeta.\n"
    assert [p.id for p in parse_document(text)] == ["NX-X-1 §1", "NX-X-1 §2"]


def test_policy_references_resolve_to_passages(kb):
    assert kb.resolve("NX-PUR-002 §2").section_title == "Approval matrix"
    assert kb.resolve("NX-PUR-999 §1") is None
    assert kb.resolve(None) is None


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Urgent pump replacement, production line stopped, emergency", "NX-PUR-001 §6"),
        ("New supplier not yet in the vendor master, onboarding pending", "NX-PUR-003 §1"),
        ("Order outside the frame agreement and the e-catalog", "NX-PUR-001 §7"),
    ],
)
def test_search_finds_the_section_that_applies(kb, query, expected):
    assert kb.search(query, limit=1)[0][0].id == expected


def test_anchored_passages_come_first_without_duplicates(kb):
    hits = retrieve(
        kb,
        "Emergency replacement, production stopped",
        anchors=[
            ("sourcing_evidence", "NX-PUR-001 §5"),
            ("split_purchase", "NX-PUR-001 §5"),
            ("price_deviation", None),
            ("approval_band", "NX-PUR-002 §2"),
        ],
    )
    ids = [h.passage.id for h in hits]
    assert ids[:2] == ["NX-PUR-001 §5", "NX-PUR-002 §2"]
    assert hits[0].reason == "rule:sourcing_evidence"
    assert "NX-PUR-001 §6" in ids
    assert len(ids) == len(set(ids)) <= 6


def test_weak_matches_are_not_retrieved(kb):
    hits = retrieve(kb, "zebra tango quartz", anchors=[])
    assert hits == []
