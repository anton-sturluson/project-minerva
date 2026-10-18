"""Check the agent tool boundary without simulating provider call sequences."""

import pytest
from pydantic import ValidationError

from harness.ideas.agents import Browse, Group, Read, Source, _tool, validate_groups


def test_group_assignments_are_disjoint_and_selected() -> None:
    """An agent cannot delegate an unauthorized or concurrently repeated lead."""
    first: Group = Group(ordinals=[1, 2], instructions="Find the shared manager letter")
    second: Group = Group(ordinals=[3], instructions="Find the other manager letter")
    validate_groups([first, second], {1, 2, 3})
    with pytest.raises(ValueError, match="distinct selected"):
        validate_groups([first, first], {1, 2, 3})
    with pytest.raises(ValueError, match="distinct selected"):
        validate_groups([first, second], {1, 2})


def test_source_tools_accept_only_explicit_public_source_arguments() -> None:
    """Tool input cannot supply filesystem paths, evidence, or final database state."""
    candidate: Source = Source(ordinal=1, url="https://example.com/letter.pdf")
    assert candidate.ordinal == 1
    for extra in ("path", "identity", "state"):
        with pytest.raises(ValidationError):
            Source.model_validate(
                {"ordinal": 1, "url": candidate.url, extra: "injected"}
            )
    with pytest.raises(ValidationError):
        Source(ordinal=0, url=candidate.url)
    with pytest.raises(ValidationError):
        Browse(url=candidate.url, link_offset=-1)


def test_source_reader_contract_keeps_strict_parameters_and_original_scope_ids() -> (
    None
):
    """The actual tool schema requires all values and accepts only explicit source IDs."""
    reading: Read = Read(
        url="https://example.com/report.pdf",
        section_ids=["p10", "p11"],
        anchor_ids=["p1"],
        query="Acme",
    )
    assert reading.section_ids == ["p10", "p11"] and reading.anchor_ids == ["p1"]
    schema: dict = _tool("read", Read, "Read original source sections")["parameters"]
    assert set(schema["required"]) == set(schema["properties"])
    with pytest.raises(ValidationError):
        Read.model_validate({**reading.model_dump(), "path": "/tmp/other-source"})
    with pytest.raises(ValidationError):
        Read(url=reading.url, index_offset=-1)


def test_preview_caps_context_without_changing_archived_blocks() -> None:
    """The context limit must not silently remove text from the evidence input."""
    from harness.ideas.agents import preview

    blocks: list[dict[str, str]] = [
        {"id": "p1", "text": "a" * 20000},
        {"id": "p2", "text": "b" * 20000},
    ]
    result: dict = preview({"parts": blocks, "url": "https://example.com/letter.pdf"})
    assert sum(len(part["text"]) for part in result["parts"]) == 24000
    assert result["text_truncated"] is True
    assert result["full_block_count"] == 2
    assert len(blocks[1]["text"]) == 20000


def test_response_replay_preserves_api_aliases_and_encrypted_reasoning() -> None:
    """SDK output uses Python names which must become valid API input fields."""
    from openai.types.responses import ResponseFunctionToolCall, ResponseReasoningItem

    from harness.ideas.agents import replay_item

    call: ResponseFunctionToolCall = ResponseFunctionToolCall.model_validate(
        {
            "id": "fc_test",
            "type": "function_call",
            "call_id": "call_test",
            "name": "search",
            "arguments": '{"query":"manager letter"}',
            "async": True,
        }
    )
    encoded: dict = replay_item(call)
    assert "async_" not in encoded
    assert encoded["async"] is True
    assert encoded["arguments"] == call.arguments
    reasoning: ResponseReasoningItem = ResponseReasoningItem(
        id="rs_test",
        type="reasoning",
        summary=[],
        encrypted_content="encrypted-example",
    )
    assert replay_item(reasoning)["encrypted_content"] == "encrypted-example"
