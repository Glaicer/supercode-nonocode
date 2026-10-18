# Technical guide

[Back to README](../README.md)

For agents installing or configuring nonocode on a user's machine, follow the
[setup workflow](#agent-setup-workflow). The remaining sections are reference;
[development checks](#development-checks) are for changing this repository, not
a prerequisite for an end-user installation.

- [Agent setup workflow](#agent-setup-workflow)
- [Layout](#layout)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running nonocode](#running-nonocode)
- [Sandbox boundaries](#sandbox-boundaries)
- [Allowing extra paths](#allowing-extra-paths)
- [Sandbox Awareness](#sandbox-awareness)
- [Verification](#verification)

## Agent setup workflow

Installation changes user-level binaries, shell configuration, and possibly
system packages. Work within your current permissions. If you are already
sandboxed, use `question` to give the user the exact blocked command, working
directory, and effects to perform outside the sandbox; wait for their result.
Use a normal response if `question` is unavailable. An installation request is
not permission to escape the current sandbox or weaken its protections.

1. **Preflight.** Identify the OS and architecture (`uname -s`, `uname -m`),
   login shell (`$SHELL`), any `ZDOTDIR`/XDG overrides, and the user's intended
   project directory. Check OpenCode's actual `--version` and `--help`, preferring
   `~/.opencode/bin/opencode` over the executable on `PATH`, as the installer
   does. Confirm V2 supports `--standalone` and `--auto`, and meet the
   [plugin's minimum version](#installation) if installing it. The installer
   checks OpenCode's presence, not its version. Check for an existing installed
   profile and shell integration before proposing changes. Proceed only with
   a supported host and a compatible OpenCode executable; if OpenCode is
   missing, follow its [V2 installation docs](https://opencode.ai/v2/docs/)
   before continuing.
2. **Agree on choices.** Resolve the three [installer choices](#what-the-installer-asks),
   the target shell(s), and any package-manager/`sudo` work with the user. On
   macOS, disclose experimental enforcement; on WSL2, prefer a project in the
   Linux filesystem. Use `--non-interactive` only when the user accepts all its
   defaults. There are no installer flags for individual yes/no choices; use a
   real terminal for different answers. Piping answers to stdin is unreliable
   because a piped installer reads answers from `/dev/tty`.
3. **Install.** Run one of the [installation commands](#installation) as the
   regular user. Prefer the installer over recreating its shell block or
   manually registering the plugin. If it exits nonzero, inspect the error and
   any completed changes: installation is not transactional, so a launcher or
   plugin may already have been installed. Continue after the cause is resolved
   and its final sandboxed version check succeeds.
4. **Configure.** Use the [installed configuration map](#configuration), keep
   existing settings, and add only user-approved [extra paths](#allowing-extra-paths).
   Ensure `~/.local/bin` is on `PATH`. Keep the same XDG environment during
   installation and normal launches so both use the same profile. Configuration
   is ready when the installed JSON parses and the agreed grants and shell
   choices are present, not when the repository examples have been edited.
5. **Activate.** Have the user open a new target shell or reload its selected
   config. Sourcing a file in an agent's child shell cannot update the user's
   existing terminal. If provider authentication is missing, have the user run
   `opencode auth login` outside the sandbox; keep credentials out of chat and
   tracked files. Close and relaunch sandboxed sessions after profile or plugin
   changes; nonocode uses a private server, so a shared-service restart is not
   needed for this setup.
6. **Verify and hand back.** Complete [installation verification](#installation-verification)
   from the intended project. Report the resolved binaries/versions, installed
   profile path, changed shell files, optional choices, extra grants, and actual
   check results. Name pending user steps explicitly; distinguish an installed
   launcher from a working authenticated session and from tested OS enforcement.

## Layout

Paths below are relative to the repository root. The local `sandbox-awareness/`
directory contains plugin source for development; the installer uses the
published npm package instead.

| Path | What it is |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `install.sh`                                         | Installer: requires OpenCode, installs nono and nonocode; works from `curl \| bash` or a local checkout. |
| `launcher.py`                                        | Implementation copied to `~/.local/bin/nonocode`: derives a nono profile per launch and runs OpenCode inside it. |
| `config/opencode-dev.linux.json`                     | Default Linux/WSL2 profile. Installed as `~/.config/nono/opencode-dev.json` only if absent. |
| `config/opencode-dev.macos.json`                     | Experimental macOS profile, installed under the same name. |
| `sandbox-awareness/index.js`                         | Local OpenCode plugin: when `OPENCODE_SANDBOX_MODE=sandboxed` is set, appends sandbox guidance to the system prompt and tells the agent to request manual help via `question`. |
| `sandbox-awareness/tui.js`                           | TUI entrypoint: shows `(sandboxed)` next to the working directory in the prompt footer and in the home footer, only when the sandbox marker is set. |
| `sandbox-awareness/package.json`, `sandbox-awareness/index.test.js` | Published plugin metadata, compatibility requirements, native Node syntax checks and hook tests; no build step. |
| `test_launcher.py`                                   | Unit tests plus a real nono enforcement test. |
| `test_install.py`                                    | Installer choices, repeat installs and Bash/Zsh routing in a throwaway home with stub dependencies; interactive tests require pseudo-terminals. |
| `probe_sandbox_awareness.py`                         | Boots an isolated server with a loopback provider and asserts the plugin injects the guidance only in sandboxed mode. |
| `probe_install.py`                                   | Installer checks: syntax, a local-checkout install into a throwaway `$HOME`, a download-mode install from a loopback HTTP server, and a clean-system container install. |

## Installation

Supports **x86_64** and **ARM64** hosts:

| Platform | Sandbox | Profile |
| --- | --- | --- |
| Linux | Landlock, enabled in the kernel LSM list | [Linux profile](../config/opencode-dev.linux.json) |
| Windows through WSL2 | Landlock inside the Linux distribution | Same Linux profile |
| macOS | Seatbelt | [macOS profile](../config/opencode-dev.macos.json), experimental |

The macOS installation branch and generated grants are tested with fixtures on
Linux, **not with native Seatbelt enforcement on a Mac**. Native Windows is not
supported; run both OpenCode and nono inside WSL2 instead. Windows-mounted paths
such as `/mnt/c` need a separate access review before using them as project or
grant roots.

OpenCode V2 (`--standalone`, `--auto`) is required. Sandbox Awareness requires
OpenCode V2 **2.0.28 or newer**. Run the installer as a regular user, not root.

Install [OpenCode V2](https://opencode.ai/v2/docs/) before running the installer.
It checks `~/.opencode/bin/opencode`, then `PATH`, and stops before asking
questions or installing anything if neither contains OpenCode. It does not
install or update OpenCode.

From GitHub:

```sh
curl -fsSL https://raw.githubusercontent.com/Glaicer/supercode-nonocode/main/install.sh | bash
```

Or from the repository root of a local checkout:

```sh
bash install.sh
```

Local-checkout detection uses the **current working directory**, not the
script's location: both `launcher.py` and the selected `config/` profile must
be present there. Running `bash /path/to/install.sh` from another directory
can download the published payload instead of installing that checkout.

The installer:

- selects `opencode-dev.linux.json` for Linux/WSL2 and `opencode-dev.macos.json` for macOS;
- on Linux/WSL2, checks the Landlock LSM list and warns if it is missing;
- installs `nono` when missing — Homebrew on macOS; on Linux/WSL2, COPR `always-further/nono` (`nono-cli`) on dnf, the release `.deb`/`.rpm` from GitHub on apt/zypper, Homebrew, AUR `nono-ai-bin` via yay/paru, or a source build via cargo as the last resort;
- requires an existing OpenCode installation and never installs it;
- installs `nonocode` to `~/.local/bin` and optionally Sandbox Awareness from npm using `opencode plugin add @glaicer/supercode-sandbox-awareness`;
- copies the selected profile to `$XDG_CONFIG_HOME/nono/opencode-dev.json` (default `~/.config/nono/opencode-dev.json`) **only when absent**, preserving existing settings; OpenCode's CLI handles the plugin's global configuration entry;
- verifies the full chain at the end by running `nonocode --version` inside the sandbox.

On macOS, install Homebrew first if you want the installer to add missing nono
or Python dependencies. If they are already available, Homebrew is not required.
Moving an existing profile between operating systems still requires reviewing
its paths yourself: the installer will not replace it with a platform default.

### What the installer asks

There are three optional extras. Press Enter to accept the default for each one.

1. **Let the agent read `~/.ssh/known_hosts` for Git over SSH?** Default: **yes**.
   Git over SSH uses this file to check server identities. Without access,
   `git pull` and `git push` over SSH can fail when the server cannot be verified.
   Git over HTTPS is not affected. Saying yes lets the
   sandbox read this one file, not your SSH keys or the rest of `~/.ssh`. It
   doesn't set up authentication or let SSH save new hosts to the file. Your
   other profile settings are kept.
2. **Use `opencode` for sandboxed project sessions?** Default: **yes**.
   A convenient way to keep using the same command: `opencode` starts a sandboxed
   session in a project. In `~` and `/tmp`, it runs without the sandbox for system
   debugging, general questions, or other work outside a project. Management
   commands and `opencode --no-sandbox` in any project also run without the
   sandbox. `--no-sandbox` must be the first argument.
   If you say yes, you'll choose **bash**, **zsh**, or **both**. The default is
   **zsh** if `$SHELL` points to Zsh, otherwise **bash**. Open a new shell or
   reload the selected shell config to activate it.
3. **Install the [Sandbox Awareness](https://www.npmjs.com/package/@glaicer/supercode-sandbox-awareness) plugin?** Default: **yes**, recommended.
   Tells the agent about sandbox limits and adds a sandbox status indicator to
   the terminal UI. The OS still enforces the sandbox without it, but the agent
   may not understand why an operation was blocked. The installer runs
   `opencode plugin add @glaicer/supercode-sandbox-awareness` to install the npm
   package and register it globally. It no longer copies plugin files into
   `~/.config/opencode/plugins/`.

If an older install left a local copy in
`~/.config/opencode/plugins/sandbox-awareness/`, the installer asks you to move
it outside `plugins/` before installing the npm package. It won't delete your
files or load both copies. Choose **no** to keep using the local copy instead.

Shell integration adds a managed block to `~/.bashrc` or
`${ZDOTDIR:-$HOME}/.zshrc`. Existing files get a one-time `.nonocode.bak` backup;
repeat installs update the block without changing the surrounding config. Once
loaded, it overrides any existing `opencode` alias or function. It uses
`~/.opencode/bin/opencode` when available, otherwise the executable on `PATH`;
`nonocode` must also be on `PATH`.

Saying no skips a step; it doesn't remove a plugin, shell integration, or read
exception you already have.

The questions work with `curl | bash` too: answers come from your terminal.
Without a terminal, the installer answers **yes** to all three questions and
selects **zsh** if `$SHELL` points to Zsh, otherwise **bash**, without asking a
follow-up question. To use these defaults without being asked, run
`bash install.sh --non-interactive`, or pipe the downloaded script to
`bash -s -- --non-interactive`.

Override the payload source with `NONOCODE_REPO` (defaults to
`https://raw.githubusercontent.com/Glaicer/supercode-nonocode/main`). This changes where
the launcher and example profile are downloaded; Sandbox Awareness still comes
from npm through OpenCode's CLI.

For a manual nono installation on Fedora:

```sh
sudo dnf copr enable always-further/nono
sudo dnf install nono-cli
```

## Configuration

Repository files are installation inputs; the files below control an installed
machine. nonocode has one user-level profile, not a separate settings file per
project. OpenCode's own project configuration remains independent.

| Installed location | Purpose |
| --- | --- |
| `~/.local/bin/nonocode` | Executable copy of `launcher.py`; rerunning the installer replaces it. |
| `${XDG_CONFIG_HOME:-$HOME/.config}/nono/opencode-dev.json` | Strict JSON sandbox settings: required `read`, `write`, `exclude` arrays and optional `read_exceptions`. See [extra paths](#allowing-extra-paths) for their meanings. |
| `~/.bashrc`, `${ZDOTDIR:-$HOME}/.zshrc` | Selected shell's managed integration block; backup and repeat-install behavior are described under [installer choices](#what-the-installer-asks). |
| `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json(c)` | OpenCode's global server settings, including providers, permissions and server plugins. Preserve unrelated configuration. |
| `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/cli.json` | OpenCode's global terminal settings and CLI plugins. Let `opencode plugin add` handle package registration rather than guessing which file to edit. |

Use the [V2 configuration guide](https://opencode.ai/v2/docs/config) and
[CLI settings reference](https://opencode.ai/v2/docs/cli/config) for OpenCode
settings; their JSON/JSONC configuration is not the nonocode profile format.
Existing `OPENCODE_CONFIG_DIR` or other OpenCode path overrides also need review:
nonocode inherits them, but they do not automatically add filesystem grants.
An overridden runtime directory outside existing grants may need a narrow
`write` entry. Changing `OPENCODE_CONFIG_DIR` does not relocate nonocode's profile.

Profile paths support `~` and the literal `$HOME`, `$XDG_CONFIG_HOME`,
`$XDG_CACHE_HOME`, `$XDG_DATA_HOME`, `$XDG_STATE_HOME`, and `$TMPDIR` placeholders.
Use that `$NAME` form, not `${NAME}` or arbitrary shell expressions. XDG defaults
are `~/.config`, `~/.cache`, `~/.local/share`, and `~/.local/state`, respectively.
Paths are resolved to their real locations, so a symlink is not an extra grant.
The launcher creates missing `write` directories before entering the sandbox;
existing device entries are left as devices. Missing read paths are skipped
until a subsequent launch where they exist. `exclude` also supports glob
patterns, expanded at launch.

The installer only warns if `~/.local/bin` is missing from `PATH`; it does not
add it. In Bash or Zsh, add this to the appropriate user-owned startup file if
needed, before the managed integration block:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

The shell wrapper and launcher prefer `~/.opencode/bin/opencode` to `PATH`;
check that binary when multiple OpenCode versions are installed. nono is found
on `PATH`, with `/usr/bin/nono` as a fallback. There is no Fish integration:
Fish users can put `~/.local/bin` on their shell's path and invoke `nonocode`
directly rather than copying the Bash/Zsh function.

## Running nonocode

```sh
nonocode  # sandboxed OpenCode + auto approve in the current project
opencode  # unchanged unless you opted into shell integration
```

`nonocode` refuses `/` and `$HOME` as the working directory and rejects any argument
outside a small allow-list, so it cannot be turned into a server or pointed at a
directory outside the project. The marker is set only in the child environment;
the shell never exports it.

Each launch uses the resolved **current working directory**, not an automatically
detected Git root, and runs OpenCode with `--standalone --auto`: a private server
with automatic approval of permissions that are not explicitly denied. `cd` to
the intended project root first; launching from a subdirectory adds no grant for
its parent or siblings, though other profile grants still apply. Existing
OpenCode denies still apply. Supported arguments are:

- `--continue` / `-c`
- `--session` / `-s`, followed by a session ID
- `--prompt`, followed by a prompt
- `--log-level`, followed by a level
- `--print-logs`
- `--help` / `-h` and `--version` / `-v`

Options with values also accept the `--option=value` form.

### Shell integration

This is the snippet `install.sh` adds to your selected shell config when shell
integration is enabled (yes by default). It keeps one `opencode` command for
both sandboxed and unsandboxed sessions.

For a manual install, add it to `~/.bashrc` or `${ZDOTDIR:-$HOME}/.zshrc`, replacing
any existing `opencode` alias or function. It uses the bundled OpenCode path or
falls back to `PATH`, so Homebrew installations work too. `command` bypasses the
shell function when invoking the executable, avoiding recursion.

```bash
unalias opencode 2>/dev/null || true
opencode() {
  local no_sandbox=0
  local opencode_bin="$HOME/.opencode/bin/opencode"
  if [[ ! -x "$opencode_bin" ]]; then
    opencode_bin=opencode
  fi
  if [[ "${1-}" == "--no-sandbox" ]]; then
    shift
    no_sandbox=1
  fi
  if [[ "$no_sandbox" == 1 || "$PWD" == "$HOME" || "$PWD" == "/tmp" ]]; then
    if (( $# == 0 )) && [[ "$PWD" == "$HOME" ]]; then
      command "$opencode_bin" /tmp
    else
      command "$opencode_bin" "$@"
    fi
  else
    local arg skip=0
    for arg in "$@"; do
      if (( skip )); then
        skip=0
        continue
      fi
      case "$arg" in
        auth|mcp|plugin|upgrade|update|uninstall|models|stats|session|debug|service|reload|pair|--help|-h|--version|-v|--completions|--completions=*)
          command "$opencode_bin" "$@"
          return $?
          ;;
        --continue|-c|--print-logs|--wizard)
          ;;
        --session|-s|--prompt|--log-level)
          skip=1
          ;;
        --session=*|--prompt=*|--log-level=*)
          ;;
        *)
          break
          ;;
      esac
    done
    nonocode "$@"
  fi
}
```

Reload your shell configuration with `source ~/.bashrc` or
`source "${ZDOTDIR:-$HOME}/.zshrc"`, as appropriate.

- In project directories, bare `opencode` and supported TUI options
  (`--continue`/`-c`, `--session`/`-s`, `--prompt`, `--log-level`, `--print-logs`)
  go through `nonocode`.
- Use `opencode --no-sandbox` to force an unsandboxed session in any directory,
  or `opencode --no-sandbox <args>` to pass arguments directly to OpenCode.
  `--no-sandbox` must be the first argument; the function removes it before launch.
- Exactly in `~` or `/tmp`, all invocations run without the sandbox. Bare
  `opencode` from `~` opens `/tmp`; arguments are otherwise passed unchanged.
- Management commands such as `opencode auth login`, plus help, version and
  completion output, bypass the sandbox in any directory. No `/tmp` argument is
  added to them.
- Outside `~` and `/tmp`, unsupported invocations (`run`, `mini`, `acp`, `serve`,
  explicit directories, `--server`, `--standalone`, `--auto`, or unknown flags)
  are rejected by `nonocode`, not silently run without protection. To deliberately
  bypass the sandbox, use `opencode --no-sandbox` or invoke
  `~/.opencode/bin/opencode` directly.

Here, "project" means any directory other than those two exact shell paths;
the wrapper does not inspect Git metadata. `/tmp/my-project` is sandboxed, but
bare `opencode` in `/tmp` is not. The exception does not expand to `$TMPDIR` or
symlink spellings of these paths. `--no-sandbox` belongs to this shell function,
not to `nonocode` or the OpenCode executable. Other shells, scripts, IDEs, and
direct executable invocations do not inherit the function's routing; use
`nonocode` explicitly wherever sandboxing is required.

## Sandbox boundaries

The launcher reads `~/.config/nono/opencode-dev.json`, or the equivalent under
`$XDG_CONFIG_HOME`, and creates a nono profile for each launch. The repository's
[Linux/WSL2 profile](../config/opencode-dev.linux.json) and
[macOS profile](../config/opencode-dev.macos.json) define the platform's read,
write, and exclusion lists. Existing profiles are not replaced during
installation; opting into `known_hosts` access adds just that read exception.

With the default Linux/WSL2 profile, `filesystem.read` = `/` minus exclusions;
`filesystem.allow` = project, `/tmp`,
`$HOME/.opencode`, `$XDG_CONFIG_HOME/opencode`, `$XDG_CACHE_HOME/opencode`,
`$XDG_DATA_HOME/opencode`, `$XDG_DATA_HOME/opentui`, `$XDG_STATE_HOME/opencode`,
`/dev/ptmx`, and `/dev/pts`. The last two support tools that need pseudo-terminals.
Everything else is read-only, and writes outside `allow` fail with `EACCES` —
including from a child Python process.

The macOS profile reads the home directory and selected system roots rather
than all of `/`, avoiding a blanket read grant through APFS data-volume aliases.
It permits writes to the project, `/tmp`, the user's `$TMPDIR`, OpenCode's runtime
directories, and `/dev` for native terminal devices. The launcher disables
nono's broad macOS system read/write groups so they do not add grants beyond
the profile; required protection groups remain enabled. This still needs a
native Mac smoke test before it can be considered verified.

`$HOME`, the XDG directory variables, and `$TMPDIR` are expanded by the launcher.
`$TMPDIR` falls back to Python's system temporary directory if unset. Generated
nono profiles are stored temporarily under that directory's `opencode/` folder.

Network access is allowed. This is a filesystem boundary, not network isolation.

The boundary applies to the launched OpenCode process and its local children,
not already-running services or remote MCP tools. Network requests can still
change external systems or send readable data elsewhere. The launcher inherits
the environment, including exported credentials; it strips `NONO_*` variables
but does not sanitize secrets from other variables. Files allowed for reading,
including project `.env` files, are not made confidential by this sandbox.

Writable grants permit deletion and modification of existing files, including
project files and OpenCode's own configuration/state. nonocode runs nono with
`--no-rollback`; it does not provide automatic recovery. Keep normal backups
and version control. This setup limits accidental filesystem damage, not a
deliberate escape attempt or actions deliberately run outside the sandbox.

Denied: nono's own state (`$HOME/.nono`, `$XDG_STATE_HOME/nono`,
`$XDG_CONFIG_HOME/nono`) and the exclusions in `opencode-dev.json` (`~/.ssh`,
`~/.gnupg`, `~/.pki`, keyrings, `~/.password-store`, browser data, `/root`,
`/boot`, `/etc/shadow*`). On top of that nono's required groups apply
(`deny_credentials`, `deny_shell_configs`, `deny_shell_history`, and the platform's
keychain/browser groups), covering `~/.aws`, `~/.kube`, `~/.docker`, gcloud,
`~/.zshrc`, shell history and similar. On macOS, the profile also excludes
Keychains, browser profiles under `~/Library`, Safari containers, Mail,
Messages, Cookies, and MobileSync backups.

The optional `read_exceptions` entry for `~/.ssh/known_hosts` grants read-only
access to that file while leaving the rest of `~/.ssh` excluded.

Not enforced at the OS level: general file masks (`.env`, `*.pem`, …). Those
remain OpenCode permission rules. OpenCode rules such as `ask` are not converted
into filesystem denies.

**Do not add `bypass_protection` for granted paths.** It removes *group-level*
deny rules, so exempting every grant re-exposes `~/.zshrc` and any granted
credential path; verified with `nono` directly.

## Allowing extra paths

Some tools keep caches, installed binaries, or state outside your project. If
one of those paths is blocked, you can grant access once instead of repeatedly
running the tool outside the sandbox.

### 1. Find the path the tool needs

Look for the path in the permission error, or ask the agent to explain which
operation failed and where. Cargo might need its registry cache; npm might need
its download cache. Allow the path that is actually needed, not every directory
the tool could use.

### 2. Edit your profile outside the sandbox

Open `~/.config/nono/opencode-dev.json` yourself, outside the sandbox. If you set
`XDG_CONFIG_HOME`, the launcher reads `$XDG_CONFIG_HOME/nono/opencode-dev.json`
instead. Edit this installed profile, not the example in the repository.

These settings apply to **every project** you launch with nonocode. Keep the
existing entries and other fields; you only need to add the relevant path.

| Field | What it does |
| --- | --- |
| `write` | Allows reading and writing a path, including creating, changing, and deleting files inside a directory. |
| `read` | Adds normal read access. Linux/WSL2 defaults to `["/"]`; macOS lists the home directory and selected system roots. |
| `read_exceptions` | Adds read-only access to a specific path otherwise withheld by the profile's `exclude` list. |
| `exclude` | Withholds paths from normal read and write grants. **This is a blocklist, not a place to add permissions.** |

### 3. Add only the access you need

For tools that need to write outside the project, append the relevant entries
to the existing **`write` array**. Common examples are:

- `$HOME/.cargo` for Cargo's cache and install directory.
- `$HOME/.npm` for npm's cache.
- `$XDG_STATE_HOME/opencode-theme-watcher` if that tool needs its state directory.

For example, these are two extra entries to append to `write`, **not a
replacement for your profile or its existing write paths**:

```json
[
  "$HOME/.cargo",
  "$HOME/.npm"
]
```

Use the actual cache path if you've customized it. Granting a whole directory
also allows changing its existing files, not just adding cache entries. If the
error names a smaller subdirectory, consider allowing just that one.

**Terminal tools:** on Linux, programs that create pseudo-terminals can need
`/dev/ptmx` and `/dev/pts` in `write`. Both are already in the Linux/WSL2 example
profile. The macOS profile instead grants `/dev` for its native terminal devices.
Older installed profiles may not have these entries because the installer
preserves existing settings; add them if missing and needed. These paths grant
access to terminal devices, so treat them as device access, not cache folders.

**Read-only access:** if a tool only needs one excluded file, use
`read_exceptions` rather than opening the whole directory. For example, this
field lets SSH read saved server identities while keeping the rest of `~/.ssh`
excluded:

```json
{
  "read_exceptions": ["$HOME/.ssh/known_hosts"]
}
```

Merge that field into the existing profile, preserving any other read
exceptions. It does not allow writing the file or reading SSH keys. The
installer already adds this exception unless you decline it.

Adding a path to `write` does **not** override `exclude`. Keep credential and
shell-config protections in place; don't grant all of `$HOME` or `/` to fix one
tool. The launcher protects `$HOME/.nono` and `$XDG_STATE_HOME/nono` even from
`read_exceptions`.

### 4. Start a new sandboxed session

Save the JSON, exit the current sandboxed OpenCode instance, and launch it
again from your project using `opencode` with shell integration or `nonocode`.
Retry the operation. Existing sandboxed processes keep their original limits;
editing the file does not update them. No reinstall is needed.

If it still fails, check the exact error before broadening access. Profile
grants don't fix missing programs, SSH authentication, ordinary Unix permission
errors, or separate OpenCode permission rules. nono's protection groups still
apply; don't disable them wholesale to get a tool working.

## Sandbox Awareness

`OPENCODE_SANDBOX_MODE=sandboxed` is the mechanism-agnostic marker the launcher
sets. The marker describes the launch environment; setting it manually does not
create or enforce a sandbox. OpenCode permissions and external services are
independent of it.

The [Sandbox Awareness](https://www.npmjs.com/package/@glaicer/supercode-sandbox-awareness)
plugin reads the marker and injects the sandbox
guidance into every agent-loop model request, so it survives compaction. Without
the marker it registers nothing. Its TUI entrypoint adds `(sandboxed)` beside
the built-in working-directory display and to the home footer; it leaves the
directory's navigation and running-status display intact. Both entrypoints are
plain JavaScript and use the host's UI runtime, with no build step.
The installer uses OpenCode's CLI to install the published package and register
it in the global configuration. nonocode does not depend on Command Gate or any
other plugin.

If you also use [Command Gate](https://github.com/Glaicer/supercode-command-gate),
a compatible version can use the same marker to skip command review inside the
sandbox. Consult its own documentation for setup and compatibility.

## Verification

### Installation verification

Use the user's normal environment and an intended project directory, not `/`
or `$HOME`. These checks do not require a repository checkout:

```sh
command -v nonocode
python3 -m json.tool "${XDG_CONFIG_HOME:-$HOME/.config}/nono/opencode-dev.json" >/dev/null
nonocode --version
```

- `command -v` should resolve the installed launcher, the JSON check should
  succeed, and `nonocode --version` should exit zero with the expected OpenCode
  version. The installer's own version check runs from `/tmp`; repeat it from
  the real project to catch project-specific failures. With shell integration,
  `opencode --version` bypasses nonocode and is **not** a sandbox check.
- In a newly opened selected shell, `type opencode` should show the function if
  integration was selected. Launch bare `opencode` from the project to exercise
  routing, or `nonocode` if integration was declined. A successful reload in a
  child shell alone does not verify the user's terminal.
- If Sandbox Awareness was selected, `opencode plugin list` should include
  `@glaicer/supercode-sandbox-awareness`. A fresh sandboxed TUI should show its
  `(sandboxed)` indicator. Package presence and the environment marker alone do
  not prove that OS filesystem restrictions are enforced.
- Have the user send a short prompt such as "Reply OK without using tools" to
  confirm provider access. A version check cannot verify authentication or
  model requests. If sign-in or the TUI check is still pending, report that
  instead of calling the setup fully verified.
- For OS-enforcement evidence from a checkout, the targeted test is
  `python3 -m unittest test_launcher.LauncherTests.test_filesystem_enforcement_and_child_inheritance -v`.
  It checks a shipped profile with dummy files, **not the user's installed
  custom profile**. Run outside an existing sandbox that blocks its temporary
  home or pseudo-terminals. Report enforcement as untested if it was not run;
  keep real credentials and personal files out of smoke tests.

### Failure triage

| Symptom | Next action |
| --- | --- |
| `nonocode` not found, or `opencode` still runs directly | Check `PATH`, the chosen rc file and the user's newly opened shell; see [configuration](#configuration). |
| Landlock unavailable or nono cannot apply the sandbox | Resolve host/kernel support outside the sandbox. An unreadable or missing `/sys/kernel/security/lsm` is not proof of support; the installer only warns when it can read a list without Landlock. Keep enforcement unverified until a real launch succeeds. |
| Invalid JSON or missing profile | Check the installed profile under the current `XDG_CONFIG_HOME`; preserve custom settings rather than replacing them with an example. |
| Unsupported argument or refused working directory | `cd` to the project and use the [supported launcher arguments](#running-nonocode). Keep unsandboxed execution an explicit user choice. |
| Permission denied by a tool | Separate sandbox denial from Unix permissions and OpenCode denies; for a needed filesystem grant, follow [extra paths](#allowing-extra-paths) outside the sandbox and relaunch. |
| SSH host verification or authentication failure | `known_hosts` access only supplies saved host identities. Let the user manage host trust and credentials outside the sandbox. |
| Plugin missing, duplicated, or no indicator | Check OpenCode compatibility, the selected plugin choice, [legacy copies](#what-the-installer-asks), and a fresh sandboxed launch before editing unrelated config. |

### Development checks

For repository changes, run the relevant checks from the repository root:

```sh
bash -n install.sh
ruff check . && ruff format --check .
python3 -m unittest discover -s . -p 'test_*.py' -v
```

For installer changes only, run `python3 -m unittest test_install -v`.
These tests use temporary homes and stub `nono`/OpenCode binaries; they do not
modify your shell configs or install system packages. Run them outside a
sandbox that prevents pseudo-terminal allocation.

The launcher's filesystem-enforcement test reads a repository profile and uses
a temporary home with dummy shell settings, not your installed profile or real
shell files. It runs the real nono binary to check enforcement.

For Sandbox Awareness source changes, also run its declared checks (Node.js
24 or newer; no dependency install or build is needed):

```sh
npm --prefix sandbox-awareness run check
npm --prefix sandbox-awareness test
```

### Runtime and installation probes

These are separate from the unit tests. They start real processes and need the
relevant programs installed:

```sh
python3 probe_sandbox_awareness.py
python3 probe_install.py
```

- `probe_sandbox_awareness.py` uses an isolated server and loopback provider to
  check that guidance is injected only with the sandbox marker. The plugin path
  is relative to this checkout, and its configuration, database, and logs are
  temporary.
- `probe_install.py` runs real installations in throwaway home directories,
  including the npm plugin installation. Missing system dependencies may still
  require package-manager changes and `sudo`. Add `--container` for the
  clean-system Podman test; its fixture installs OpenCode before testing the
  nonocode installer.

Machine-specific probes that use personal session databases or private runtime
state are excluded from the public repository. SQLite files, logs, shell-config
backups, and database-backup directories are ignored too. Do not copy personal
configuration or probe output into tracked fixtures.
