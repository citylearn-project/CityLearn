"""Versioned documentation site: versions.json generation, root/stable/dev routing and sidebar switcher (#296)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SWITCHER = ROOT / 'docs' / 'source' / '_static' / 'version_switcher.js'
sys.path.insert(0, str(ROOT / 'scripts' / 'ci'))

pytest.importorskip('packaging')
import update_versions

sys.path.remove(str(ROOT / 'scripts' / 'ci'))


def test_entries_list_stable_at_root_releases_newest_first_and_dev():
    entries, stable = update_versions.build_entries(['3.5.0', '3.6.0', '3.10.0', '3.6.0'])
    assert stable == '3.10.0'
    assert [e['path'] for e in entries] == ['', '3.10.0/', '3.6.0/', '3.5.0/', 'dev/']
    assert entries[0]['name'] == 'stable (3.10.0)'
    assert entries[-1] == {'name': 'dev (master)', 'version': 'dev', 'path': 'dev/'}


def test_prerelease_is_listed_but_never_stable():
    entries, stable = update_versions.build_entries(['3.6.0', '3.7.0rc1'])
    assert stable == '3.6.0'
    assert [e['version'] for e in entries] == ['stable', '3.7.0rc1', '3.6.0', 'dev']


def test_no_release_has_only_dev_entry():
    entries, stable = update_versions.build_entries([])
    assert stable is None and entries == [{'name': 'dev (master)', 'version': 'dev', 'path': 'dev/'}]


def test_cli_adds_to_existing_file_and_preserves_when_add_omitted(tmp_path, capsys, monkeypatch):
    existing = tmp_path / 'old.json'
    output = tmp_path / 'out' / 'versions.json'
    existing.write_text(json.dumps(update_versions.build_entries(['3.5.0'])[0]), encoding='utf-8')

    for add, is_stable in (('3.6.0', 'true'), ('3.4.0', 'false')):
        monkeypatch.setattr(sys, 'argv', ['x', '--existing', str(existing), '--add', add, '--output', str(output)])
        update_versions.main()
        printed = capsys.readouterr().out.splitlines()
        assert printed[-1] == f'is_stable={is_stable}'
        existing.write_text(output.read_text(encoding='utf-8'), encoding='utf-8')

    # Master push without --add preserves existing releases and reports is_stable=false
    monkeypatch.setattr(sys, 'argv', ['x', '--existing', str(existing), '--output', str(output)])
    update_versions.main()
    printed = capsys.readouterr().out.splitlines()
    assert printed == ['stable=3.6.0', 'is_stable=false']
    assert [e['version'] for e in json.loads(output.read_text(encoding='utf-8'))] == [
        'stable', '3.6.0', '3.5.0', '3.4.0', 'dev'
    ]


def test_invalid_version_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['x', '--add', 'main', '--output', str(tmp_path / 'v.json')])

    with pytest.raises(update_versions.InvalidVersion):
        update_versions.main()


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is not installed')
def test_switcher_routing_equivalent_page_fallback_and_sidebar():
    entries, _ = update_versions.build_entries(['3.5.0', '3.6.0'])
    script = f"""
        const s = require({json.dumps(SWITCHER.as_posix())});
        const entries = {json.dumps(entries)};
        (async () => {{
          const out = {{}};
          out.rootSite = s.siteRootOf('https://www.citylearn.net/');
          out.stableSite = s.siteRootOf('https://www.citylearn.net/stable/');
          out.releaseSite = s.siteRootOf('https://www.citylearn.net/3.6.0/');
          out.devSite = s.siteRootOf('https://www.citylearn.net/dev/');
          out.projectRootSite = s.siteRootOf('https://example.org/CityLearn/');
          out.projectReleaseSite = s.siteRootOf('https://example.org/CityLearn/3.5.0/');
          out.pageRoot = s.pageOf('/guides/features.html', '/');
          out.pageHome = s.pageOf('/index.html', '/');
          out.pageRelease = s.pageOf('/3.6.0/guides/features.html', '/3.6.0/');
          out.currentRoot = s.currentEntry(entries, 'guides/features.html').version;
          out.currentStableAlias = s.currentEntry(entries, 'stable/guides/features.html').version;
          out.currentRelease = s.currentEntry(entries, '3.6.0/guides/features.html').version;
          out.currentDev = s.currentEntry(entries, 'dev/guides/features.html').version;

          // Equivalent page exists in 3.5.0 -> stays on guides/features.html
          const existingPages = new Set([
            'https://www.citylearn.net/3.5.0/guides/features.html',
            'https://www.citylearn.net/dev/guides/KPI_V2_TREE.html',
          ]);
          const fakeFetch = async (url) => ({{ ok: existingPages.has(url) }});
          let navTarget = null;
          const e350 = entries.find(e => e.version === '3.5.0');
          await s.navigateToEntry('https://www.citylearn.net/', e350, 'guides/features.html', fakeFetch, u => {{ navTarget = u; }});
          out.sharedPageTarget = navTarget;

          // Page missing in 3.5.0 -> falls back to 3.5.0 home page
          await s.navigateToEntry('https://www.citylearn.net/', e350, 'guides/KPI_V2_TREE.html', fakeFetch, u => {{ navTarget = u; }});
          out.missingPageTarget = navTarget;

          // Sidebar DOM population & current marker
          const makeEl = (tag) => ({{
            tag, className: '', textContent: '', href: '', hidden: true, attrs: {{}}, children: [], listeners: {{}},
            ownerDocument: null,
            setAttribute(k, v) {{ this.attrs[k] = v; }},
            appendChild(c) {{ this.children.push(c); }},
            addEventListener(k, fn) {{ this.listeners[k] = fn; }},
          }});
          const doc = {{ createElement: (t) => {{ const el = makeEl(t); el.ownerDocument = doc; return el; }} }};
          const listEl = doc.createElement('ul');
          const boxEl = doc.createElement('div');
          const cur = s.currentEntry(entries, 'guides/features.html');
          s.populateSidebar(listEl, boxEl, entries, cur, 'https://www.citylearn.net/', 'guides/features.html', fakeFetch, u => {{ navTarget = u; }});
          out.sidebarHidden = boxEl.hidden;
          out.sidebarLabels = listEl.children.map(li => li.children[0].textContent);
          out.sidebarCurrentHref = listEl.children[0].children[0].attrs['aria-current'];
          console.log(JSON.stringify(out));
        }})();
    """
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {
        'rootSite': 'https://www.citylearn.net/',
        'stableSite': 'https://www.citylearn.net/',
        'releaseSite': 'https://www.citylearn.net/',
        'devSite': 'https://www.citylearn.net/',
        'projectRootSite': 'https://example.org/CityLearn/',
        'projectReleaseSite': 'https://example.org/CityLearn/',
        'pageRoot': 'guides/features.html',
        'pageHome': '',
        'pageRelease': 'guides/features.html',
        'currentRoot': 'stable',
        'currentStableAlias': 'stable',
        'currentRelease': '3.6.0',
        'currentDev': 'dev',
        'sharedPageTarget': 'https://www.citylearn.net/3.5.0/guides/features.html',
        'missingPageTarget': 'https://www.citylearn.net/3.5.0/',
        'sidebarHidden': False,
        'sidebarLabels': ['stable (3.6.0) (current)', '3.6.0', '3.5.0', 'dev (master)'],
        'sidebarCurrentHref': 'page',
    }
