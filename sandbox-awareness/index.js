const instruction = `You are running inside a filesystem sandbox (OPENCODE_SANDBOX_MODE=sandboxed).
Installed programs such as Git can run; sandboxing does not mean they are unavailable. Network access is allowed, but credentials or service access may be restricted.
Writes are limited to the launch project, configured temporary directories, and OpenCode's own runtime directories. Other paths are read-only or inaccessible; some credential, browser, and shell-configuration paths cannot be read. Existing OpenCode permission denials still apply, including the Git restrictions.
If a required operation is outside these limits or fails because of sandbox permissions, do not repeatedly retry it, escalate privileges, weaken permissions, or use an external process/service to bypass the sandbox.
Use the question tool to ask the user to perform the operation manually outside the sandbox. Explain the limitation, provide the exact command and working directory (or manual steps), and describe any destructive effects. Wait for the user's result before continuing. If the question tool is unavailable, state the blocker and manual steps in your response. Distinguish sandbox permission failures from missing programs, authentication failures, and ordinary command errors.`;

export default {
  id: "sandbox-awareness",
  async setup(ctx) {
    if (process.env.OPENCODE_SANDBOX_MODE !== "sandboxed") return;
    await ctx.session.hook("context", (event) => {
      event.system.push({ type: "text", text: instruction });
    });
  },
};
