from evaluator.evidence import EvidenceTimeline


def test_evidence_timeline_records_and_serializes():
    timeline = EvidenceTimeline()
    timeline.record(claim="Bug reproduced", evidence="$ python repro.py\nBUG REPRODUCED", passed=True)
    timeline.record(claim="Tests failed", evidence="1 failed", passed=False, extra="context")

    entries = timeline.to_list()
    assert len(entries) == 2
    assert entries[0]["claim"] == "Bug reproduced"
    assert entries[0]["passed"] is True
    assert entries[1]["passed"] is False
    assert entries[1]["metadata"] == {"extra": "context"}
