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

## CI, tagging and publication

Commit the reviewed changes with the maintainer's identity, push once and wait for
the relevant CI to pass. Tag the approved commit as `vX.Y.Z`.

The [publication workflow](https://github.com/citylearn-project/CityLearn/blob/master/.github/workflows/pypi_deploy.yml) runs when a GitHub
Release is published or when explicitly dispatched. Choose one trigger per release.
A tag push by itself does not publish the package.

The build job checks the distributions and installed exports. The publish job
uses the existing `citylearn` PyPI project and the GitHub `pypi` environment's
configured credentials. Confirm both jobs succeeded for the intended commit and
verify the pinned package from PyPI in a clean environment.

The publish job supports two credential modes:

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

## Version policy

| Type | Use when |
|---|---|
| Patch | Compatible fixes, documentation or small additive changes. |
| Minor | A substantial capability or schema/API change. |
| Major | Broad breaking changes. |

Release entries should explain what changes for users, required migration,
validation performed and its limits. A local documentation edit does not require
publication or imply that a new version already exists.
