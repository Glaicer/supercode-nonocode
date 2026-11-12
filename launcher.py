#!/usr/bin/env python3
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def expand(value):
    defaults = {
        "HOME": str(Path.home()),
        "XDG_CONFIG_HOME": str(Path.home() / ".config"),
        "XDG_CACHE_HOME": str(Path.home() / ".cache"),
        "XDG_DATA_HOME": str(Path.home() / ".local/share"),
        "XDG_STATE_HOME": str(Path.home() / ".local/state"),
        "TMPDIR": tempfile.gettempdir(),
    }
    for key, default in defaults.items():
        value = value.replace("$" + key, os.environ.get(key, default))
    return Path(os.path.expanduser(value)).resolve()


def within(path, parent):
    return path == parent or parent in path.parents


def nono_bin():
    found = shutil.which("nono")
    if found:
        return found
    if os.access("/usr/bin/nono", os.X_OK):
        return "/usr/bin/nono"
    raise ValueError(
        "nono is not installed; see https://docs.nono.sh/cli/getting_started/installation"
    )


def opencode_bin():
    bundled = Path.home() / ".opencode/bin/opencode"
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)
    found = shutil.which("opencode")
    if found:
        return found
    raise ValueError(
        "opencode is not installed; run: curl -fsSL https://opencode.ai/install | bash"
    )


def split_grants(path, excluded):
    path = path.resolve()
    if any(within(path, item) for item in excluded):
        return []
    if not path.exists():
        return []
    if not any(within(item, path) for item in excluded):
        return [str(path)]
    if not path.is_dir():
        return []
    grants = []
    try:
        children = sorted(path.iterdir())
    except PermissionError:
        return []
    for child in children:
        if not child.is_symlink():
            grants.extend(split_grants(child, excluded))
    return grants


def linked_worktree_common_dir(cwd):
    git = shutil.which("git")
    if not git:
        return None
    result = subprocess.run(
        [
            git,
            "-C",
            str(cwd),
            "rev-parse",
            "--path-format=absolute",
            "--git-dir",
            "--git-common-dir",
            "--show-toplevel",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = result.stdout.splitlines()
    if result.returncode != 0 or len(lines) != 3:
        return None
    git_dir, common, toplevel = (Path(line).resolve() for line in lines)
    # why: cwd/.git is agent-writable, so trust only a worktree the main repository registered back to cwd
    if git_dir.parent != common / "worktrees":
        return None
    try:
        registered = (git_dir / (git_dir / "gitdir").read_text().strip()).resolve()
    except OSError:
        return None
    return common if registered == toplevel / ".git" else None


def make_profile(settings, cwd):
    protected = [expand("$HOME/.nono"), expand("$XDG_STATE_HOME/nono")]
    excluded = protected[:]
    for value in settings["exclude"]:
        expanded = str(expand(value))
        excluded.extend(Path(item).resolve() for item in glob.glob(expanded))
        if not glob.has_magic(expanded):
            excluded.append(Path(expanded))
    if cwd == Path("/") or cwd == Path.home().resolve():
        raise ValueError("change to a project directory before running nonocode")
    if any(within(cwd, item) for item in excluded):
        raise ValueError("the project directory is excluded from the sandbox")
    read = []
    for value in settings["read"]:
        read.extend(split_grants(expand(value), excluded))
    for value in settings.get("read_exceptions", []):
        read.extend(split_grants(expand(value), protected))
    writable = [cwd, *(expand(value) for value in settings["write"])]
    common = linked_worktree_common_dir(cwd)
    if common:
        # why: a linked worktree keeps its index, objects and refs in the main repository's .git
        writable.append(common)
    allow = []
    for path in writable:
        if any(within(path, item) for item in protected):
            raise ValueError("a writable path targets nono state")
        allow.extend(split_grants(path, excluded))
    excluded_groups = [
        "system_read_linux_core",
        "user_tools",
        "homebrew_linux",
        "dangerous_commands",
        "dangerous_commands_linux",
        "dangerous_commands_macos",
    ]
    if sys.platform == "darwin":
        excluded_groups.extend(
            ["system_read_macos", "system_write_macos", "homebrew_macos"]
        )
    return {
        "meta": {"name": "opencode-dev", "version": "1"},
        "security": {"capability_elevation": False},
        "workdir": {"access": "none"},
        "filesystem": {
            "read": sorted(set(read)),
            "allow": sorted(set(allow)),
        },
        "groups": {"exclude": excluded_groups},
        "network": {"block": False},
    }


def validate_args(args):
    switches = {"--continue", "-c", "--print-logs", "--help", "-h", "--version", "-v"}
    values = {"--session", "-s", "--prompt", "--log-level"}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in switches:
            index += 1
        elif arg in values and index + 1 < len(args):
            index += 2
        elif any(arg.startswith(flag + "=") for flag in values):
            index += 1
        else:
            raise ValueError(
                f"unsupported argument {arg!r}; nonocode opens the current project only"
            )


def run_in_sandbox(settings, command, cwd=None, env=None):
    cwd = Path(cwd or os.getcwd()).resolve()
    profile = make_profile(settings, cwd)
    temporary_root = Path(tempfile.gettempdir()) / "opencode"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="nono-launch-", dir=temporary_root
    ) as directory:
        path = Path(directory) / "profile.json"
        path.write_text(json.dumps(profile))
        child_env = dict(os.environ if env is None else env)
        child_env["OPENCODE_SANDBOX_MODE"] = "sandboxed"
        for name in list(child_env):
            if name.startswith("NONO_"):
                del child_env[name]
        return subprocess.run(
            [
                nono_bin(),
                "run",
                "--profile",
                str(path),
                "--no-rollback",
                "--silent",
                "--startup-timeout",
                "0",
                "--",
                *command,
            ],
            check=False,
            cwd=cwd,
            env=child_env,
        ).returncode


def main():
    validate_args(sys.argv[1:])
    settings_path = expand("$XDG_CONFIG_HOME/nono/opencode-dev.json")
    settings = json.loads(settings_path.read_text())
    for value in settings["write"]:
        path = expand(value)
        # write entries may be device nodes (/dev/ptmx); only create missing dirs
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
    return run_in_sandbox(
        settings,
        [
            opencode_bin(),
            "--standalone",
            "--auto",
            *sys.argv[1:],
        ],
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        print(f"nonocode: {error}", file=sys.stderr)
        sys.exit(1)
