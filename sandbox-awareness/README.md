# Sandbox Awareness

[![npm](https://img.shields.io/npm/v/@glaicer/supercode-sandbox-awareness)](https://www.npmjs.com/package/@glaicer/supercode-sandbox-awareness)

Sandbox guidance for OpenCode agents, with a `sandboxed` indicator in the terminal UI.

**This plugin does not create or enforce a sandbox.** It reads an environment marker set by your sandbox launcher. Use it only with a sandbox whose restrictions match the guidance below, such as nonocode.

## Requirements

- OpenCode V2, version **2.0.28 or newer** within the V2 release line.
- A launcher that sets `OPENCODE_SANDBOX_MODE=sandboxed` for both the OpenCode server and terminal UI running inside the sandbox.

No build step, runtime dependency installation, API key, or model configuration is needed.

## Install

```sh
opencode plugin add @glaicer/supercode-sandbox-awareness
```

Alternatively, merge this entry into the `plugins` array in `~/.config/opencode/opencode.jsonc`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": ["@glaicer/supercode-sandbox-awareness"],
}
```

Keep your existing configuration and other plugin entries. Registering the server entry also makes the TUI entry discoverable; no separate `cli.json` entry is required.

If nonocode already installed a local copy in `~/.config/opencode/plugins/sandbox-awareness/`, use either that copy or the npm package, not both.

After changing the configuration, restart the OpenCode server through your sandbox launcher. Make sure the launcher sets `OPENCODE_SANDBOX_MODE=sandboxed` for both the server and terminal UI. Setting the marker only on a terminal connected to an already-running unsandboxed server does not enable server-side guidance.

## Behavior

With the exact marker `OPENCODE_SANDBOX_MODE=sandboxed`:

- **Agent guidance:** The plugin adds sandbox instructions to every model request in the agent loop, including requests after compaction, through the session `context` hook.
- **Terminal status:** It adds a muted `sandboxed` label to the prompt and home footers, preserving the built-in status indicators.

If the marker is missing or has any value other than `sandboxed`, the plugin adds neither agent guidance nor a terminal label.

The guidance tells the agent that:

- Installed programs such as Git can still run; sandboxing is not the same as a missing executable.
- Writes are limited to the launch project, configured temporary directories, and OpenCode's runtime directories. Other paths may be read-only or inaccessible.
- Network access is allowed, but credentials, services, browser data, and shell configuration may be restricted.
- Existing OpenCode permission denials still apply.
- A sandbox denial is not a reason to retry repeatedly, escalate privileges, weaken restrictions, or bypass the sandbox through another process or service.
- When blocked, the agent should use the `question` tool to ask the user to perform the operation outside the sandbox. It should supply the command, working directory, and any destructive effects. If the tool is unavailable, it should explain the blocker and manual steps in its response.

## Security boundaries

The environment marker is a declaration, not proof that sandboxing is active. Setting it manually does not restrict filesystem access or make commands safe.

The plugin does not detect your sandbox policy, change OpenCode permissions, approve commands, block tools, or enforce the model's compliance with its instructions. Enforcement belongs to your sandbox launcher and operating system. Do not enable the marker when the described restrictions are inaccurate.

## Development

The plugin is plain JavaScript. Its TUI imports are provided by the OpenCode host.

From this directory, using Node.js 24 or newer:

```sh
npm run check
npm test
npm pack --dry-run
```

No `npm install` or build is needed. The package exposes `.` and `./server` as `index.js`, and `./tui` as `tui.js`. Only these two runtime files, the package manifest, README, and license are published. Packing runs the syntax checks and tests automatically.

## License

MIT. See [LICENSE](./LICENSE).
