import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import (
    expand,
    make_profile,
    run_in_sandbox,
    split_grants,
    validate_args,
    within,
)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary_root = Path(tempfile.gettempdir()) / "opencode"
        self.temporary_root.mkdir(parents=True, exist_ok=True)

    def test_expand_tmpdir(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            with patch.dict(os.environ, {"TMPDIR": directory}):
                self.assertEqual(
                    expand("$TMPDIR/cache"), Path(directory, "cache").resolve()
                )
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("launcher.tempfile.gettempdir", return_value=directory),
            ):
                self.assertEqual(expand("$TMPDIR"), Path(directory).resolve())

    def test_macos_profile_grants_and_exclusions(self):
        settings = json.loads(
            (Path(__file__).parent / "config/opencode-dev.macos.json").read_text()
        )
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            home = Path(directory) / "home"
            project = home / "project"
            project.mkdir(parents=True)
            temporary = Path(directory) / "tmp"
            temporary.mkdir()
            secrets = [
                home / "Library/Keychains",
                home / "Library/Application Support/Google/Chrome",
                home / "Library/Messages",
            ]
            for secret in secrets:
                secret.mkdir(parents=True)
            with (
                patch.dict(
                    os.environ,
                    {
                        "HOME": str(home),
                        "TMPDIR": str(temporary),
                        "XDG_CONFIG_HOME": str(home / ".config"),
                        "XDG_CACHE_HOME": str(home / ".cache"),
                        "XDG_DATA_HOME": str(home / ".local/share"),
                        "XDG_STATE_HOME": str(home / ".local/state"),
                    },
                ),
                patch("launcher.sys.platform", "darwin"),
            ):
                profile = make_profile(settings, project)
            self.assertIn(str(project.resolve()), profile["filesystem"]["allow"])
            self.assertIn(str(temporary.resolve()), profile["filesystem"]["allow"])
            for secret in secrets:
                for grant in (
                    profile["filesystem"]["read"] + profile["filesystem"]["allow"]
                ):
                    self.assertFalse(within(secret.resolve(), Path(grant)))
            self.assertIn("system_write_macos", profile["groups"]["exclude"])
            self.assertIn("system_read_macos", profile["groups"]["exclude"])
            self.assertNotIn("deny_keychains_macos", profile["groups"]["exclude"])
            self.assertNotIn("bypass_protection", profile["filesystem"])

    def test_launch_uses_system_temporary_directory(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            with (
                patch("launcher.tempfile.gettempdir", return_value=directory),
                patch("launcher.nono_bin", return_value="/fake/nono"),
                patch("launcher.subprocess.run") as run,
            ):
                run.return_value.returncode = 0
                result = run_in_sandbox(
                    {"read": [], "write": [], "exclude": []},
                    ["/fake/opencode"],
                    cwd=project,
                )
            self.assertEqual(result, 0)
            arguments = run.call_args.args[0]
            profile_path = Path(arguments[arguments.index("--profile") + 1])
            self.assertEqual(profile_path.parent.parent, root / "opencode")

    def test_arguments(self):
        validate_args(["--continue", "--session", "session-id", "--prompt=hello"])
        for args in [
            ["--server", "http://localhost:4096"],
            ["run"],
            ["/tmp"],
            ["--session"],
        ]:
            with self.assertRaises(ValueError):
                validate_args(args)

    def test_excluded_ancestors_and_symlinks(self):
        with tempfile.TemporaryDirectory(dir=self.temporary_root) as directory:
            root = Path(directory)
            secret = root / "secret"
            secret.mkdir()
            (root / "ordinary").mkdir()
            (root / "alias").symlink_to(secret)
            grants = split_grants(root, [secret])
            self.assertEqual(grants, [str(root / "ordinary")])

    def test_filesystem_enforcement_and_child_inheritance(self):
        platform = "macos" if sys.platform == "darwin" else "linux"
        settings = json.loads(
            (
                Path(__file__).resolve().parent
                / "config"
                / f"opencode-dev.{platform}.json"
            ).read_text()
        )
        with (
            tempfile.TemporaryDirectory(
                prefix=".nono-probe-", dir=Path.home()
            ) as directory,
            patch.dict(
                os.environ,
                {
                    "HOME": str(Path(directory) / "home"),
                    "XDG_CONFIG_HOME": str(Path(directory) / "config"),
                    "XDG_CACHE_HOME": str(Path(directory) / "cache"),
                    "XDG_DATA_HOME": str(Path(directory) / "data"),
                    "XDG_STATE_HOME": str(Path(directory) / "state"),
                    "TMPDIR": str(Path(directory) / "tmp"),
                },
            ),
        ):
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            (home / ".zshrc").write_text("export PROBE_FIXTURE=1\n")
            temporary = root / "tmp"
            temporary.mkdir()
            settings["write"].append(str(temporary))
            project = root / "project"
            project.mkdir()
            outside = root / "outside"
            outside.mkdir()
            secret = root / "excluded"
            secret.mkdir()
            (outside / "existing").write_text("original")
            (secret / "fixture").write_text("dummy secret")
            settings["exclude"].append(str(secret))
            profile = make_profile(settings, project)
            for grant in profile["filesystem"]["read"] + profile["filesystem"]["allow"]:
                self.assertFalse(within(secret, Path(grant)))
            self.assertNotIn("bypass_protection", profile["filesystem"])

            code = """
import errno, os, pathlib, pty, socket, subprocess, sys, tempfile
project, outside, secret = map(pathlib.Path, sys.argv[1:])
assert os.environ["OPENCODE_SANDBOX_MODE"] == "sandboxed"
p = project / "created"
p.write_text("first")
p.write_text("second")
p.rename(project / "renamed")
(project / "renamed").unlink()
assert (outside / "existing").read_text() == "original"
def refused(action):
    try:
        action()
    except OSError as error:
        assert error.errno in (errno.EACCES, errno.EPERM), error
    else:
        raise AssertionError("operation escaped the sandbox")
refused(lambda: (outside / "new").write_text("bad"))
refused(lambda: (outside / "existing").write_text("bad"))
refused(lambda: (outside / "existing").unlink())
refused(lambda: (outside / "existing").rename(outside / "moved"))
refused(lambda: (secret / "fixture").read_text())
for name in (".zshrc", ".bashrc", ".zprofile"):
    config = pathlib.Path(os.path.expanduser("~")) / name
    if config.is_file():
        refused(lambda: config.read_text())
        break
refused(lambda: (secret / "new").write_text("bad"))
child = subprocess.run([sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('bad')", str(outside / "new")], capture_output=True)
assert child.returncode != 0
with tempfile.TemporaryDirectory() as directory:
    p = pathlib.Path(directory) / "fixture"
    p.write_text("tmp works")
    assert p.read_text() == "tmp works"
    p.unlink()
pty.openpty()
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
print("PASS: project, tmp, read-only outside, excluded reads, denied shell configs, subprocess and TCP listener, pty")

"""
            self.assertEqual(
                run_in_sandbox(
                    settings,
                    [
                        sys.executable,
                        "-c",
                        code,
                        str(project),
                        str(outside),
                        str(secret),
                    ],
                    cwd=project,
                ),
                0,
            )
            self.assertEqual((outside / "existing").read_text(), "original")
            self.assertFalse((outside / "new").exists())

    def test_unsafe_cwd(self):
        settings = {"read": [], "write": [], "exclude": []}
        for cwd in [Path("/"), Path.home()]:
            with self.assertRaises(ValueError):
                make_profile(settings, cwd)


if __name__ == "__main__":
    unittest.main()
