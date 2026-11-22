"""Stage a versioned documentation deployment for the gh-pages branch (#296).

Before staging, the deploy job probes ``origin`` with ``--probe-remote`` to distinguish a verified first deployment
(``refs/heads/gh-pages`` absent on a reachable remote that serves ``master``) from a read or checkout failure, which
aborts immediately so ``keep_files: false`` never overwrites an existing site with a partial snapshot.

Each workflow run checks out ``gh-pages`` into ``--site-dir`` (when ``present``) and stages ``--build-dir``:

- ``--version ""`` (push to ``master``): replaces ``dev/`` and refreshes ``versions.json``. When ``stable/`` already
  exists, root HTML redirects are refreshed so pages present under ``dev/`` and absent from ``stable/`` redirect to
  ``dev/<page>``.
- ``--version X.Y.Z`` (release tag ``vX.Y.Z``): replaces ``X.Y.Z/`` and updates ``versions.json``. When ``X.Y.Z`` is
  the newest final (non-prerelease) version, also replaces ``stable/`` and syncs the site root ``/`` from ``stable/``:
  every file in ``stable/`` is served directly at ``/``, root HTML URLs absent from ``stable/`` receive an explicit
  relative redirect stub to ``dev/<page>`` when ``dev/<page>`` exists, and if ``dev/`` has not been deployed yet any
  pre-existing root pages absent from ``stable/`` are preserved in place until ``dev/`` is published.
"""

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

RELEASE_DIR_RE = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?$')
PROTECTED_ROOT_NAMES = frozenset({'.git', 'dev', 'stable', '.nojekyll', 'CNAME', 'versions.json'})
REDIRECT_MARKER = 'data-citylearn-root-redirect="dev"'


def is_protected_root_entry(name: str) -> bool:
    """Whether a top-level entry in site_dir belongs to version folders or site metadata."""

    return name in PROTECTED_ROOT_NAMES or bool(RELEASE_DIR_RE.match(name))


def probe_remote_branch(remote: str = 'origin', branch: str = 'gh-pages', cwd: Path | None = None) -> str:
    """Return ``'present'`` or ``'absent'`` for ``refs/heads/<branch>`` on ``remote``, or raise ``RuntimeError``."""

    proc = subprocess.run(
        ['git', 'ls-remote', '--heads', remote],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )

    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f'exit code {proc.returncode}'
        raise RuntimeError(f'Failed to query remote {remote!r} for {branch!r}: {detail}')

    heads = {line.split('\t', 1)[1].strip() for line in proc.stdout.splitlines() if '\t' in line}

    if not heads:
        raise RuntimeError(
            f'Remote {remote!r} returned no branch heads; refusing to assume first deployment for {branch!r}.'
        )

    return 'present' if f'refs/heads/{branch}' in heads else 'absent'


def render_dev_redirect(rel_posix_path: str) -> str:
    """Return an HTML redirect stub from root ``/<rel_posix_path>`` to ``/dev/<rel_posix_path>``."""

    depth = rel_posix_path.count('/')
    target = ('../' * depth) + 'dev/' + rel_posix_path
    escaped = html.escape(target, quote=True)
    target_js = json.dumps(target)

    return (
        '<!DOCTYPE html>\n'
        f'<html lang="en" {REDIRECT_MARKER}>\n'
        '<head>\n'
        '  <meta charset="utf-8">\n'
        '  <title>Redirecting to development documentation</title>\n'
        f'  <link rel="canonical" href="{escaped}">\n'
        f'  <meta http-equiv="refresh" content="0; url={escaped}">\n'
        f'  <script>location.replace({target_js} + location.search + location.hash);</script>\n'
        '</head>\n'
        '<body>\n'
        '  <p>This page is part of the development documentation: '
        f'<a href="{escaped}">{escaped}</a>.</p>\n'
        '</body>\n'
        '</html>\n'
    )


