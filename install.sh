#!/usr/bin/env bash
# nonocode installer: sandboxed OpenCode launcher (https://github.com/Glaicer/supercode-nonocode)
# Usage: curl -fsSL https://raw.githubusercontent.com/Glaicer/supercode-nonocode/main/install.sh | bash
set -euo pipefail

REPO="${NONOCODE_REPO:-https://raw.githubusercontent.com/Glaicer/supercode-nonocode/main}"

say() { printf 'nonocode: %s\n' "$*"; }
warn() { printf 'nonocode: WARNING: %s\n' "$*" >&2; }
die() { printf 'nonocode: ERROR: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
confirm() {
  local answer
  if [ "$interactive" = false ]; then
    [ "$2" = yes ]
    return
  fi
  while true; do
    printf '%s ' "$1" >&2
    IFS= read -r answer <&3 || die "input ended; installation cancelled"
    case "$answer" in
      y|Y|yes|YES|Yes) return 0 ;;
      n|N|no|NO|No) return 1 ;;
      '') [ "$2" = yes ]; return ;;
      *) say "please answer yes or no" ;;
    esac
  done
}
fetch() {
  if have curl; then curl -fsSL "$1" -o "$2"
  else wget -q "$1" -O "$2"
  fi
}

[ "$(id -u)" -eq 0 ] && die "run as a regular user, not root"
case "$(uname -s)" in
  Linux) platform=linux ;;
  Darwin) platform=macos ;;
  *) die "supported platforms: Linux, WSL2, and macOS; native Windows is not supported" ;;
esac
case "$(uname -m)" in
  x86_64) DEB_ARCH=amd64 RPM_ARCH=x86_64 ;;
  aarch64|arm64) DEB_ARCH=arm64 RPM_ARCH=aarch64 ;;
  *) die "unsupported architecture: $(uname -m)" ;;
esac
profile="config/opencode-dev.$platform.json"
settings_path="${XDG_CONFIG_HOME:-$HOME/.config}/nono/opencode-dev.json"

opencode_bin="$HOME/.opencode/bin/opencode"
if [ ! -x "$opencode_bin" ]; then
  opencode_bin=$(command -v opencode) || die "OpenCode was not found. Install OpenCode V2 first, then run this installer again: https://opencode.ai/v2/docs/"
fi

if [ "$platform" = linux ] && [ -r /sys/kernel/security/lsm ] && ! grep -qw landlock /sys/kernel/security/lsm; then
  warn "Landlock is missing from the kernel LSM list; nono cannot enforce the sandbox on this kernel"
fi
if [ "$platform" = macos ]; then
  warn "macOS support is experimental; native Seatbelt enforcement still needs validation on a Mac"
fi

interactive=false
case "${1-}" in
  --non-interactive) [ "$#" -eq 1 ] || die "usage: bash install.sh [--non-interactive]" ;;
  '')
    if [ -t 0 ]; then
      exec 3<&0
      interactive=true
    elif { exec 3</dev/tty; } 2>/dev/null; then
      interactive=true
    fi
    ;;
  *) die "usage: bash install.sh [--non-interactive]" ;;
esac
if [ "$interactive" = false ]; then
  say "non-interactive defaults: known_hosts=yes, shell integration=yes, Sandbox Awareness=yes"
fi

known_hosts=false
say "For git pull and git push over SSH, the agent may need to read ~/.ssh/known_hosts."
say "Without it, SSH can fail to verify the Git server and stop the command. Git over HTTPS is not affected."
say "This is read-only access to one file, not your SSH keys or the rest of ~/.ssh. Authentication is still separate."
if confirm "Let the agent read ~/.ssh/known_hosts for Git over SSH? [Y/n]" yes; then
  known_hosts=true
fi

