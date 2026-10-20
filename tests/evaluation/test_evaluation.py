"""The evaluation harness, run on the whole labelled set with the scripted
provider: every acceptance criterion that does not depend on a language model
must pass. Takes about ten seconds."""

from __future__ import annotations

import pytest

from nexora.evaluation import baselines, runner
from nexora.llm import ScriptedProvider


@pytest.fixture(scope="module")
def figures():
    run = runner.evaluate(ScriptedProvider(), runner.load())
    return runner.metrics(run)


@pytest.mark.parametrize(
    "criterion",
    [
        "1_malformed_rejected",
        "2_rules_and_routing",
        "3_processed_once",
        "4_valid_end_state",
        "6_citations_supported",
        "8_unauthorised_blocked",
        "9_decisions_audited",
        "10_time_and_cost",
    ],
)
def test_criteria_that_do_not_depend_on_the_model_pass(figures, criterion):
    assert figures["criteria"][criterion]["pass"], figures["criteria"][criterion]["detail"]


def test_the_labelled_set_covers_the_scenarios():
    records = runner.load()
    scenarios = {r["scenario"] for r in records}
    assert len(records) >= 150
    assert {
        "invalid",
        "blocked_supplier",
        "duplicate_second",
        "split_purchase",
        "prompt_injection_unseen",
        "mislabelled_category",
    } <= scenarios


def test_the_screen_misses_the_unseen_phrasings_and_says_so(figures):
    missed = figures["failures"]["injection_missed_by_screen"]
    assert len(missed) == 4  # documented limit: the screen is a list of patterns


def test_keyword_baseline():
    assert baselines.keywords({"description": "Hydraulic oil ISO VG 46"}) == "mro_supplies"
    assert baselines.keywords({"description": "Something else", "item_category": "ppe"}) == "ppe"
