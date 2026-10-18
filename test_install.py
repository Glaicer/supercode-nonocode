import json
import os
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
INSTALL = HERE / "install.sh"
BEGIN = "# >>> nonocode shell integration >>>"
PLUGIN = "@glaicer/supercode-sandbox-awareness"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(tempfile.gettempdir()) / "opencode"
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(
            prefix="nonocode-install-test-", dir=temporary_root
        )
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.home / ".local/bin"
        self.bin.mkdir(parents=True)
        self.set_platform("Linux", "x86_64")
        self.opencode = self.home / ".opencode/bin/opencode"
        self.opencode.parent.mkdir(parents=True)
        self.record_command(self.opencode, "opencode")
        nono = self.bin / "nono"
        nono.write_text(
            '#!/bin/sh\nwhile [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n'
        )
        nono.chmod(0o755)
        self.env = dict(os.environ)
        for name in list(self.env):
            if name.startswith(("XDG_", "NONO_", "NONOCODE_")) or name == "ZDOTDIR":
                self.env.pop(name)
        self.env.update(
            HOME=str(self.home),
            OPENCODE_CONFIG_DIR=str(self.home / ".config/opencode"),
            TMPDIR=str(self.root / "tmp"),
            SHELL="/bin/bash",
            PATH=f"{self.bin}:{self.env['PATH']}",
        )
        (self.root / "tmp").mkdir()
        self.settings = self.home / ".config/nono/opencode-dev.json"
        self.plugin = self.home / ".config/opencode/plugins/sandbox-awareness"

    def record_command(self, path, name):
        path.write_text(
            f"#!{sys.executable}\nimport json, sys\n"
            f"print(json.dumps([{name!r}, *sys.argv[1:]]))\n"
        )
        path.chmod(0o755)

    def set_platform(self, system, machine):
        path = self.bin / "uname"
        path.write_text(
            f'#!/bin/sh\ncase "$1" in\n-s) echo {system};;\n-m) echo {machine};;\nesac\n'
        )
        path.chmod(0o755)

    def install(self, answers=None, piped=False, expected_returncode=0, cwd=None):
        if answers is None:
            result = subprocess.run(
                ["bash", str(INSTALL), "--non-interactive"],
                check=False,
                cwd=cwd or HERE,
                env=self.env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(
                result.returncode,
                expected_returncode,
                result.stdout + result.stderr,
            )
            return result.stdout + result.stderr

        master, slave = pty.openpty()

        command = ["bash"] if piped else ["bash", str(INSTALL)]
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import fcntl, os, sys, termios; "
                    "fcntl.ioctl(1, termios.TIOCSCTTY, 0); "
                    "os.execvp(sys.argv[1], sys.argv[1:])"
                ),
                *command,
            ],
            cwd=cwd or HERE,
            env=self.env,
            stdin=subprocess.PIPE if piped else slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
        )
        os.close(slave)
        output = bytearray()
        try:
            os.write(master, answers.encode())
            if piped:
                child.stdin.write(INSTALL.read_bytes())
                child.stdin.close()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                elif child.poll() is not None:
                    break
            self.assertEqual(
                child.wait(timeout=1), expected_returncode, output.decode()
            )
            return output.decode()
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            os.close(master)

    def test_noninteractive_defaults(self):
        output = self.install()
        self.assertIn(
            "non-interactive defaults: known_hosts=yes, shell integration=yes, Sandbox Awareness=yes",
            output,
        )
        self.assertIn("git pull and git push over SSH", output)
        self.assertIn("opencode --no-sandbox", output)
        self.assertIn("Sandbox Awareness plugin", output)
        self.assertEqual(
            json.loads(self.settings.read_text())["read_exceptions"],
            ["$HOME/.ssh/known_hosts"],
        )
        self.assertIn(BEGIN, (self.home / ".bashrc").read_text())
        self.assertFalse((self.home / ".zshrc").exists())
        self.assertIn(json.dumps(["opencode", "plugin", "add", PLUGIN]), output)
        self.assertFalse(self.plugin.exists())

    def test_linux_profile_selected(self):
        self.install()
        expected = json.loads((HERE / "config/opencode-dev.linux.json").read_text())
        actual = json.loads(self.settings.read_text())
        for key in ["read", "write", "exclude"]:
            self.assertEqual(actual[key], expected[key])

    def test_wsl_uses_linux_profile(self):
        self.env["WSL_DISTRO_NAME"] = "Ubuntu"
        self.install()
        expected = json.loads((HERE / "config/opencode-dev.linux.json").read_text())
        self.assertEqual(
            json.loads(self.settings.read_text())["write"], expected["write"]
        )

    def test_macos_profile_selected(self):
        self.set_platform("Darwin", "arm64")
        output = self.install()
        expected = json.loads((HERE / "config/opencode-dev.macos.json").read_text())
        actual = json.loads(self.settings.read_text())
        for key in ["read", "write", "exclude"]:
            self.assertEqual(actual[key], expected[key])
        self.assertIn("macOS support is experimental", output)

    def test_macos_download_profile(self):
        self.set_platform("Darwin", "x86_64")
        self.env["NONOCODE_REPO"] = HERE.as_uri()
        output = self.install(cwd=self.root)
        expected = json.loads((HERE / "config/opencode-dev.macos.json").read_text())
        self.assertEqual(
            json.loads(self.settings.read_text())["exclude"], expected["exclude"]
        )
        self.assertNotIn("installing from local checkout", output)

    def test_linux_download_profile(self):
        self.env["NONOCODE_REPO"] = HERE.as_uri()
        output = self.install(cwd=self.root)
        expected = json.loads((HERE / "config/opencode-dev.linux.json").read_text())
        self.assertEqual(
            json.loads(self.settings.read_text())["exclude"], expected["exclude"]
        )
        self.assertNotIn("installing from local checkout", output)

    def test_macos_preserves_existing_profile(self):
        self.set_platform("Darwin", "arm64")
        self.settings.parent.mkdir(parents=True)
        existing = json.loads((HERE / "config/opencode-dev.linux.json").read_text())
        existing["read_exceptions"] = ["$HOME/.ssh/known_hosts"]
        existing["exclude"].append("/custom-marker")
        self.settings.write_text(json.dumps(existing))
        before = self.settings.read_bytes()
        self.install()
        self.assertEqual(self.settings.read_bytes(), before)

    def test_xdg_config_home(self):
        self.env["XDG_CONFIG_HOME"] = str(self.root / "config")
        self.settings = self.root / "config/nono/opencode-dev.json"
        self.install()
        self.assertIn(
            "$HOME/.ssh/known_hosts",
            json.loads(self.settings.read_text())["read_exceptions"],
        )
        self.assertFalse((self.home / ".config/nono/opencode-dev.json").exists())

    def test_unsupported_platform(self):
        self.set_platform("FreeBSD", "x86_64")
        output = self.install(expected_returncode=1)
        self.assertIn("native Windows is not supported", output)
        self.assertFalse((self.bin / "nonocode").exists())

    def test_noninteractive_zsh_default(self):
        self.env["SHELL"] = "/bin/zsh"
        self.env["ZDOTDIR"] = str(self.home / "zsh")
        self.install()
        self.assertIn(BEGIN, (self.home / "zsh/.zshrc").read_text())
        self.assertFalse((self.home / ".bashrc").exists())

    def test_opencode_on_path(self):
        self.opencode.rename(self.bin / "opencode")
        output = self.install()
        self.assertIn(json.dumps(["opencode", "plugin", "add", PLUGIN]), output)
        result = subprocess.run(
            ["bash", "-c", 'source "$HOME/.bashrc"\nopencode --no-sandbox --version'],
            check=False,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["opencode", "--version"])

    def test_missing_opencode_aborts_before_prompts_or_installation(self):
        self.opencode.unlink()
        for command in ["bash", "id"]:
            (self.bin / command).symlink_to(shutil.which(command))
        self.env["PATH"] = str(self.bin)
        output = self.install(expected_returncode=1)
        self.assertIn("OpenCode was not found. Install OpenCode V2 first", output)
        self.assertNotIn("non-interactive defaults", output)
        self.assertFalse((self.bin / "nonocode").exists())
        self.assertFalse(self.settings.exists())
        self.assertFalse(self.plugin.exists())

    def test_plugin_install_failure_stops_installer(self):
        self.opencode.write_text("#!/bin/sh\nexit 42\n")
        output = self.install(expected_returncode=1)
        self.assertIn("Sandbox Awareness installation failed", output)
        self.assertNotIn("nonocode: done", output)
        self.assertFalse(self.plugin.exists())

    def test_existing_local_plugin_is_not_overwritten_or_duplicated(self):
        self.plugin.mkdir(parents=True)
        entry = self.plugin / "index.js"
        entry.write_text("existing plugin")
        output = self.install(expected_returncode=1)
        self.assertIn("move it outside plugins/", output)
        self.assertNotIn(json.dumps(["opencode", "plugin", "add", PLUGIN]), output)
        self.assertEqual(entry.read_text(), "existing plugin")

    def test_accept_and_repeat_preserves_config(self):
        self.settings.parent.mkdir(parents=True)
        settings = json.loads((HERE / "config/opencode-dev.linux.json").read_text())
        settings["exclude"].append("/custom-marker")
        settings["read_exceptions"] = ["$HOME/existing-exception"]
        self.settings.write_text(json.dumps(settings))
        originals = {}
        for name in [".bashrc", ".zshrc"]:
            originals[name] = "alias opencode='old-command'\nexport KEEP_ME=yes\n"
            (self.home / name).write_text(originals[name])
        self.install("y\ny\nboth\ny\n")
        first = {name: (self.home / name).read_text() for name in originals}
        self.install("y\ny\nboth\ny\n")
        expected = dict(settings)
        expected["read_exceptions"] = [
            "$HOME/existing-exception",
            "$HOME/.ssh/known_hosts",
        ]
        self.assertEqual(json.loads(self.settings.read_text()), expected)
        for name, original in originals.items():
            self.assertEqual((self.home / name).read_text(), first[name])
            self.assertEqual(first[name].count(BEGIN), 1)
            self.assertTrue(first[name].startswith(original))
            self.assertEqual(
                (self.home / (name + ".nonocode.bak")).read_text(), original
            )

    def test_decline_leaves_existing_choices_untouched(self):
        output = self.install("n\nn\nn\n")
        self.assertNotIn(json.dumps(["opencode", "plugin", "add", PLUGIN]), output)
        self.assertFalse(self.plugin.exists())
        self.assertNotIn("read_exceptions", json.loads(self.settings.read_text()))
        self.install("y\ny\nbash\ny\n")
        profile = self.settings.read_bytes()
        rc = (self.home / ".bashrc").read_bytes()
        self.plugin.mkdir(parents=True)
        (self.plugin / "index.js").write_text("existing plugin")
        output = self.install("n\nn\nn\n")
        self.assertNotIn(json.dumps(["opencode", "plugin", "add", PLUGIN]), output)
        self.assertEqual(self.settings.read_bytes(), profile)
        self.assertEqual((self.home / ".bashrc").read_bytes(), rc)
        self.assertEqual((self.plugin / "index.js").read_text(), "existing plugin")

    def test_piped_installer_reads_answers_from_terminal(self):
        output = self.install("y\ny\nzsh\nn\n", piped=True)
        self.assertNotIn(json.dumps(["opencode", "plugin", "add", PLUGIN]), output)
        self.assertIn(
            "$HOME/.ssh/known_hosts",
            json.loads(self.settings.read_text())["read_exceptions"],
        )
        self.assertTrue((self.home / ".zshrc").exists())
        self.assertFalse((self.home / ".bashrc").exists())
        self.assertFalse(self.plugin.exists())

    def test_prompt_defaults_and_shell_selection(self):
        self.env["SHELL"] = "/bin/zsh"
        self.env["ZDOTDIR"] = str(self.home / "zsh")
        output = self.install("\n\n\n\n")
        self.assertIn(
            "$HOME/.ssh/known_hosts",
            json.loads(self.settings.read_text())["read_exceptions"],
        )
        self.assertTrue((self.home / "zsh/.zshrc").exists())
        self.assertFalse((self.home / ".bashrc").exists())
        self.assertIn(json.dumps(["opencode", "plugin", "add", PLUGIN]), output)
        self.assertFalse(self.plugin.exists())

    def test_shell_routing_in_bash_and_zsh(self):
        self.install("n\ny\nboth\nn\n")
        self.record_command(self.bin / "nonocode", "nonocode")
        project = self.root / "project"
        project.mkdir()
        cases = [
            (project, [], ["nonocode"]),
            (project, ["--no-sandbox"], ["opencode"]),
            (project, ["--no-sandbox", "run", "hello"], ["opencode", "run", "hello"]),
            (self.home, [], ["opencode", "/tmp"]),
            (self.home, ["-c"], ["opencode", "-c"]),
            (Path("/tmp"), [], ["opencode"]),
            (project, ["auth", "login"], ["opencode", "auth", "login"]),
            (project, ["--continue", "models"], ["opencode", "--continue", "models"]),
            (project, ["--prompt", "auth"], ["nonocode", "--prompt", "auth"]),
            (project, ["--prompt=auth"], ["nonocode", "--prompt=auth"]),
            (project, ["--session"], ["nonocode", "--session"]),
            (project, ["run", "auth"], ["nonocode", "run", "auth"]),
            (project, ["--unknown", "auth"], ["nonocode", "--unknown", "auth"]),
            (project, ["--prompt", "two words"], ["nonocode", "--prompt", "two words"]),
        ]
        for shell in ["bash", "zsh"]:
            with self.subTest(shell=shell):
                if not shutil.which(shell):
                    self.skipTest(f"{shell} is not installed")
                rc = self.home / (".bashrc" if shell == "bash" else ".zshrc")
                for cwd, arguments, expected in cases:
                    with self.subTest(shell=shell, cwd=cwd, arguments=arguments):
                        result = subprocess.run(
                            [
                                shell,
                                "-c",
                                f'source "{rc}"\nopencode "$@"',
                                "test",
                                *arguments,
                            ],
                            check=False,
                            cwd=cwd,
                            env=self.env,
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(json.loads(result.stdout), expected)


if __name__ == "__main__":
    unittest.main()
