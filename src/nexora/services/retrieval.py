"""Finds the Nexora policy passages that apply to a request.

A passage is one numbered section of a policy, identified as "NX-PUR-001 §5".
Two sources are combined, in this order:

1. Anchored passages: the sections that the flagged rules cite in
   config/rules.yaml. They are certain to apply, so they are always included.
2. Lexical search (BM25) over every section, with the description, the
   justification and the rule messages as the query. It brings in sections
   that no rule names, such as emergency purchases or frame agreements.

Retrieval only proposes passages. Whether a passage supports a statement is
checked later, in code, against the passages returned here.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

SECTION = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)
WORD = re.compile(r"[a-z0-9€]+")
_STOPWORD_TEXT = """a an and are as at be by for from has have in is it its of on or that the
this to was were will with within without per our we you your their they not no can may must all
any each more than other such"""
STOPWORDS = frozenset(_STOPWORD_TEXT.split())


@dataclass(frozen=True)
class Passage:
    id: str  # "NX-PUR-001 §5"
    doc_id: str
    doc_title: str
    section: int
    section_title: str
    text: str

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Hit:
    passage: Passage
    reason: str  # "rule:<rule_id>" or "search"
    score: float


def _front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    _, header, body = text.split("---", 2)
    return yaml.safe_load(header) or {}, body


def parse_document(text: str) -> list[Passage]:
    meta, body = _front_matter(text)
    doc_id, title = str(meta["doc_id"]), str(meta["title"])
    matches = list(SECTION.finditer(body))
    passages = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[match.end() : end].strip()
        if content:
            number = int(match.group(1))
            passages.append(
                Passage(
                    id=f"{doc_id} §{number}",
                    doc_id=doc_id,
                    doc_title=title,
                    section=number,
                    section_title=match.group(2).strip(),
                    text=content,
                )
            )
    return passages


def tokenize(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]


class KnowledgeBase:
    """The policy sections, indexed for BM25 search."""

    def __init__(self, passages: list[Passage], k1: float = 1.5, b: float = 0.75) -> None:
        self.passages = passages
        self.by_id = {p.id: p for p in passages}
        self._k1, self._b = k1, b
        self._docs = [Counter(tokenize(f"{p.section_title} {p.text}")) for p in passages]
        self._lengths = [sum(d.values()) for d in self._docs]
        self._avg = sum(self._lengths) / max(len(self._lengths), 1)
        frequency: Counter[str] = Counter()
        for doc in self._docs:
            frequency.update(doc.keys())
        n = len(passages)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in frequency.items()}

    @classmethod
    def from_directory(cls, directory: Path) -> KnowledgeBase:
        passages: list[Passage] = []
        for path in sorted(directory.glob("*.md")):
            passages += parse_document(path.read_text(encoding="utf-8"))
        return cls(passages)

    def search(self, query: str, limit: int) -> list[tuple[Passage, float]]:
        terms = set(tokenize(query))
        scored = []
        for passage, doc, length in zip(self.passages, self._docs, self._lengths, strict=True):
            score = 0.0
            for term in terms & doc.keys():
                tf = doc[term]
                norm = tf + self._k1 * (1 - self._b + self._b * length / self._avg)
                score += self._idf[term] * tf * (self._k1 + 1) / norm
            if score > 0:
                scored.append((passage, score))
        scored.sort(key=lambda item: (-item[1], item[0].id))
        return scored[:limit]

    def resolve(self, policy_ref: str | None) -> Passage | None:
        """'NX-PUR-001 §5' -> that passage; None when the reference is unknown."""
        return self.by_id.get(policy_ref.strip()) if policy_ref else None


@lru_cache(maxsize=4)
def load_knowledge_base(directory: Path) -> KnowledgeBase:
    return KnowledgeBase.from_directory(directory)


def retrieve(
    kb: KnowledgeBase,
    query: str,
    anchors: list[tuple[str, str | None]],
    search_limit: int = 3,
    min_score: float = 3.0,
    max_passages: int = 6,
) -> list[Hit]:
    """Anchored passages first (one per (rule_id, policy_ref) pair), then the
    best search hits above `min_score`, without duplicates."""
    hits: list[Hit] = []
    seen: set[str] = set()
    for rule_id, ref in anchors:
        passage = kb.resolve(ref)
        if passage and passage.id not in seen:
            hits.append(Hit(passage, f"rule:{rule_id}", 0.0))
            seen.add(passage.id)
    for passage, score in kb.search(query, limit=search_limit + len(seen)):
        if len(hits) >= max_passages:
            break
        if score >= min_score and passage.id not in seen:
            hits.append(Hit(passage, "search", round(score, 2)))
            seen.add(passage.id)
    return hits[:max_passages]
