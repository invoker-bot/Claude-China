"""Release trigger and dependency-cache contracts; no GitHub jobs are started."""
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def workflow(name):
    # BaseLoader keeps GitHub's `on` key intact instead of parsing it as YAML 1.1 true.
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda path: path.name)
def test_untagged_pushes_and_pr_updates_do_not_start_workflows(path):
    events = workflow(path.name)["on"]
    assert set(events) <= {"push", "workflow_dispatch"}
    if "push" in events:
        assert set(events["push"]) == {"tags"}
        assert events["push"]["tags"] in (["v*"], ["legacy-v*"])


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
