from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from harness.ideas import model


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supported: bool


def test_stage_model_overrides(monkeypatch):
    monkeypatch.setenv("MINERVA_IDEAS_SOURCE_MODEL", "gpt-6.1-sol")
    assert model.resolve_models().source == "gpt-6.1-sol"
    assert set(vars(model.resolve_models("gemini-2.5-flash-lite")).values()) == {
        "gemini-2.5-flash-lite"
    }


@pytest.mark.parametrize(
    "status,parsed",
    [("completed", Answer(supported=True)), ("incomplete", None), ("completed", None)],
)
def test_openai_structured_response_and_failure_classification(
    tmp_path, monkeypatch, status, parsed
):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-used")
    calls = []
    response = SimpleNamespace(
        status=status, output_parsed=parsed, model_dump=lambda **kw: {"status": status}
    )

    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 180, "max_retries": 0}
            self.responses = SimpleNamespace(
                parse=lambda **kwargs: calls.append(kwargs) or response
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(model.openai, "OpenAI", Client)
    if parsed:
        assert (
            model.generate("Is this supported?", Answer, tmp_path, model="gpt-6-luna")
            == parsed
        )
    else:
        with pytest.raises(model.ModelError):
            model.generate("Is this supported?", Answer, tmp_path, model="gpt-6-luna")
    assert calls[0]["model"] == "gpt-6-luna"
    assert calls[0]["text_format"] is Answer
    assert calls[0]["store"] is False
    assert list((tmp_path / "research/model").glob("*.response.json"))
