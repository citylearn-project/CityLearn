"""Execute the example notebooks published in the documentation.

Install cells (``%pip``/``!pip``) are skipped, because CI installs the checkout with its dependencies,
and so are cells tagged ``skip-execution`` (for example, dataset generation that needs EnergyPlus).
Each notebook runs in its own temporary working directory, so the files it writes do not touch the
checkout. The notebooks keep their episodes short, so this check stays fast.

With ``--output-dir``, the executed notebooks are also written there, with the skipped cells kept
(without outputs), so the documentation build can render them with their outputs. The notebooks in the
repository stay free of outputs.

Usage: python scripts/ci/run_notebooks.py [--output-dir DIR] [notebook ...]
"""

import argparse
from pathlib import Path
import sys
import tempfile
import time

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOKS = [
    'examples/load_environment.ipynb',
    'examples/controller_examples.ipynb',
    'examples/cli.ipynb',
    'examples/rl_training.ipynb',
    'examples/rllib_training.ipynb',
]
SKIP_TAG = 'skip-execution'
INSTALL_PREFIXES = ('%pip', '!pip', '%conda', '!conda')


def executable_copy(path: Path) -> nbformat.NotebookNode:
    notebook = nbformat.read(path, as_version=4)
    notebook.cells = [
        cell for cell in notebook.cells
        if cell.cell_type != 'code' or not (
            cell.source.lstrip().startswith(INSTALL_PREFIXES) or SKIP_TAG in cell.metadata.get('tags', [])
        )
    ]

    return notebook


def with_skipped_cells(source: nbformat.NotebookNode, executed: nbformat.NotebookNode) -> nbformat.NotebookNode:
    """Return ``source`` with the outputs of the executed code cells, in order; skipped cells stay unexecuted."""

    results = iter([cell for cell in executed.cells if cell.cell_type == 'code'])
    notebook = nbformat.from_dict(source)

    for cell in notebook.cells:
        if cell.cell_type == 'code' and not (
            cell.source.lstrip().startswith(INSTALL_PREFIXES) or SKIP_TAG in cell.metadata.get('tags', [])
        ):
            result = next(results)
            cell.outputs, cell.execution_count = result.outputs, result.execution_count

    notebook.metadata = executed.metadata

    return notebook


def run(path: Path, timeout: int, output_dir: Path | None = None) -> float:
    start = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix='citylearn-notebook-', ignore_cleanup_errors=True) as directory:
        executed = executable_copy(path)
        client = NotebookClient(
            executed, timeout=timeout, kernel_name='python3', resources={'metadata': {'path': directory}},
        )
        client.execute()  # fills the outputs of `executed` in place

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        nbformat.write(with_skipped_cells(nbformat.read(path, as_version=4), executed), output_dir / path.name)

    return time.perf_counter() - start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('notebooks', nargs='*', default=NOTEBOOKS, help='Notebook paths relative to the repository root.')
    parser.add_argument('--timeout', type=int, default=900, help='Time limit of one cell, in seconds.')
    parser.add_argument('--output-dir', type=Path, help='Also write the executed notebooks, with outputs, to this directory.')
    args = parser.parse_args()
    failures = []

    for name in args.notebooks:
        path = ROOT / name

        try:
            seconds = run(path, args.timeout, args.output_dir)

        except Exception as error:  # noqa: BLE001 - report every failing notebook, then fail
            failures.append(name)
            print(f'FAILED {name}: {type(error).__name__}: {error}', flush=True)

        else:
            print(f'ok {name} ({seconds:.0f} s)', flush=True)

    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
