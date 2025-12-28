"""Tests for payload parsing helpers."""

from app.main import coerce_mapping_payload, normalize_artifact_item


def test_coerce_mapping_payload_json_string():
    """JSON string payloads are parsed into dicts."""
    payload = coerce_mapping_payload('{"foo": "bar"}', field_name="test")
    assert payload == {"foo": "bar"}


def test_coerce_mapping_payload_plain_string():
    """Plain string payloads are wrapped to avoid .get crashes."""
    payload = coerce_mapping_payload("raw text", field_name="test")
    assert payload == {"text": "raw text"}


def test_normalize_artifact_item_parses_payload_string():
    """normalize_artifact_item returns a dict payload from JSON strings."""
    artifact = {
        "id": "artifact-1",
        "type": "review_report",
        "payload": '{"passed": true}',
        "created_at": None,
    }
    normalized = normalize_artifact_item(artifact)
    assert normalized.payload["passed"] is True