shell_target=none
say "Shell integration is a convenient way to keep using the familiar opencode command."
say "Inside a project, opencode starts a sandboxed session."
say "In ~ and /tmp, it runs without the sandbox for system debugging, general questions, and other work outside a project."
say "Use opencode --no-sandbox in any project when you want a normal, unsandboxed session."
say "Management commands such as opencode auth login also run without the sandbox."
say "This adds a shell function that takes precedence over any existing opencode alias or function. Existing shell files are backed up."
if confirm "Use opencode for sandboxed project sessions? [Y/n]" yes; then
  default_shell=bash
  case "${SHELL:-}" in
    zsh|*/zsh) default_shell=zsh ;;
  esac
  shell_target=$default_shell
  if [ "$interactive" = true ]; then
    while true; do
      printf 'Install for bash, zsh, or both? [%s] ' "$default_shell" >&2
      IFS= read -r shell_target <&3 || die "input ended; installation cancelled"
      shell_target=${shell_target:-$default_shell}
      case "$shell_target" in
        bash|zsh|both) break ;;
        *) say "please choose bash, zsh, or both" ;;
      esac
    done
  fi
fi

sandbox_awareness=false
say "The Sandbox Awareness plugin explains sandbox limits to the agent and shows a sandboxed label in the terminal."
say "Recommended: it helps the agent understand blocked commands. The OS sandbox works without it."
say "Installs the npm package through OpenCode's plugin CLI and adds it to the global configuration."
if confirm "Install the Sandbox Awareness plugin? [Y/n]" yes; then
  sandbox_awareness=true
fi

if [ "$sandbox_awareness" = true ]; then
  legacy_plugin="${OPENCODE_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode}/plugins/sandbox-awareness"
  [ ! -e "$legacy_plugin" ] || die "local Sandbox Awareness copy found at $legacy_plugin; move it outside plugins/ before retrying to avoid loading both copies"
fi

PM=""
if [ "$platform" = linux ]; then
  for candidate in dnf apt-get zypper pacman; do
    if have "$candidate"; then PM=$candidate; break; fi
  done
fi
[ -z "$PM" ] && have brew && PM=brew

pm_install() {
  case "$PM" in
    dnf) sudo dnf install -y "$@" ;;
    apt-get) sudo apt-get update && sudo apt-get install -y "$@" ;;
    zypper) sudo zypper --non-interactive install "$@" ;;
    pacman) sudo pacman --noconfirm --needed -S "$@" ;;
    brew) brew install "$@" ;;
    *) return 1 ;;
  esac
}

if ! have python3; then
  [ -n "$PM" ] || die "python3 is required, but no supported package manager was found"
  say "installing python3 via $PM"
  pm_install python3 || die "failed to install python3"
fi
if ! have curl && ! have wget; then
  [ -n "$PM" ] || die "curl or wget is required, but no supported package manager was found"
  pm_install curl || pm_install wget || die "failed to install a downloader"
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

latest_nono_version() {
  fetch "https://api.github.com/repos/nolabs-ai/nono/releases/latest" "$work/release.json"
  sed -n 's/.*"tag_name": *"v\([^"]*\)".*/\1/p' "$work/release.json" | head -n 1
}

install_nono() {
  say "installing nono"
  if [ "$platform" = macos ] && [ "$PM" != brew ]; then
    die "install nono first, or install Homebrew so this installer can run brew install nono"
  fi
  [ "$PM" = brew ] || have sudo || die "sudo is required to install packages via ${PM:-none}"
  if [ "$PM" = brew ]; then
    brew install nono && return 0
  fi
  if [ "$PM" = dnf ]; then
    if sudo dnf copr enable -y always-further/nono && sudo dnf install -y nono-cli; then
      return 0
    fi
    warn "COPR install failed, falling back to the release RPM"
  fi
  if [ "$PM" = pacman ]; then
    if have yay; then yay -S --noconfirm nono-ai-bin && return 0; fi
    if have paru; then paru -S --noconfirm nono-ai-bin && return 0; fi
    die "install nono from the AUR and re-run: yay -S nono-ai-bin"
  fi
  local version
  version=$(latest_nono_version) || die "cannot determine the latest nono release"
  case "$PM" in
    apt-get)
      fetch "https://github.com/nolabs-ai/nono/releases/download/v${version}/nono-cli_${version}_${DEB_ARCH}.deb" "$work/nono.deb"
      sudo dpkg -i "$work/nono.deb" && return 0
      ;;
    dnf)
      fetch "https://github.com/nolabs-ai/nono/releases/download/v${version}/nono-cli-${version}-1.${RPM_ARCH}.rpm" "$work/nono.rpm"
      sudo dnf install -y "$work/nono.rpm" && return 0
      ;;
    zypper)
      fetch "https://github.com/nolabs-ai/nono/releases/download/v${version}/nono-cli-${version}-1.${RPM_ARCH}.rpm" "$work/nono.rpm"
      sudo zypper --non-interactive install "$work/nono.rpm" && return 0
      ;;
  esac
  if have cargo && have git; then
    warn "building nono from source; this takes a few minutes"
    git clone --depth 1 https://github.com/lukehinds/nono "$work/nono-src" \
      && (cd "$work/nono-src" && cargo build --release) \
      && mkdir -p "$HOME/.local/bin" \
      && cp "$work/nono-src/target/release/nono" "$HOME/.local/bin/nono" \
      && return 0
  fi
  die "no supported way to install nono; see https://docs.nono.sh/cli/getting_started/installation"
}

