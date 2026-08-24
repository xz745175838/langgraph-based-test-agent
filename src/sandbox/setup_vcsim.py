import socket
import subprocess
import time

CONTAINER_NAME = "vcsim-sandbox"
IMAGE = "vmware/vcsim:latest"
HOST = "localhost"
HOST_PORT = 8989
CONTAINER_PORT = 8989


def is_running() -> bool:
    """Return True if the vcsim container is running."""
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"name=^{CONTAINER_NAME}$",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return CONTAINER_NAME in (result.stdout or "")


def setup() -> None:
    """Start the vcsim Docker container mapped to host port 8989."""
    if is_running():
        return
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER_NAME,
            "-p",
            f"{HOST_PORT}:{CONTAINER_PORT}",
            IMAGE,
        ],
        check=True,
    )


def teardown() -> None:
    """Stop and remove the vcsim Docker container."""
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        check=False,
    )


def wait_ready(timeout_sec: int = 60) -> bool:
    """Wait until vcsim accepts TCP connections on HOST_PORT."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, HOST_PORT), timeout=2):
                return True
        except OSError:
            time.sleep(1)
    return False
