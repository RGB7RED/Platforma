import pytest

from app.planning import (
    OutputContract,
    OutputContractViolation,
    TaskMode,
    build_task_plan,
    validate_output_contract,
)


@pytest.mark.asyncio
async def test_heuristic_micro_file_plan_extracts_path():
    task_text = (
        "Return EXACTLY this JSON: {\"files\":[{\"path\":\"RadJab.txt\","
        "\"content\":\"Moama\"}]}"
    )
    codex = {
        "workflow": {
            "stages": ["research", "design", "implementation", "review"],
            "max_iterations": 15,
            "review_required": True,
        }
    }

    plan = await build_task_plan(task_text, codex, allow_llm=False)

    assert plan.mode == TaskMode.micro_file
    assert plan.contract.allowed_files_count == 1
    assert plan.contract.allowed_paths == ["RadJab.txt"]
    assert plan.contract.exact_json_only is True
    assert plan.contract.no_extra_text_outside_json is True


def test_output_contract_validator_accepts_json_only():
    contract = OutputContract(
        exact_json_only=True,
        allowed_files_count=1,
        no_extra_text_outside_json=True,
    )
    raw_text = '{"files":[{"path":"one.txt","content":"hi"}]}'
    parsed = {"files": [{"path": "one.txt", "content": "hi"}]}

    validate_output_contract(contract, raw_text, parsed)


def test_output_contract_validator_rejects_preamble():
    contract = OutputContract(
        exact_json_only=True,
        allowed_files_count=1,
        no_extra_text_outside_json=True,
    )
    raw_text = (
        "Sure, here is the JSON: "
        "{\"files\":[{\"path\":\"one.txt\",\"content\":\"hi\"}]}"
    )
    parsed = {"files": [{"path": "one.txt", "content": "hi"}]}

    with pytest.raises(OutputContractViolation):
        validate_output_contract(contract, raw_text, parsed)


def test_output_contract_validator_rejects_extra_files():
    contract = OutputContract(
        exact_json_only=True,
        allowed_files_count=1,
        no_extra_text_outside_json=True,
    )
    raw_text = (
        '{"files":['
        '{"path":"one.txt","content":"hi"},'
        '{"path":"two.txt","content":"hi"}]}')
    parsed = {
        "files": [
            {"path": "one.txt", "content": "hi"},
            {"path": "two.txt", "content": "hi"},
        ]
    }

    with pytest.raises(OutputContractViolation):
        validate_output_contract(contract, raw_text, parsed)
