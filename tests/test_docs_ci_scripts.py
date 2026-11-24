"""Documentation CI helpers: published notebook pages must show outputs (#299)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'ci'))

import check_docs

sys.path.remove(str(ROOT / 'scripts' / 'ci'))

WITH_OUTPUT = '<div class="nboutput nblast docutils container"><pre>1</pre></div>'


def _site(tmp_path, outputs):
    for name in check_docs.NOTEBOOK_PAGES:
        page = tmp_path / name
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(f'<html><body>{outputs.get(name, "")}</body></html>', encoding='utf-8')

    return tmp_path


def _notebook_errors(root, **kwargs):
    return [e for e in check_docs.check_site(root, **kwargs)[2] if e.startswith('Notebook page')]


def test_notebook_pages_without_outputs_are_reported(tmp_path):
    root = _site(tmp_path, {name: WITH_OUTPUT for name in check_docs.NOTEBOOK_PAGES[1:]})
    assert _notebook_errors(root, notebook_outputs=True) == [f'Notebook page has no outputs: {check_docs.NOTEBOOK_PAGES[0]}']
    assert _notebook_errors(root) == []


def test_notebook_pages_with_outputs_pass(tmp_path):
    root = _site(tmp_path, {name: WITH_OUTPUT for name in check_docs.NOTEBOOK_PAGES})
    assert _notebook_errors(root, notebook_outputs=True) == []


def test_missing_notebook_page_is_reported(tmp_path):
    root = _site(tmp_path, {name: WITH_OUTPUT for name in check_docs.NOTEBOOK_PAGES})
    (root / check_docs.NOTEBOOK_PAGES[0]).unlink()
    assert _notebook_errors(root, notebook_outputs=True) == [f'Notebook page missing: {check_docs.NOTEBOOK_PAGES[0]}']


def test_executed_notebook_keeps_skipped_cells_without_outputs(tmp_path):
    nbformat = pytest.importorskip('nbformat')
    pytest.importorskip('nbclient')
    sys.path.insert(0, str(ROOT / 'scripts' / 'ci'))

    try:
        from run_notebooks import executable_copy, with_skipped_cells
    finally:
        sys.path.remove(str(ROOT / 'scripts' / 'ci'))

    source = nbformat.v4.new_notebook(cells=[
        nbformat.v4.new_code_cell('%pip install citylearn'),
        nbformat.v4.new_markdown_cell('text'),
        nbformat.v4.new_code_cell('1 + 1'),
        nbformat.v4.new_code_cell('slow()', metadata={'tags': ['skip-execution']}),
    ])
    path = tmp_path / 'example.ipynb'
    nbformat.write(source, path)
    executed = executable_copy(path)
    code = [c for c in executed.cells if c.cell_type == 'code']
    assert [c.source for c in code] == ['1 + 1']
    code[0].outputs = [nbformat.v4.new_output('execute_result', {'text/plain': '2'}, execution_count=1)]
    code[0].execution_count = 1
    merged = with_skipped_cells(source, executed)
    assert [c.cell_type for c in merged.cells] == ['code', 'markdown', 'code', 'code']
    assert [len(c.outputs) for c in merged.cells if c.cell_type == 'code'] == [0, 1, 0]
    assert merged.cells[0].source == '%pip install citylearn'
    assert not source.cells[2].outputs
