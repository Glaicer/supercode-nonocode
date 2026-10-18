import assert from "node:assert/strict";
import { test } from "node:test";
import plugin from "@glaicer/supercode-sandbox-awareness";

test("registers sandbox guidance only for the exact sandboxed marker", async () => {
  const previous = process.env.OPENCODE_SANDBOX_MODE;
  try {
    for (const mode of [undefined, "unsandboxed", "", "true", "sandboxed "]) {
      if (mode === undefined) delete process.env.OPENCODE_SANDBOX_MODE;
      else process.env.OPENCODE_SANDBOX_MODE = mode;
      await plugin.setup({
        session: {
          hook() {
            assert.fail(`unexpected hook for marker ${JSON.stringify(mode)}`);
          },
        },
      });
    }

    process.env.OPENCODE_SANDBOX_MODE = "sandboxed";
    const hooks = [];
    await plugin.setup({
      session: {
        async hook(name, callback) {
          hooks.push({ name, callback });
        },
      },
    });
    assert.equal(hooks.length, 1);
    assert.equal(hooks[0].name, "context");

    for (let request = 0; request < 2; request++) {
      const existing = { type: "text", text: "Existing system instructions" };
      const event = { system: [existing] };
      hooks[0].callback(event);
      assert.equal(event.system.length, 2);
      assert.equal(event.system[0], existing);
      assert.equal(event.system[1].type, "text");
      assert.match(event.system[1].text, /OPENCODE_SANDBOX_MODE=sandboxed/);
      assert.match(event.system[1].text, /question tool/);
      assert.match(event.system[1].text, /do not repeatedly retry/);
      assert.match(event.system[1].text, /Existing OpenCode permission denials/);
    }
  } finally {
    if (previous === undefined) delete process.env.OPENCODE_SANDBOX_MODE;
    else process.env.OPENCODE_SANDBOX_MODE = previous;
  }
});