def _has_published_content(site_dir: Path) -> bool:
    if not site_dir.is_dir():
        return False

    if (site_dir / 'versions.json').is_file():
        return True

    for entry in site_dir.iterdir():
        if entry.name == '.git':
            continue

        if entry.is_file() and entry.suffix == '.html':
            return True

        if entry.is_dir() and any(entry.rglob('*.html')):
            return True

    return False


def _validate_existing_site(site_dir: Path, existing_site_state: str, require_git_dir: bool = False) -> None:
    if existing_site_state not in ('present', 'absent'):
        raise ValueError(f'Invalid existing_site_state: {existing_site_state!r}')

    if existing_site_state == 'present':
        if not site_dir.is_dir():
            raise RuntimeError(
                f'Published site directory {site_dir} does not exist while gh-pages is marked present.'
            )

        if require_git_dir and not (site_dir / '.git').exists():
            raise RuntimeError(
                f'Published site directory {site_dir} is missing .git metadata; gh-pages checkout did not succeed.'
            )

        if not _has_published_content(site_dir):
            raise RuntimeError(
                f'Published site directory {site_dir} contains no HTML pages or versions.json; '
                'refusing to overwrite an existing gh-pages site.'
            )
    elif _has_published_content(site_dir):
        raise RuntimeError(
            f'Published site directory {site_dir} already has content while gh-pages is marked absent.'
        )


def _replace_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)

    shutil.copytree(src, dst)


def _overlay_tree(src: Path, dst: Path) -> None:
    for item in src.rglob('*'):
        rel = item.relative_to(src)
        target = dst / rel

        if item.is_dir():
            if target.is_file():
                target.unlink()

            target.mkdir(parents=True, exist_ok=True)
        else:
            if target.is_dir():
                shutil.rmtree(target)

            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _prune_empty_parents(path: Path, stop_at: Path) -> None:
    parent = path.parent

    while parent != stop_at and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def _sync_root_from_stable(site_dir: Path, prev_stable_files: set[str]) -> list[str]:
    """Mirror ``stable/`` to ``site_dir`` root and write ``dev/`` redirects only for existing ``dev/`` targets."""

    stable_dir = site_dir / 'stable'
    dev_dir = site_dir / 'dev'

    if not dev_dir.is_dir():
        # No dev/ deployment exists yet: overlay stable/ onto root while preserving any pre-existing non-stable root
        # pages in place so we never emit redirects to missing /dev/<page> URLs.
        current_stable_files = {p.relative_to(stable_dir).as_posix() for p in stable_dir.rglob('*') if p.is_file()}

        for stale_rel in sorted(prev_stable_files - current_stable_files):
            stale_target = site_dir / stale_rel

            if stale_target.is_file():
                stale_target.unlink()
                _prune_empty_parents(stale_target, site_dir)

        _overlay_tree(stable_dir, site_dir)
        return []

    for entry in list(site_dir.iterdir()):
        if is_protected_root_entry(entry.name):
            continue

        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()

    for item in stable_dir.iterdir():
        target = site_dir / item.name

        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)

    stable_html = {p.relative_to(stable_dir).as_posix() for p in stable_dir.rglob('*.html')}
    dev_html = {p.relative_to(dev_dir).as_posix() for p in dev_dir.rglob('*.html')}
    written_redirects: list[str] = []

    for rel_path in sorted(dev_html - stable_html):
        if not (dev_dir / rel_path).is_file():
            continue

        dest = site_dir / rel_path

        if dest.exists():
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_dev_redirect(rel_path), encoding='utf-8')
        written_redirects.append(rel_path)

    return written_redirects


