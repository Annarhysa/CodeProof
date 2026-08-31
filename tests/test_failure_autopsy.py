from evaluator.failure_autopsy import classify_failure


def test_pass_verdict_needs_no_autopsy():
    assert classify_failure("PASS", "everything worked", []) is None


def test_clone_failure_classified_as_environment():
    evidence = [{"claim": "Could not clone repository", "evidence": ""}]
    autopsy = classify_failure("ABSTAIN", "Could not clone repository; no evidence collected.", evidence)
    assert autopsy.category == "Environment failure"


def test_could_not_reproduce_classified_correctly():
    autopsy = classify_failure(
        "ABSTAIN",
        "Could not reproduce the reported bug at this commit; insufficient evidence to evaluate a fix.",
        [],
    )
    assert autopsy.category == "Failed reproduction"


def test_no_file_changes_classified_as_incorrect_patch():
    autopsy = classify_failure(
        "ABSTAIN",
        "Agent failed while generating or verifying a patch: agent produced no file changes during propose_fix",
        [],
    )
    assert autopsy.category == "Incorrect patch"


def test_regression_classified_correctly():
    autopsy = classify_failure("FAIL", "2 existing test(s) failed", [])
    assert autopsy.category == "Regression"


def test_skeptic_failure_classified_as_edge_case():
    autopsy = classify_failure("FAIL", "1 adversarial scenario(s) failed", [], skeptic_failed=True)
    assert autopsy.category == "Edge case"


def test_unknown_failure_falls_back_to_weak_test_coverage():
    autopsy = classify_failure("FAIL", "something bizarre and unmatched", [])
    assert autopsy.category == "Weak test coverage"
    assert autopsy.applicable is True
