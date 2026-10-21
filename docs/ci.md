# CI triggers and dependency caches

Ordinary branch pushes and pull request updates do not start GitHub Actions.
Run tests locally before pushing. Automatic publication runs only on release tags:

- `v*`: cross-platform CLI tests and PyPI publishing, plus native desktop
  installation, update and removal checks followed by GitHub Release publishing.
- `legacy-v*`: compatibility-package tests and publishing.
- `workflow_dispatch`: explicitly requested validation or cache warming.

The existing release workflows remain manually runnable. Manual runs do not
publish a Release or upload to PyPI. The desktop and main-package workflows
upload build artifacts for inspection.

## What is cached

CLI workflows and Windows/macOS desktop builds use `actions/setup-python`'s
`cache: pip`. The action separates caches by OS, architecture and Python version.
Dependency manifests and the corresponding workflow files contribute to the key,
so changes to dependencies installed inline also invalidate the exact match.

The Linux desktop build keeps Ubuntu 22.04's system Python 3.10 for GTK bindings.
It uses `actions/cache` with the path from `python -m pip cache dir`, a key that
includes the OS, architecture, distribution and Python minor version, and a
restore prefix restricted to that same environment.

Only pip's download/wheel cache is persisted. Virtual environments, installed
packages, source build directories, installers, credentials and signing material
are not cached. Every release still installs dependencies into its current
environment and performs all tests, builds and installation checks. A cache miss
uses the normal download path. Cache hits do not freeze dependency versions.

## Optional manual warmup

GitHub caches are scoped by ref. A release tag can restore the default branch's
cache, but cannot restore a cache created under another tag. This is why the
manual **Warm dependency caches** workflow runs only on the default branch
(`main`) and shares its keys with the release workflows.

Use Actions → Warm dependency caches → Run workflow → Branch: `main`, then choose
`desktop`, `cli` (including compatibility-package dependencies), or `all`.
The equivalent CLI command, when warming is explicitly wanted, is:

```sh
gh workflow run dependency-cache.yml --ref main -f scope=desktop
```

It installs dependencies without native builds, tests, signing or publishing.
An exact cache hit skips the dependency-install step in this warmup only.
There is no automatic warmup on pushes, PRs or a schedule. It is optional and
still consumes runner time, so it is useful before a release when dependencies
have changed or caches have expired; it need not run for every source edit.

The package version is part of `pyproject.toml`, so a version bump changes the
exact key. Restore prefixes allow reuse of the same environment's existing pip
downloads, followed by normal resolution and installation of missing packages.
GitHub can evict inactive caches, and unrestricted dependency versions can still
require new downloads. Compare total job time (including cache restore/save),
not just the installation step, before claiming a speed improvement.

## Local verification

```sh
python -m pytest tests/test_ci_workflows.py -q
python -m pytest tests/ -q
actionlint
```

The regression checks cover the tag-only automatic trigger policy, unchanged
release tag routing, cache/warmup compatibility and preservation of validation
steps on a cache hit. Use actionlint to validate workflow syntax and expressions.
Pushing a change to these files without a tag does not run remote validation.

References: [setup-python caching](https://github.com/actions/setup-python/blob/v6/README.md#caching-packages-dependencies),
[GitHub cache scope and retention](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching).