def prepare_site(
    site_dir: Path,
    build_dir: Path,
    version: str | None = None,
    custom_domain: str | None = None,
    existing_site_state: str = 'present',
    require_git_dir: bool = False,
) -> tuple[str | None, bool, list[str]]:
    """Stage ``build_dir`` into ``site_dir`` and return ``(stable, is_stable, written_redirects)``."""

    import update_versions
    from packaging.version import InvalidVersion, Version

    if not build_dir.is_dir():
        raise FileNotFoundError(f'Sphinx HTML build directory does not exist: {build_dir}')

    _validate_existing_site(site_dir, existing_site_state=existing_site_state, require_git_dir=require_git_dir)

    clean_version = (version or '').strip() or None

    if clean_version is not None:
        if not RELEASE_DIR_RE.match(clean_version):
            raise InvalidVersion(clean_version)

        Version(clean_version)

    site_dir.mkdir(parents=True, exist_ok=True)
    git_meta = site_dir / '.git'

    if git_meta.is_dir():
        shutil.rmtree(git_meta)
    elif git_meta.exists():
        git_meta.unlink()

    versions_file = site_dir / 'versions.json'
    existing = []

    if versions_file.is_file():
        existing = update_versions.release_versions(json.loads(versions_file.read_text(encoding='utf-8')))

    if clean_version is not None:
        existing.append(clean_version)

    prev_stable_dir = site_dir / 'stable'
    prev_stable_files = (
        {p.relative_to(prev_stable_dir).as_posix() for p in prev_stable_dir.rglob('*') if p.is_file()}
        if prev_stable_dir.is_dir()
        else set()
    )

    entries, stable = update_versions.build_entries(existing)
    is_stable = bool(clean_version is not None and clean_version == stable)
    versions_file.write_text(json.dumps(entries, indent=2) + '\n', encoding='utf-8')
    (site_dir / '.nojekyll').write_text('', encoding='utf-8')

    domain = (custom_domain or '').strip()
    cname_file = site_dir / 'CNAME'

    if domain:
        cname_file.write_text(domain + '\n', encoding='utf-8')
    elif cname_file.exists():
        cname_file.unlink()

    if clean_version is None:
        _replace_tree(build_dir, site_dir / 'dev')
    else:
        _replace_tree(build_dir, site_dir / clean_version)

        if is_stable:
            _replace_tree(build_dir, site_dir / 'stable')

    redirects: list[str] = []

    if (site_dir / 'stable').is_dir() and (is_stable or clean_version is None):
        redirects = _sync_root_from_stable(site_dir, prev_stable_files=prev_stable_files)

    return stable, is_stable, redirects


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--probe-remote', help='Git remote to inspect for --branch (prints "present" or "absent").')
    parser.add_argument('--branch', default='gh-pages', help='Published site branch name for --probe-remote.')
    parser.add_argument('--site-dir', type=Path, help='Checked-out gh-pages working tree.')
    parser.add_argument('--build-dir', type=Path, help='Built Sphinx HTML directory.')
    parser.add_argument(
        '--existing-site-state',
        choices=('present', 'absent'),
        default='present',
        help='Whether gh-pages already exists on the remote ("present" refuses empty/missing checkouts).',
    )
    parser.add_argument(
        '--require-git-dir',
        action='store_true',
        help='Require --site-dir/.git when --existing-site-state=present before removing .git for publication.',
    )
    parser.add_argument('--version', default='', help='Release version without leading "v", or empty for master.')
    parser.add_argument('--custom-domain', default='', help='Custom domain for CNAME, if configured.')
    args = parser.parse_args()

    if args.probe_remote:
        print(probe_remote_branch(remote=args.probe_remote, branch=args.branch))
        return 0

    if args.site_dir is None or args.build_dir is None:
        parser.error('--site-dir and --build-dir are required unless --probe-remote is used.')

    stable, is_stable, redirects = prepare_site(
        site_dir=args.site_dir,
        build_dir=args.build_dir,
        version=args.version,
        custom_domain=args.custom_domain,
        existing_site_state=args.existing_site_state,
        require_git_dir=args.require_git_dir,
    )
    print(f'stable={stable or ""}')
    print(f'is_stable={"true" if is_stable else "false"}')
    print(f'root_redirects={len(redirects)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
