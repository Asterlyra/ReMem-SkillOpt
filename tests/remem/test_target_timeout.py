from contextlib import nullcontext

import pytest
from openpyxl import Workbook

from skillopt.envs.spreadsheetbench import codegen_agent
from skillopt.envs.spreadsheetbench.rollout import process_one_codegen
from skillopt.remem.call_policy import ResearchCallPolicy, use_call_policy


@pytest.mark.parametrize('mode', ['single', 'multi'])
@pytest.mark.parametrize('configured', [None, 120, 240])
def test_frozen_target_timeout_reaches_both_task_agents(tmp_path, monkeypatch, mode, configured):
    payload = tmp_path / 'task1'
    payload.mkdir()
    workbook = Workbook()
    workbook.active['A1'] = 2
    workbook.save(payload / 'initial.xlsx')
    workbook.save(payload / 'golden.xlsx')
    workbook.close()
    seen = []

    def agent(**kwargs):
        seen.append(kwargs['llm_timeout'])
        raise RuntimeError('Synthetic stop before any model or code execution')

    monkeypatch.setattr(codegen_agent, 'run_' + mode, agent)
    context = use_call_policy(ResearchCallPolicy(tmp_path / 'policy', timeout_s=configured)) if configured else nullcontext()
    with context:
        result = process_one_codegen(
            {'id': 'task1', 'instruction': 'Synthetic task', 'spreadsheet_path': 'task1',
             'instruction_type': 'Cell-Level Manipulation', 'answer_position': 'Sheet!A1'},
            str(tmp_path), str(tmp_path / 'output'), '', mode=mode,
        )
    assert seen == [configured if configured is not None else 120]
    assert result['llm_ok'] is False


def test_larger_target_timeout_preserves_shorter_task_deadline(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(codegen_agent, 'is_target_exec_backend', lambda: False)
    monkeypatch.setattr(codegen_agent, 'get_target_client', lambda: object())
    monkeypatch.setattr(codegen_agent, '_build_user', lambda *a, **k: 'Synthetic task')
    monkeypatch.setattr(codegen_agent.time, 'sleep', lambda seconds: None)

    def chat(*args, **kwargs):
        seen.append(kwargs['llm_timeout'])
        return ''

    monkeypatch.setattr(codegen_agent, '_chat_call', chat)
    with use_call_policy(ResearchCallPolicy(tmp_path, timeout_s=240)):
        codegen_agent.run_single('Synthetic task', 'input.xlsx', 'output.xlsx',
                                 llm_timeout=240, task_timeout=15)
    assert len(seen) == 1 and 0 < seen[0] <= 15
