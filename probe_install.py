import argparse
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
INSTALL = HERE / "install.sh"
LAUNCHER = HERE / "launcher.py"
SETTINGS = HERE / (
    "config/opencode-dev.macos.json"
    if sys.platform == "darwin"
    else "config/opencode-dev.linux.json"
)
PLUGIN = "@glaicer/supercode-sandbox-awareness"
TEMPORARY_ROOT = Path(tempfile.gettempdir()) / "opencode"


def run(command, env, cwd, timeout=300):
    result = subprocess.run(
        command,
        check=False,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"command failed: {command}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def isolated_env(home, extra=None):
    env = dict(os.environ)
    for name in [
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
        "NONOCODE_REPO",
    ]:
        env.pop(name, None)
    env["HOME"] = str(home)
    env["OPENCODE_CONFIG_DIR"] = str(home / ".config/opencode")
    if extra:
        env.update(extra)
    return env


def check_layout(home):
    launcher = home / ".local/bin/nonocode"
    assert launcher.is_file() and os.access(launcher, os.X_OK), launcher
    assert launcher.read_text() == LAUNCHER.read_text()
    settings = home / ".config/nono/opencode-dev.json"
    assert settings.is_file(), settings
    expected = json.loads(SETTINGS.read_text())
    actual = json.loads(settings.read_text())
    for key in ["read", "write", "exclude"]:
        assert actual[key] == expected[key], key
    config_dir = home / ".config/opencode"
    assert not (config_dir / "plugins/sandbox-awareness").exists()
    assert any(
        PLUGIN in path.read_text()
        for path in [config_dir / "opencode.json", config_dir / "opencode.jsonc"]
        if path.is_file()
    ), "OpenCode must register the npm plugin in its global configuration"


def check_local():
    with tempfile.TemporaryDirectory(
        prefix="install-local-", dir=TEMPORARY_ROOT
    ) as directory:
        home = Path(directory) / "home"
        home.mkdir()
        run(
            ["bash", str(INSTALL), "--non-interactive"],
            env=isolated_env(home),
            cwd=HERE,
        )
        check_layout(home)
        settings = home / ".config/nono/opencode-dev.json"
        data = json.loads(settings.read_text())
        data["exclude"].append("/custom-marker")
        settings.write_text(json.dumps(data, indent=2))
        run(
            ["bash", str(INSTALL), "--non-interactive"],
            env=isolated_env(home),
            cwd=HERE,
        )
        assert json.loads(settings.read_text())["exclude"][-1] == "/custom-marker"
        print(
            "PASS: local-checkout install, layout, and existing user profile preserved"
        )


def check_download():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(HERE), **kwargs)

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(
            prefix="install-download-", dir=TEMPORARY_ROOT
        ) as directory:
            root = Path(directory)
            home = root / "home"
            neutral = root / "neutral"
            home.mkdir()
            neutral.mkdir()
            run(
                ["bash", str(INSTALL), "--non-interactive"],
                env=isolated_env(
                    home, {"NONOCODE_REPO": f"http://127.0.0.1:{server.server_port}"}
                ),
                cwd=neutral,
            )
            check_layout(home)
    finally:
        server.shutdown()
        server.server_close()
    print("PASS: download-mode install from a remote payload source")


def check_container():
    if shutil.which("podman") is None:
        print("SKIP: podman is not installed")
        return
    script = """
set -e
command -v curl >/dev/null || dnf install -y curl
useradd -m nonocode-tester
echo 'nonocode-tester ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/nonocode-tester
sudo -u nonocode-tester -H bash -c 'curl -fsSL https://opencode.ai/install | bash'
sudo -u nonocode-tester -H env NONOCODE_REPO=file:///src bash /src/install.sh --non-interactive
"""
    result = subprocess.run(
        [
            "podman",
            "run",
            "--rm",
            "--security-opt",
            "label=disable",
            "-v",
            f"{HERE}:/src:ro",
            "fedora:44",
            "bash",
            "-c",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=1200,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"container install failed:\nstdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
        )
    assert "nonocode: done" in result.stdout
    print("PASS: clean-system install inside a fedora:44 container")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--container", action="store_true", help="also run the podman clean-system test"
    )
    arguments = parser.parse_args()
    TEMPORARY_ROOT.mkdir(parents=True, exist_ok=True)
    run(["bash", "-n", str(INSTALL)], env=dict(os.environ), cwd=HERE)
    print("PASS: install.sh passes bash -n")
    check_local()
    check_download()
    if arguments.container:
        check_container()


if __name__ == "__main__":
    main()
