"""Versioned documentation site: versions.json generation, site staging, root redirects and switcher (#296)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
SWITCHER = ROOT / 'docs' / 'source' / '_static' / 'version_switcher.js'
WORKFLOW = ROOT / '.github' / 'workflows' / 'sphinx.yml'
PREPARE_SCRIPT = ROOT / 'scripts' / 'ci' / 'prepare_docs_site.py'
sys.path.insert(0, str(ROOT / 'scripts' / 'ci'))

pytest.importorskip('packaging')
import check_docs
import prepare_docs_site
import update_versions

sys.path.remove(str(ROOT / 'scripts' / 'ci'))


def _write_build(target: Path, pages: dict[str, str], assets: dict[str, str] | None = None) -> Path:
    target.mkdir(parents=True, exist_ok=True)

    for rel_path, body in pages.items():
        dest = target / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding='utf-8')

    for rel_path, body in (assets or {}).items():
        dest = target / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding='utf-8')

    return target


def _missing_local_targets(site_root: Path) -> list[str]:
    """Check every HTML href/src in site_root resolves to an existing file."""

    resolved_root = site_root.resolve()
    missing: list[str] = []

    for html_path in sorted(resolved_root.rglob('*.html')):
        page = check_docs.Page(html_path.read_text(encoding='utf-8'))

        for link in page.links:
            parsed = urlsplit(link)

            if parsed.scheme or parsed.netloc:
                continue

            target = (
                resolved_root / unquote(parsed.path).lstrip('/')
                if parsed.path.startswith('/')
                else (html_path.parent / unquote(parsed.path) if parsed.path else html_path)
            ).resolve()

            if target.is_dir():
                target /= 'index.html'

            if not target.is_file():
                missing.append(f'{html_path.relative_to(resolved_root).as_posix()} -> {link}')

        # Also check <meta http-equiv="refresh" content="0; url=..."> targets
        raw = html_path.read_text(encoding='utf-8')

        for token in raw.split('url=')[1:]:
            refresh_url = token.split('"', 1)[0].strip()
            target = (html_path.parent / refresh_url).resolve()

            if target.is_dir():
                target /= 'index.html'

            if not target.is_file():
                missing.append(f'{html_path.relative_to(resolved_root).as_posix()} [meta-refresh] -> {refresh_url}')

    return missing


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


def test_newest_release_first_rollout_keeps_stable_during_older_backfills(tmp_path, capsys, monkeypatch):
    versions_json = tmp_path / 'versions.json'

    for add, expected_is_stable in (('3.6.0', 'true'), ('3.5.0', 'false'), ('3.4.0', 'false')):
        monkeypatch.setattr(
            sys, 'argv', ['x', '--existing', str(versions_json), '--add', add, '--output', str(versions_json)]
        )
        update_versions.main()
        printed = capsys.readouterr().out.splitlines()
        assert printed == ['stable=3.6.0', f'is_stable={expected_is_stable}']

    assert [e['version'] for e in json.loads(versions_json.read_text(encoding='utf-8'))] == [
        'stable', '3.6.0', '3.5.0', '3.4.0', 'dev'
    ]


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


def test_probe_remote_distinguishes_first_deploy_present_and_read_failure(tmp_path):
    empty_bare = tmp_path / 'empty-remote.git'
    subprocess.run(['git', 'init', '--bare', str(empty_bare)], check=True, capture_output=True)

    # Empty remote with zero branches must NOT be mistaken for a valid first deployment.
    with pytest.raises(RuntimeError, match='returned no branch heads'):
        prepare_docs_site.probe_remote_branch(str(empty_bare), 'gh-pages')

    # Unreachable / unreadable remote must fail closed.
    missing_remote = tmp_path / 'does-not-exist.git'
    proc_fail = subprocess.run(
        [sys.executable, str(PREPARE_SCRIPT), '--probe-remote', str(missing_remote), '--branch', 'gh-pages'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_fail.returncode != 0

    # Valid remote serving master without gh-pages is a verified first deployment ("absent").
    bare = tmp_path / 'origin.git'
    work = tmp_path / 'work'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    subprocess.run(['git', 'init', '-b', 'master', str(work)], check=True, capture_output=True)
    (work / 'README.md').write_text('hi\n', encoding='utf-8')
    subprocess.run(
        ['git', '-C', str(work), '-c', 'user.name=Test', '-c', 'user.email=t@example.org', '-c', 'commit.gpgsign=false',
         'add', 'README.md'],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ['git', '-C', str(work), '-c', 'user.name=Test', '-c', 'user.email=t@example.org', '-c', 'commit.gpgsign=false',
         'commit', '-m', 'init'],
        check=True,
        capture_output=True,
    )
    subprocess.run(['git', '-C', str(work), 'push', str(bare), 'master:refs/heads/master'], check=True, capture_output=True)

    proc_absent = subprocess.run(
        [sys.executable, str(PREPARE_SCRIPT), '--probe-remote', str(bare), '--branch', 'gh-pages'],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc_absent.stdout.strip() == 'absent'

    # Once gh-pages exists on the remote, --probe-remote reports "present".
    subprocess.run(['git', '-C', str(work), 'push', str(bare), 'master:refs/heads/gh-pages'], check=True, capture_output=True)
    proc_present = subprocess.run(
        [sys.executable, str(PREPARE_SCRIPT), '--probe-remote', str(bare), '--branch', 'gh-pages'],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc_present.stdout.strip() == 'present'


def test_checkout_or_read_failure_stops_publication_without_staging_partial_site(tmp_path):
    dev_build = _write_build(tmp_path / 'build-dev', pages={'index.html': '<h1>CityLearn dev</h1>'})

    # 1. Missing published directory when gh-pages is expected ("present", the default) -> fails before staging.
    missing_site = tmp_path / 'missing-published'
    proc = subprocess.run(
        [
            sys.executable, str(PREPARE_SCRIPT),
            '--site-dir', str(missing_site),
            '--build-dir', str(dev_build),
            '--custom-domain', 'www.citylearn.net',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert not missing_site.exists()

    # 2. Empty published directory (simulated failed checkout) -> fails without writing dev/, CNAME, or versions.json.
    empty_site = tmp_path / 'empty-published'
    empty_site.mkdir()
    with pytest.raises(RuntimeError, match='contains no HTML pages or versions.json'):
        prepare_docs_site.prepare_site(
            empty_site, dev_build, version='', custom_domain='www.citylearn.net', existing_site_state='present'
        )
    assert list(empty_site.iterdir()) == []

    # 3. Missing .git directory when --require-git-dir is enabled -> fails closed.
    no_git_site = _write_build(tmp_path / 'no-git-published', pages={'index.html': '<h1>Existing stable</h1>'})
    with pytest.raises(RuntimeError, match='missing .git metadata'):
        prepare_docs_site.prepare_site(
            no_git_site, dev_build, version='', existing_site_state='present', require_git_dir=True
        )
    assert not (no_git_site / 'dev').exists()

    # 4. Valid checkout with .git succeeds and strips .git prior to publication.
    valid_site = _write_build(tmp_path / 'valid-published', pages={'index.html': '<h1>Existing stable</h1>'})
    (valid_site / '.git').mkdir()
    stable, is_stable, _ = prepare_docs_site.prepare_site(
        valid_site, dev_build, version='', existing_site_state='present', require_git_dir=True
    )
    assert (stable, is_stable) == (None, False)
    assert not (valid_site / '.git').exists()
    assert (valid_site / 'index.html').read_text(encoding='utf-8') == '<h1>Existing stable</h1>'
    assert (valid_site / 'dev' / 'index.html').read_text(encoding='utf-8') == '<h1>CityLearn dev</h1>'

    # 5. Verified first deployment (existing_site_state='absent') initializes a new site, and rejects non-empty dirs.
    first_site = tmp_path / 'first-deploy'
    stable, is_stable, _ = prepare_docs_site.prepare_site(
        first_site, dev_build, version='', existing_site_state='absent', require_git_dir=True
    )
    assert (stable, is_stable) == (None, False)
    assert (first_site / 'dev' / 'index.html').is_file()

    with pytest.raises(RuntimeError, match='already has content'):
        prepare_docs_site.prepare_site(first_site, dev_build, version='', existing_site_state='absent')


def test_sphinx_workflow_fails_closed_on_gh_pages_read_error():
    workflow_text = WORKFLOW.read_text(encoding='utf-8')
    assert 'continue-on-error' not in workflow_text
    assert '--probe-remote origin --branch gh-pages' in workflow_text
    assert '--existing-site-state "$EXISTING_SITE_STATE"' in workflow_text
    assert '--require-git-dir' in workflow_text
    assert '"ray[rllib]"' in workflow_text

    uses_lines = [line.strip() for line in workflow_text.splitlines() if line.lstrip().startswith(('- uses:', 'uses:'))]
    assert len(uses_lines) == 9

    for line in uses_lines:
        spec = line.split('uses:', 1)[1].strip()
        assert prepare_docs_site.re.match(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}  # v[0-9]+$', spec), line

    deploy_section = workflow_text.split('\n  deploy:\n', 1)[1]
    assert 'actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0  # v7' in deploy_section


def test_prepare_site_stages_stable_backfills_and_explicit_dev_redirects(tmp_path):
    site = tmp_path / 'gh-pages'
    # Pre-existing unversioned master root on gh-pages before versioned rollout
    _write_build(
        site,
        pages={
            'index.html': '<h1>Old unversioned dev home</h1>',
            'installation.html': '<h1>Old dev installation</h1>',
            'glossary.html': '<h1>Old dev glossary</h1>',
            'guides/dataset_catalogue.html': '<h1>Old dev dataset catalogue</h1>',
            'guides/retired_datasets.html': '<h1>Retired page absent from dev and stable</h1>',
        },
        assets={'_images/stale.png': 'old-bytes'},
    )

    dev_build = _write_build(
        tmp_path / 'build-dev',
        pages={
            'index.html': '<h1>CityLearn dev</h1>',
            'installation.html': '<h1>Install dev</h1>',
            'glossary.html': '<h1>Glossary dev</h1>',
            'guides/dataset_catalogue.html': '<h1>Dataset catalogue dev</h1>',
        },
    )
    v360_build = _write_build(
        tmp_path / 'build-360',
        pages={
            'index.html': '<h1>CityLearn 3.6.0</h1>',
            'installation.html': '<h1>Install 3.6.0</h1>',
        },
        assets={'_static/version_switcher.js': '// switcher'},
    )
    v350_build = _write_build(
        tmp_path / 'build-350',
        pages={
            'index.html': '<h1>CityLearn 3.5.0</h1>',
            'installation.html': '<h1>Install 3.5.0</h1>',
        },
    )
    v340_build = _write_build(
        tmp_path / 'build-340',
        pages={'index.html': '<h1>CityLearn 3.4.0</h1>'},
    )

    # 1. Master push before stable exists: populates /dev/ and leaves pre-existing root intact.
    stable, is_stable, redirects = prepare_docs_site.prepare_site(
        site, dev_build, version='', custom_domain='www.citylearn.net'
    )
    assert (stable, is_stable, redirects) == (None, False, [])
    assert (site / 'dev' / 'guides' / 'dataset_catalogue.html').read_text(encoding='utf-8') == (
        '<h1>Dataset catalogue dev</h1>'
    )
    assert (site / 'CNAME').read_text(encoding='utf-8') == 'www.citylearn.net\n'
    assert (site / '.nojekyll').is_file()

    # 2. Deploy newest final release v3.6.0 first: updates /3.6.0/, /stable/, and / with /dev/ redirects.
    stable, is_stable, redirects = prepare_docs_site.prepare_site(
        site, v360_build, version='3.6.0', custom_domain='www.citylearn.net'
    )
    assert (stable, is_stable) == ('3.6.0', True)
    assert redirects == ['glossary.html', 'guides/dataset_catalogue.html']
    assert (site / 'index.html').read_text(encoding='utf-8') == '<h1>CityLearn 3.6.0</h1>'
    assert (site / 'installation.html').read_text(encoding='utf-8') == '<h1>Install 3.6.0</h1>'
    assert (site / 'stable' / 'installation.html').read_text(encoding='utf-8') == '<h1>Install 3.6.0</h1>'
    assert (site / '3.6.0' / 'installation.html').read_text(encoding='utf-8') == '<h1>Install 3.6.0</h1>'
    assert _missing_local_targets(site) == []

    cat_redirect = (site / 'guides' / 'dataset_catalogue.html').read_text(encoding='utf-8')
    assert prepare_docs_site.REDIRECT_MARKER in cat_redirect
    assert 'url=../dev/guides/dataset_catalogue.html' in cat_redirect
    assert 'location.replace("../dev/guides/dataset_catalogue.html" + location.search + location.hash)' in cat_redirect

    glossary_redirect = (site / 'glossary.html').read_text(encoding='utf-8')
    assert 'url=dev/glossary.html' in glossary_redirect
    assert not (site / 'guides' / 'retired_datasets.html').exists()
    assert not (site / '_images' / 'stale.png').exists()

    # 3. Backfill v3.5.0 and v3.4.0: root and /stable/ stay on 3.6.0, redirects stay intact.
    for older_ver, older_build in (('3.5.0', v350_build), ('3.4.0', v340_build)):
        stable, is_stable, redirects = prepare_docs_site.prepare_site(
            site, older_build, version=older_ver, custom_domain='www.citylearn.net'
        )
        assert (stable, is_stable, redirects) == ('3.6.0', False, [])
        assert (site / 'index.html').read_text(encoding='utf-8') == '<h1>CityLearn 3.6.0</h1>'
        assert (site / 'stable' / 'index.html').read_text(encoding='utf-8') == '<h1>CityLearn 3.6.0</h1>'
        assert prepare_docs_site.REDIRECT_MARKER in (
            site / 'guides' / 'dataset_catalogue.html'
        ).read_text(encoding='utf-8')

    assert (site / '3.5.0' / 'index.html').read_text(encoding='utf-8') == '<h1>CityLearn 3.5.0</h1>'
    assert (site / '3.4.0' / 'index.html').read_text(encoding='utf-8') == '<h1>CityLearn 3.4.0</h1>'
    assert _missing_local_targets(site) == []

    # 4. Subsequent v3.7.0 release containing guides/dataset_catalogue.html replaces redirect stub with stable content.
    v370_build = _write_build(
        tmp_path / 'build-370',
        pages={
            'index.html': '<h1>CityLearn 3.7.0</h1>',
            'installation.html': '<h1>Install 3.7.0</h1>',
            'guides/dataset_catalogue.html': '<h1>Dataset catalogue 3.7.0</h1>',
        },
    )
    stable, is_stable, redirects = prepare_docs_site.prepare_site(site, v370_build, version='3.7.0')
    assert (stable, is_stable, redirects) == ('3.7.0', True, ['glossary.html'])
    assert (site / 'guides' / 'dataset_catalogue.html').read_text(encoding='utf-8') == (
        '<h1>Dataset catalogue 3.7.0</h1>'
    )
    assert not (site / 'CNAME').exists()
    assert _missing_local_targets(site) == []


def test_stable_tag_before_first_dev_deploy_preserves_legacy_root_until_dev_exists(tmp_path):
    site = tmp_path / 'gh-pages-direct'
    legacy_catalogue_html = (
        '<html><body><h1>Pre-existing master catalogue</h1>'
        '<a href="../installation.html">Install</a><img src="../_images/cat.svg"></body></html>'
    )
    _write_build(
        site,
        pages={
            'index.html': '<h1>Pre-existing master index</h1>',
            'installation.html': '<h1>Pre-existing master install</h1>',
            'guides/dataset_catalogue.html': legacy_catalogue_html,
        },
        assets={'_images/cat.svg': '<svg></svg>'},
    )
    v360_build = _write_build(
        tmp_path / 'v360',
        pages={
            'index.html': '<h1>CityLearn 3.6.0</h1>',
            'installation.html': '<h1>Install 3.6.0</h1>',
        },
    )
    dev_build = _write_build(
        tmp_path / 'dev',
        pages={
            'index.html': '<h1>CityLearn dev</h1>',
            'installation.html': '<h1>Install dev</h1>',
            'guides/dataset_catalogue.html': '<h1>Dataset catalogue dev</h1>',
        },
    )

    # 1. Stable tag arrives before any dev/ build: shared pages serve 3.6.0, legacy root page stays preserved in place
    #    with zero redirects to non-existent /dev/ targets.
    stable, is_stable, redirects = prepare_docs_site.prepare_site(site, v360_build, version='3.6.0')
    assert (stable, is_stable, redirects) == ('3.6.0', True, [])
    assert (site / 'index.html').read_text(encoding='utf-8') == '<h1>CityLearn 3.6.0</h1>'
    assert (site / 'installation.html').read_text(encoding='utf-8') == '<h1>Install 3.6.0</h1>'
    assert (site / 'guides' / 'dataset_catalogue.html').read_text(encoding='utf-8') == legacy_catalogue_html
    assert _missing_local_targets(site) == []

    # 2. Once dev/ is deployed, the preserved legacy root page transitions to a verified redirect to ../dev/...
    stable, is_stable, redirects = prepare_docs_site.prepare_site(site, dev_build, version='')
    assert (stable, is_stable, redirects) == ('3.6.0', False, ['guides/dataset_catalogue.html'])
    assert (site / 'installation.html').read_text(encoding='utf-8') == '<h1>Install 3.6.0</h1>'
    assert 'url=../dev/guides/dataset_catalogue.html' in (
        site / 'guides' / 'dataset_catalogue.html'
    ).read_text(encoding='utf-8')
    assert _missing_local_targets(site) == []


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is not installed')
def test_switcher_routing_equivalent_page_fallback_root_redirects_and_sidebar():
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

          // Root /guides/dataset_catalogue.html has a 200 OK redirect stub, while /stable/ does NOT have it.
          const existingPages = new Set([
            'https://www.citylearn.net/guides/features.html',
            'https://www.citylearn.net/stable/guides/features.html',
            'https://www.citylearn.net/3.5.0/guides/features.html',
            'https://www.citylearn.net/guides/dataset_catalogue.html', // root redirect stub!
            'https://www.citylearn.net/dev/guides/dataset_catalogue.html',
            'https://www.citylearn.net/dev/guides/KPI_V2_TREE.html',
          ]);
          const fakeFetch = async (url) => ({{ ok: existingPages.has(url) }});
          let navTarget = null;
          const eStable = entries.find(e => e.version === 'stable');
          const e350 = entries.find(e => e.version === '3.5.0');

          // Shared page exists in 3.5.0 and stable -> stays on guides/features.html
          await s.navigateToEntry('https://www.citylearn.net/', e350, 'guides/features.html', fakeFetch, u => {{ navTarget = u; }});
          out.sharedPageTarget = navTarget;
          await s.navigateToEntry('https://www.citylearn.net/', eStable, 'guides/features.html', fakeFetch, u => {{ navTarget = u; }});
          out.sharedStableTarget = navTarget;

          // Dev-only page switched to stable probes /stable/guides/dataset_catalogue.html (404) -> goes to / home!
          await s.navigateToEntry('https://www.citylearn.net/', eStable, 'guides/dataset_catalogue.html', fakeFetch, u => {{ navTarget = u; }});
          out.devOnlyToStableTarget = navTarget;

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
        'sharedStableTarget': 'https://www.citylearn.net/guides/features.html',
        'devOnlyToStableTarget': 'https://www.citylearn.net/',
        'missingPageTarget': 'https://www.citylearn.net/3.5.0/',
        'sidebarHidden': False,
        'sidebarLabels': ['stable (3.6.0) (current)', '3.6.0', '3.5.0', 'dev (master)'],
        'sidebarCurrentHref': 'page',
    }
