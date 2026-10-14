import { createCn } from "cn/config";

// The theme replaces Tailwind's type scale and adds spacing names of its own, which the merge
// otherwise misreads: `text-cell` beside `text-text-muted` would be taken for a second colour and
// dropped. Every import of "cn", the components shadcn generates among them, resolves to this
// module through the path mapping in tsconfig.json and the alias in vitest.config.ts.
export const cn = createCn({
  extend: {
    theme: {
      text: ["hero", "title", "heading", "body", "cell", "header", "caption"],
      spacing: ["row", "cell", "card", "gutter", "section", "control"],
    },
  },
});
