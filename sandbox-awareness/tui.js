import { Plugin } from "@opencode/plugin/tui";
import { createElement, effect, insert, setProp } from "@opentui/solid";

export default Plugin.define({
  id: "sandbox-awareness.tui",
  setup(context) {
    if (process.env.OPENCODE_SANDBOX_MODE !== "sandboxed") return;
    const render = () => {
      const text = createElement("text");
      setProp(text, "wrapMode", "none");
      setProp(text, "flexShrink", 0);
      insert(text, "sandboxed");
      effect(() => setProp(text, "fg", context.theme.text.muted));
      return text;
    };
    context.ui.slot({ append: "prompt.footer.status", render });
    context.ui.slot({ append: "home.footer.status", render });
  },
});