if ! have nono && [ ! -x /usr/bin/nono ]; then
  install_nono
fi

files=(launcher.py "$profile")
local_checkout=true
for file in "${files[@]}"; do
  [ -f "$file" ] || local_checkout=false
done
if [ "$local_checkout" = true ]; then
  src=$PWD
  say "installing from local checkout: $src"
else
  src=$work/src
  mkdir -p "$src/config"
  for file in "${files[@]}"; do
    fetch "$REPO/$file" "$src/$file" || die "failed to download $REPO/$file"
  done
fi

mkdir -p "$HOME/.local/bin" "$(dirname "$settings_path")"
install -m 755 "$src/launcher.py" "$HOME/.local/bin/nonocode"
if [ "$sandbox_awareness" = true ]; then
  say "installing Sandbox Awareness via OpenCode"
  "$opencode_bin" plugin add @glaicer/supercode-sandbox-awareness \
    || die "Sandbox Awareness installation failed"
fi

if [ ! -f "$settings_path" ]; then
  install -m 644 "$src/$profile" "$settings_path"
  say "created $settings_path ($platform profile)"
else
  say "$settings_path exists; left untouched"
fi

if [ "$known_hosts" = true ]; then
  python3 - "$settings_path" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
settings = json.loads(path.read_text())
exceptions = settings.setdefault("read_exceptions", [])
known_hosts = "$HOME/.ssh/known_hosts"
if known_hosts not in exceptions:
    exceptions.append(known_hosts)
    path.write_text(json.dumps(settings, indent=2) + "\n")
PY
  say 'enabled read-only access to $HOME/.ssh/known_hosts'
fi

if [ "$shell_target" != none ]; then
  cat > "$work/shell-integration" <<'SH'
# >>> nonocode shell integration >>>
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
# <<< nonocode shell integration <<<
SH
  rc_files=()
  case "$shell_target" in
    bash|both) rc_files+=("$HOME/.bashrc") ;;
  esac
  case "$shell_target" in
    zsh|both) rc_files+=("${ZDOTDIR:-$HOME}/.zshrc") ;;
  esac
  python3 - "$work/shell-integration" "${rc_files[@]}" <<'PY'
import shutil
import sys
from pathlib import Path

block = Path(sys.argv[1]).read_text()
begin, end = block.splitlines()[0], block.splitlines()[-1]
for filename in sys.argv[2:]:
    path = Path(filename)
    text = path.read_text() if path.exists() else ""
    if begin in text:
        before, _, rest = text.partition(begin)
        _, marker, after = rest.partition(end)
        if not marker:
            sys.exit(f"nonocode: incomplete integration block in {path}; fix it before retrying")
        updated = before + block.rstrip("\n") + after
    else:
        if end in text:
            sys.exit(f"nonocode: incomplete integration block in {path}; fix it before retrying")
        updated = text + ("\n" if text and not text.endswith("\n") else "") + block
    if updated == text:
        continue
    backup = path.with_name(path.name + ".nonocode.bak")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
        print(f"nonocode: backed up {path} to {backup}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated)
    print(f"nonocode: installed shell integration in {path}")
PY
  say "open a new shell or source the selected rc file to activate the integration"
fi

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) warn "add ~/.local/bin to PATH: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

say "verifying the full chain (nono sandbox + opencode)"
(cd /tmp && "$HOME/.local/bin/nonocode" --version) \
  || die "verification failed; nonocode is at ~/.local/bin/nonocode but could not run"

say "done. Next:"
echo "  1. opencode auth login    # once, if no model provider is configured yet"
echo "  2. cd your-project && nonocode"
