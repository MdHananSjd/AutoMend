from app.classifier import FailureClassifier
from tests.mock_data import MOCK_SCENARIOS

def test_healthy_classification():
    data = MOCK_SCENARIOS["healthy"]
    result = FailureClassifier.classify(data["logs"], data["metrics"], data["current_revision"], data["last_known_good_revision"])
    assert result is None

def test_error_rate_spike():
    data = MOCK_SCENARIOS["error_rate_spike"]
    result = FailureClassifier.classify(data["logs"], data["metrics"], data["current_revision"], data["last_known_good_revision"])
    assert result["failure_type"] == "error_rate_spike"
    assert result["metrics"]["error_rate"] == 0.85

def test_memory_leak():
    data = MOCK_SCENARIOS["memory_leak"]
    result = FailureClassifier.classify(data["logs"], data["metrics"], data["current_revision"], data["last_known_good_revision"])
    assert result["failure_type"] == "memory_leak"
    assert result["metrics"]["memory_mb"] == 850

def test_crash_loop():
    data = MOCK_SCENARIOS["crash_loop"]
    result = FailureClassifier.classify(data["logs"], data["metrics"], data["current_revision"], data["last_known_good_revision"])
    assert result["failure_type"] == "crash_loop"
    assert result["metrics"]["restart_count"] == 5
    assert result["last_known_good_revision"] == "rev-001"
    assert result["revision_id"] == "rev-002"

def test_bad_deploy():
    data = MOCK_SCENARIOS["bad_deploy"]
    result = FailureClassifier.classify(data["logs"], data["metrics"], data["current_revision"], data["last_known_good_revision"])
    assert result["failure_type"] == "bad_deploy"

def test_health_check_failure():
    data = MOCK_SCENARIOS["health_check_failure"]
    result = FailureClassifier.classify(data["logs"], data["metrics"], data["current_revision"], data["last_known_good_revision"])
    assert result["failure_type"] == "health_check_failure"

def test_dependency_failure():
    data = MOCK_SCENARIOS["dependency_failure"]
    result = FailureClassifier.classify(data["logs"], data["metrics"], data["current_revision"], data["last_known_good_revision"])
    assert result["failure_type"] == "dependency_failure"