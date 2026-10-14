import type { ReactNode } from "react";

type NotFoundProps = Readonly<{
  isin: string;
  action?: ReactNode;
}>;

export function NotFound({ isin, action }: NotFoundProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
      <h1 className="text-heading text-text">
        No instrument with ISIN <span className="font-mono">{isin}</span>
      </h1>
      <p className="max-w-[420px] text-cell leading-normal text-text-muted">
        A split or consolidation issues a new ISIN, so an address saved before
        one may name the predecessor.
      </p>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
