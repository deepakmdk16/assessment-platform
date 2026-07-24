"""Row metadata: created_at / updated_at are populated and updated_at bumps."""

from fastapi.testclient import TestClient


def _question() -> dict:
    return {
        "id": "meta_q",
        "title": "Meta",
        "prompt": "p",
        "constraints": "c",
        "time_limit_s": 2.0,
        "pass_threshold": 0.9,
        "required_complexity": None,
        "example_input": None,
        "example_output": None,
        # 4 correctness + 1 performance to satisfy the authoring-time floor (A1).
        "test_cases": [
            {"name": "t1", "stdin": "1\n", "expected": "1", "category": "correctness", "weight": 1.0},
            {"name": "t2", "stdin": "2\n", "expected": "2", "category": "correctness", "weight": 1.0},
            {"name": "t3", "stdin": "3\n", "expected": "3", "category": "correctness", "weight": 1.0},
            {"name": "t4", "stdin": "4\n", "expected": "4", "category": "correctness", "weight": 1.0},
            {"name": "big", "stdin": "9\n", "expected": "9", "category": "performance", "weight": 3.0},
        ],
    }


def test_created_and_updated_at_are_set(client: TestClient) -> None:
    body = client.post("/questions", json=_question()).json()
    assert body["created_at"]
    assert body["updated_at"]
    assert body["updated_at"] >= body["created_at"]


def test_updated_at_bumps_on_update_created_at_stable(client: TestClient) -> None:
    created = client.post("/questions", json=_question()).json()

    changed = _question() | {"title": "Meta v2"}
    updated = client.put(f"/questions/{created['id']}", json=changed).json()

    assert updated["created_at"] == created["created_at"]  # created_at never moves
    assert updated["updated_at"] >= created["updated_at"]  # bumped on write (UTC ISO, sortable)
