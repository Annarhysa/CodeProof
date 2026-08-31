from unittest.mock import MagicMock

from evaluator.skeptic import run_skeptic_review


def test_skeptic_all_scenarios_pass():
    agent = MagicMock()
    agent.run_custom_stage.return_value = (
        '{"scenarios": [{"name": "empty list", "passed": true, "notes": "handled correctly"}]}'
    )

    result = run_skeptic_review(agent, "title", "body", "diff", "explanation")

    assert result.ran is True
    assert result.generated == 1
    assert result.failed == 0
    assert result.passed == 1


def test_skeptic_some_scenarios_fail():
    agent = MagicMock()
    agent.run_custom_stage.return_value = (
        '{"scenarios": ['
        '{"name": "empty list", "passed": true, "notes": "ok"}, '
        '{"name": "negative bound", "passed": false, "notes": "crashed"}'
        "]}"
    )

    result = run_skeptic_review(agent, "title", "body", "diff", "explanation")

    assert result.generated == 2
    assert result.passed == 1
    assert result.failed == 1
    assert "not fully verified" in result.summary


def test_skeptic_unparseable_output_defaults_to_not_ran():
    agent = MagicMock()
    agent.run_custom_stage.return_value = "I looked into it but couldn't decide."

    result = run_skeptic_review(agent, "title", "body", "diff", "explanation")

    assert result.ran is False
    assert result.generated == 0


def test_skeptic_agent_exception_does_not_propagate():
    agent = MagicMock()
    agent.run_custom_stage.side_effect = RuntimeError("boom")

    result = run_skeptic_review(agent, "title", "body", "diff", "explanation")

    assert result.ran is False
    assert "boom" in result.summary
