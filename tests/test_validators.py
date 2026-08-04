"""Tests for the rollback, monitoring, and validation plan validators."""

import pytest

from preflightops.validators import (
    MIN_ROLLBACK_LENGTH,
    VAGUE_ROLLBACK_PHRASES,
    is_bad_rollback_plan,
    is_monitoring_plan_incomplete,
    is_validation_plan_valid,
)

GOOD_ROLLBACK_PLAN = (
    "Roll back to checkout-api:3.1.0 using the production deploy pipeline if the "
    "5xx rate exceeds 1% in the first 30 minutes. Owner: payments-team."
)


# ---------------------------------------------------------------------------
# is_bad_rollback_plan
# ---------------------------------------------------------------------------
class TestIsBadRollbackPlan:
    def test_none_is_bad(self):
        assert is_bad_rollback_plan(None) is True

    def test_empty_string_is_bad(self):
        assert is_bad_rollback_plan("") is True

    def test_whitespace_only_is_bad(self):
        assert is_bad_rollback_plan("    \n\t  ") is True

    def test_too_short_is_bad(self):
        short = "x" * (MIN_ROLLBACK_LENGTH - 1)
        assert is_bad_rollback_plan(short) is True

    def test_exactly_min_length_is_ok(self):
        # A plan exactly at the minimum length that is not a vague phrase.
        plan = "a" * MIN_ROLLBACK_LENGTH
        assert is_bad_rollback_plan(plan) is False

    @pytest.mark.parametrize("phrase", VAGUE_ROLLBACK_PHRASES)
    def test_vague_phrase_alone_is_bad(self, phrase):
        # Pad short phrases so length is not the reason it is flagged; the
        # vague-phrase check lowercases and matches the whole cleaned string.
        padded = phrase + (" " * (MIN_ROLLBACK_LENGTH - len(phrase) + 1))
        assert is_bad_rollback_plan(padded) is True

    def test_vague_phrase_case_insensitive(self):
        padded = "Rollback If Needed" + (" " * MIN_ROLLBACK_LENGTH)
        assert is_bad_rollback_plan(padded) is True

    def test_good_plan_is_not_bad(self):
        assert is_bad_rollback_plan(GOOD_ROLLBACK_PLAN) is False

    def test_vague_phrase_within_longer_plan_is_not_bad(self):
        # Only an exact (whole-string) vague phrase is flagged; a real plan
        # that happens to contain the word "revert" is acceptable.
        plan = (
            "If the error rate climbs above 2% we will revert to the previous "
            "container image via the deploy pipeline within 10 minutes."
        )
        assert is_bad_rollback_plan(plan) is False


# ---------------------------------------------------------------------------
# is_monitoring_plan_incomplete
# ---------------------------------------------------------------------------
class TestIsMonitoringPlanIncomplete:
    def test_non_dict_is_incomplete(self):
        assert is_monitoring_plan_incomplete(None) is True
        assert is_monitoring_plan_incomplete("dashboards") is True
        assert is_monitoring_plan_incomplete(["alerts"]) is True

    def test_empty_dict_is_incomplete(self):
        assert is_monitoring_plan_incomplete({}) is True

    def test_single_field_is_incomplete(self):
        plan = {"dashboards": ["https://grafana.example.com/d/checkout"]}
        assert is_monitoring_plan_incomplete(plan) is True

    def test_two_fields_is_complete(self):
        plan = {
            "dashboards": ["https://grafana.example.com/d/checkout"],
            "alerts": ["checkout-error-rate"],
        }
        assert is_monitoring_plan_incomplete(plan) is False

    def test_empty_values_do_not_count(self):
        # Keys present but empty should not count toward completeness.
        plan = {"dashboards": [], "alerts": "", "logs": None}
        assert is_monitoring_plan_incomplete(plan) is True

    def test_all_fields_present_is_complete(self):
        plan = {
            "dashboards": ["d"],
            "alerts": ["a"],
            "validation_window": "15 minutes",
            "success_criteria": ["error rate below 2%"],
            "logs": ["app logs"],
        }
        assert is_monitoring_plan_incomplete(plan) is False


# ---------------------------------------------------------------------------
# is_validation_plan_valid
# ---------------------------------------------------------------------------
class TestIsValidationPlanValid:
    def test_non_list_is_invalid(self):
        assert is_validation_plan_valid(None) is False
        assert is_validation_plan_valid("smoke tests") is False
        assert is_validation_plan_valid({"step": "smoke"}) is False

    def test_empty_list_is_invalid(self):
        assert is_validation_plan_valid([]) is False

    def test_non_empty_list_is_valid(self):
        assert is_validation_plan_valid(["Confirm smoke tests pass"]) is True
