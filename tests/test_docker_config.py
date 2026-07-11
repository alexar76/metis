"""Validate Docker Compose configuration files."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_compose(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _merged_services() -> dict:
    base = _load_compose(ROOT / "docker-compose.yml")
    prod = _load_compose(ROOT / "docker-compose.prod.yml")
    services = dict(base.get("services", {}))
    for name, override in prod.get("services", {}).items():
        if name in services:
            services[name] = {**services[name], **override}
        else:
            services[name] = override
    return services


@pytest.mark.parametrize(
    "compose_file",
    ["docker-compose.yml", "docker-compose.prod.yml"],
)
def test_compose_files_parse(compose_file: str) -> None:
    data = _load_compose(ROOT / compose_file)
    assert "services" in data
    assert isinstance(data["services"], dict)


def test_required_services_defined() -> None:
    services = _merged_services()
    required = {"coordinator", "node-a", "node-b"}
    assert required.issubset(services.keys())


def test_optional_profiles() -> None:
    services = _load_compose(ROOT / "docker-compose.yml")["services"]
    assert "profiles" in services["ollama"]
    assert "local-models" in services["ollama"]["profiles"]
    assert "profiles" in services["redis"]


def test_network_isolation() -> None:
    data = _load_compose(ROOT / "docker-compose.yml")
    assert "metis-net" in data["networks"]


def test_security_hardening_on_app_services() -> None:
    services = _load_compose(ROOT / "docker-compose.yml")["services"]
    for name in ("coordinator", "node-a", "node-b"):
        svc = services[name]
        assert svc.get("read_only") is True
        assert svc.get("cap_drop") == ["ALL"]
        assert "no-new-privileges:true" in svc.get("security_opt", [])


def test_docker_config_files_exist() -> None:
    config_dir = ROOT / "config"
    expected = [
        "docker-cluster.yaml",
        "docker-runtime.yaml",
        "docker-node-a.yaml",
        "docker-node-b.yaml",
        "docker.env.example",
    ]
    for name in expected:
        assert (config_dir / name).is_file(), f"missing {name}"


def test_dockerfile_exists() -> None:
    assert (ROOT / "Dockerfile").is_file()
    assert (ROOT / ".dockerignore").is_file()


def test_entrypoint_scripts_exist_and_executable() -> None:
    for name in ("docker-entrypoint-coordinator.sh", "docker-entrypoint-node.sh"):
        path = ROOT / "scripts" / name
        assert path.is_file()
        assert path.stat().st_mode & 0o111


def test_docker_cluster_uses_service_names() -> None:
    cluster = _load_compose(ROOT / "config" / "docker-cluster.yaml")
    urls = [n["url"] for n in cluster["nodes"]]
    assert "http://node-a:8443" in urls
    assert "http://node-b:8444" in urls


def test_prod_compose_resource_limits() -> None:
    prod = _load_compose(ROOT / "docker-compose.prod.yml")["services"]
    for name in ("coordinator", "node-a", "node-b"):
        assert "deploy" in prod[name]
        assert "resources" in prod[name]["deploy"]
        assert prod[name].get("restart") == "always"
        assert prod[name].get("logging", {}).get("driver") == "json-file"
