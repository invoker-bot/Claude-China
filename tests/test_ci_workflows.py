"""Release trigger and dependency-cache contracts; no GitHub jobs are started."""
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def workflow(name):
    # BaseLoader keeps GitHub's `on` key intact instead of parsing it as YAML 1.1 true.
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


@pytest.mark.parametrize("name", ["publish.yml", "publish-legacy.yml", "desktop-release.yml"])
def test_release_workflows_only_publish_from_version_tags(name):
    events = workflow(name)["on"]
    assert set(events) <= {"push", "workflow_dispatch"}
    assert set(events["push"]) == {"tags"}


def test_pull_requests_and_main_run_cross_platform_ci_without_publishing():
    events = workflow("ci.yml")["on"]
    assert set(events) == {"pull_request", "push", "workflow_dispatch"}
    assert events["push"]["branches"] == ["main"]
    jobs = workflow("ci.yml")["jobs"]
    assert set(jobs) == {"test"}
    commands = "\n".join(step.get("run", "") for step in jobs["test"]["steps"])
    assert "python -m pytest tests/ -q" in commands
    assert not any(word in commands for word in ("twine upload", "gh release", "build_desktop.py"))


def test_release_publishes_macos_packages_without_requiring_signing():
    release = workflow("desktop-release.yml")
    assert release["env"]["PUBLISH_MACOS"] == "true"
    assert release["env"]["SIGN_MACOS"] == "false"
    commands = "\n".join(step.get("run", "") for step in release["jobs"]["release"]["steps"])
    assert "prepare_desktop_release.py --include-macos" in commands


def test_python_39_jobs_use_a_supported_ubuntu_runner():
    for name in ("ci.yml", "publish.yml", "publish-legacy.yml", "dependency-cache.yml"):
        found = False
        for job in workflow(name)["jobs"].values():
            entries = job.get("strategy", {}).get("matrix", {}).get("include", [])
            for entry in entries:
                if entry.get("python") == "3.9":
                    found = True
                    assert entry["os"] == "ubuntu-22.04", (name, entry)
        assert found, name


@pytest.mark.parametrize("name, tag", [
    ("publish.yml", "v*"), ("desktop-release.yml", "v*"),
    ("publish-legacy.yml", "legacy-v*"),
])
def test_release_tag_routing_is_preserved(name, tag):
    assert workflow(name)["on"]["push"]["tags"] == [tag]


@pytest.mark.parametrize("name", ["publish.yml", "publish-legacy.yml", "desktop-release.yml"])
def test_release_jobs_install_and_validate_even_when_the_download_cache_hits(name):
    for job in workflow(name)["jobs"].values():
        for step in job.get("steps", []):
            if "run" in step:
                assert "cache-hit" not in step.get("if", "")
            if step.get("uses", "").startswith("actions/setup-python@") and "cache" in step.get("with", {}):
                assert step["with"]["cache"] == "pip"


def test_manual_warmup_uses_the_same_pip_cache_inputs_as_consumers():
    warm = workflow("dependency-cache.yml")
    assert set(warm["on"]) == {"workflow_dispatch"}
    for name, warm_job in [("publish.yml", "cli"), ("publish-legacy.yml", "cli"),
                           ("desktop-release.yml", "desktop")]:
        warm_setup = next(step for step in warm["jobs"][warm_job]["steps"]
                          if step.get("uses", "").startswith("actions/setup-python@"))
        for job_id, job in workflow(name)["jobs"].items():
            # The desktop upload job uses only the Python standard library.
            if name == "desktop-release.yml" and job_id == "release":
                continue
            for step in job.get("steps", []):
                if not step.get("uses", "").startswith("actions/setup-python@"):
                    continue
                assert step["with"].get("cache") == "pip"
                assert step["with"]["cache-dependency-path"] == warm_setup["with"]["cache-dependency-path"]


def test_linux_desktop_warmup_restores_the_same_download_cache():
    release_steps = workflow("desktop-release.yml")["jobs"]["build"]["steps"]
    warm_steps = workflow("dependency-cache.yml")["jobs"]["linux-desktop"]["steps"]
    release_cache = next(step for step in release_steps if step.get("uses", "").startswith("actions/cache@"))
    warm_cache = next(step for step in warm_steps if step.get("uses", "").startswith("actions/cache@"))
    assert release_cache["with"] == warm_cache["with"]
    assert "runner.arch" in release_cache["with"]["key"]
    assert "python3.10" in release_cache["with"]["key"]
    assert ".venv" not in release_cache["with"]["path"]


def test_warmup_is_confined_to_default_branch_and_does_not_build_or_publish():
    for job in workflow("dependency-cache.yml")["jobs"].values():
        assert "github.event.repository.default_branch" in job["if"]
        commands = "\n".join(step.get("run", "") for step in job["steps"])
        for command in ("-m build", "build_desktop.py", "twine upload", "gh release", "pytest"):
            assert command not in commands
