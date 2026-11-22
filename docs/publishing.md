# Publishing CityLearn

CityLearn is distributed as `citylearn` and imports as `citylearn`.
The release maintainer is [Tiago Fonseca](https://github.com/calofonseca).

Portuguese version: [pt/publishing.md](pt/publishing.md).

## Prepare the release

1. Update the version in `citylearn/__init__.py`. `pyproject.toml` holds the rest of
   the package metadata; it reads the version from that file and the runtime
   dependencies from `requirements.txt`.
2. Add a user-facing entry to [releases.md](releases.md), including compatibility,
   dataset/schema impact, validation scope and migration instructions.
3. Update the affected guides and [migration notes](migration.md).
4. Run the tests and auditors in the [developer guide](developer_guide.md),
   build the Sphinx site and check its links and examples.
5. Build and validate wheel/source distributions, then verify the installed wheel
   outside the checkout. The workflow's installed-export check demonstrates this.

```console
python -m build
python -m twine check dist/*
```

Keep raw validation output in CI or release artifacts. Document measured
improvements with the baseline, inputs, repetitions, metric units and limitations.
Move older entries to the [release archive](releases_archive.md) without dropping
their validation evidence. Keep the latest release and its migration information
on the current page.

## CI, tagging, package and documentation publication

1. Commit the reviewed changes with the maintainer's identity, push once and wait for
   the relevant CI to pass.
2. Tag the approved commit as `vX.Y.Z` and push the tag (`git push origin vX.Y.Z`).
   - **PyPI publication:** A tag push by itself does not publish to PyPI. The
     [publication workflow](https://github.com/citylearn-project/CityLearn/blob/master/.github/workflows/pypi_deploy.yml)
     runs when a GitHub Release is published or when explicitly dispatched; choose one
     trigger per release. Confirm the build, installed-export check and `pypi` publish
     jobs succeeded for the intended commit, then verify the pinned package from PyPI
     in a clean environment.
   - **Documentation publication (automatic on tag push):** Pushing tag `vX.Y.Z`
     automatically triggers the
     [Sphinx workflow](https://github.com/citylearn-project/CityLearn/blob/master/.github/workflows/sphinx.yml),
     which builds the documentation at `vX.Y.Z`, deploys `/X.Y.Z/`, updates
     `/versions.json`, and when `X.Y.Z` is the newest final (non-prerelease) version,
     updates `/stable/` and the site root `/`.
   - **Rerunning a failed or missed documentation build:** Open **Actions -> Sphinx
     build -> Run workflow** on `master` and enter the exact tag in `tag` (for example
     `v3.6.0`). Re-dispatching is idempotent and overwrites `/X.Y.Z/` (and `/stable/`
     plus `/` when `X.Y.Z` is the latest final release).
   - **Post-release documentation checklist:**
     1. Confirm the `Sphinx build` (`build` and `deploy`) jobs succeeded for `vX.Y.Z`.
     2. Open `https://www.citylearn.net/X.Y.Z/` and verify the version banner and the
        left-sidebar **Other versions** section show `X.Y.Z` as `(current)`.
     3. Open `https://www.citylearn.net/versions.json` and confirm `X.Y.Z` is listed
        and selectable from both the top selector and **Other versions** in the sidebar.
     4. For a **final release** (no `a`/`b`/`rc` suffix), open both
        `https://www.citylearn.net/` and `https://www.citylearn.net/stable/` and
        confirm both serve `CityLearn X.Y.Z` (`stable (X.Y.Z)`), while
        `https://www.citylearn.net/dev/` continues to serve `master`.

The PyPI publish job supports two credential modes:

- **API credentials (current default):** the `PYPI_USERNAME` and `PYPI_PASSWORD`
  secrets, uploaded with `twine`.
- **Trusted publishing (prepared, off):** PyPI issues a short-lived token to this
  workflow through OpenID Connect, so no long-lived PyPI secret is stored in GitHub.
  To switch:
  1. On PyPI, add a trusted publisher for the `citylearn` project with the owner
     `citylearn-project`, the repository `CityLearn`, the workflow `pypi_deploy.yml`
     and the environment `pypi`.
  2. Set the repository variable `PYPI_TRUSTED_PUBLISHING` to `true`
     (Settings → Secrets and variables → Actions → Variables).
  3. After one successful release, delete the `PYPI_USERNAME` and `PYPI_PASSWORD`
     secrets.

## Documentation site

The [Sphinx workflow](https://github.com/citylearn-project/CityLearn/blob/master/.github/workflows/sphinx.yml)
publishes to GitHub Pages (the `gh-pages` branch, custom domain from the `CUSTOM_DOMAIN` secret):

| URL | Content | Built when |
|---|---|---|
| `/` | Latest final release (`stable`). The public Documentation link, the site home and existing links to shared pages open the latest stable release by default; root HTML URLs present only in `master` redirect explicitly to `/dev/<page>`. | Together with the latest final release (`v*` tag push or manual tag dispatch), with `/dev/` redirects refreshed on `master` pushes. |
| `/stable/` | Explicit alias of the latest final (non-prerelease) release. | Together with that release. |
| `/<version>/` (for example `/3.6.0/`) | Pinned documentation at tag `v<version>`. | A tag `v*` is pushed, or the workflow is run manually with `tag=v<version>`. |
| `/dev/` | Development documentation from `master` (includes `Unreleased` changes). | Every push to `master`. |
| `/versions.json` | Published versions read by the top selector and the **Other versions** sidebar section. | Every `master` or release deployment. |

Every page provides both a top version selector and an **Other versions** section in the left sidebar
(`docs/source/_static/version_switcher.js`, `docs/source/_templates/layout.html`), built from `/versions.json`.
Both show which version the reader is viewing and switch to the equivalent page in the chosen version when that
page exists (`HTTP HEAD`), or to that version's home page when the page was added or renamed in another release.

### Initial rollout tags

When this workflow first lands on `master`, wait for the automatic `master` push run to finish so `/dev/` is
published, then run **Actions -> Sphinx build -> Run workflow** from `master` deploying the **newest final release
first** and backfilling older releases one at a time:

1. Dispatch `v3.6.0` **first** and wait for both `build` and `deploy` to succeed. This publishes `/3.6.0/`,
   `/stable/` and the site root `/`, writes `/dev/<page>` redirect stubs for root HTML URLs absent from `3.6.0`,
   and records `3.6.0` as `stable` in `/versions.json`.
2. Dispatch `v3.5.0` and wait for `build` and `deploy` to succeed. This backfills `/3.5.0/` while `/` and `/stable/`
   continue serving `3.6.0`.
3. Dispatch `v3.4.0` and wait for `build` and `deploy` to succeed. This backfills `/3.4.0/` while `/` and `/stable/`
   continue serving `3.6.0`.

Deploying `v3.6.0` first ensures `versions.json` already records `3.6.0` before any historical tag runs, so older
tags never temporarily become `stable`. Earlier `v3.0.0` to `v3.3.1` tags can also be backfilled one at a time on
demand. A release build copies `layout.html` and `version_switcher.js` from `master`, so tags cut before this change
still include both the banner selector and the **Other versions** sidebar section, while skipping notebook execution
when `scripts/ci/run_notebooks.py --output-dir` is absent.

Site staging details (`scripts/ci/prepare_docs_site.py`):

- Before staging, `deploy` probes `origin` (`--probe-remote`) to distinguish a verified first deployment (`gh-pages`
  absent on a reachable remote) from a read or checkout failure, aborting immediately if an existing `gh-pages` branch
  cannot be read.
- Each deployment stages the `gh-pages` tree in one atomic commit. Every file in `stable/` is mirrored to `/` so
  shared pages serve the stable release directly; root HTML URLs absent from `stable/` receive a relative redirect
  stub to `/dev/<page>` when `/dev/<page>` exists, and if `/dev/` has not been deployed yet pre-existing root pages
  remain in place until `/dev/` is published.
- With `concurrency: documentation-deploy`, GitHub keeps one active deploy and at most one queued deploy, cancelling
  an earlier pending deploy when a third run joins the group. Dispatch any cancelled release or backfill deploy again
  so that version is published.
- In Settings -> Environments -> `github-pages`, allow deployments from `master` and from release tags `v*`.

## Version policy

| Type | Use when |
|---|---|
| Patch | Compatible fixes, documentation or small additive changes. |
| Minor | A substantial capability or schema/API change. |
| Major | Broad breaking changes. |

Release entries should explain what changes for users, required migration,
validation performed and its limits. A local documentation edit does not require
publication or imply that a new version already exists.
