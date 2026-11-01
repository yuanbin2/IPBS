"""Check Compose's static port and required-variable boundary without an engine."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "docker-compose.yml"
DEBUG = ROOT / "docker-compose.debug.yml"
SAMPLE = {
    "COMPOSE_PROJECT_NAME": "blog_i010_isolated",
    "POSTGRES_DB": "isolated_i010",
    "POSTGRES_USER": "isolated_user",
    "POSTGRES_PASSWORD": "isolated-only-private-value",
    "RABBITMQ_USER": "isolated_user",
    "RABBITMQ_PASSWORD": "isolated-only-private-value",
    "RABBITMQ_VHOST": "isolated_i010",
    "DJANGO_SECRET_KEY": "isolated-compose-test-key-not-for-deployment-0123456789",
    "DJANGO_ALLOWED_HOSTS": "blog.example.test",
    "DJANGO_HTTPS_TERMINATED": "true",
    "BLOG_LOCAL_MODE": "false",
    "BLOG_RELEASE_ID": "i019-isolated",
}


def render(env_file: Path, docker_config: Path, *, debug: bool = False) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for key in SAMPLE:
        environment.pop(key, None)
    environment["COMPOSE_ENV_FILE"] = str(env_file)
    environment["DOCKER_CONFIG"] = str(docker_config)
    command = ["docker", "compose", "--env-file", str(env_file), "-f", str(BASE)]
    if debug:
        command += ["-f", str(DEBUG)]
    command += ["config", "--format", "json"]
    return subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, check=False)


def published_ports(config: dict, service: str) -> list[dict]:
    return config["services"][service].get("ports", [])


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise RuntimeError("Compose boundary failed: " + detail)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="blog-i010-compose-") as directory:
        temporary = Path(directory)
        env_file = temporary / "synthetic.env"
        env_file.write_text("\n".join(f"{key}={value}" for key, value in SAMPLE.items()) + "\n", encoding="utf-8")
        result = render(env_file, temporary)
        if result.returncode:
            print("Compose static rendering failed; no containers were started.", file=sys.stderr)
            return 1
        config = json.loads(result.stdout)
        internal = ("backend", "celery_worker", "celery_beat", "postgres", "redis", "rabbitmq")
        require(all(not published_ports(config, name) for name in internal), "internal service has a host port")
        frontend_ports = published_ports(config, "frontend")
        require(len(frontend_ports) == 1 and frontend_ports[0]["host_ip"] == "127.0.0.1", "frontend bind")
        require(config["services"]["backend"]["environment"]["BLOG_LOCAL_MODE"] == "false", "backend mode")
        require(
            config["services"]["backend"]["environment"]["RUN_MIGRATIONS"] == "false", "automatic migration enabled"
        )
        require(
            config["services"]["backend"]["environment"]["COLLECT_STATIC"] == "false", "automatic collectstatic enabled"
        )
        require(config["services"]["backend"]["image"] == "knowledge-agent-backend:i019-isolated", "backend image tag")
        require(
            config["services"]["frontend"]["image"] == "knowledge-agent-frontend:i019-isolated", "frontend image tag"
        )
        require("/api/ready/" in config["services"]["backend"]["healthcheck"]["test"][-1], "readiness health check")

        debug_result = render(env_file, temporary, debug=True)
        if debug_result.returncode:
            print("Compose debug override rendering failed.", file=sys.stderr)
            return 1
        debug_config = json.loads(debug_result.stdout)
        for name in ("postgres", "redis", "rabbitmq"):
            require(bool(published_ports(debug_config, name)), f"{name} debug port missing")
            require(
                all(port["host_ip"] == "127.0.0.1" for port in published_ports(debug_config, name)),
                f"{name} debug port is not loopback",
            )

        missing_file = temporary / "missing-password.env"
        missing_file.write_text(
            "\n".join(f"{key}={value}" for key, value in SAMPLE.items() if key != "POSTGRES_PASSWORD") + "\n",
            encoding="utf-8",
        )
        missing = render(missing_file, temporary)
        require(missing.returncode != 0 and "POSTGRES_PASSWORD" in missing.stderr, "missing password accepted")
        print(
            "Compose static boundaries passed: internal ports absent; debug ports loopback; missing password rejected."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
