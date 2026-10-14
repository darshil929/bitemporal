import type { ReactNode } from "react";

type EmptyStateProps = Readonly<{
  title: string;
  text: string;
  action?: ReactNode;
}>;

export function EmptyState({ title, text, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <p className="text-body font-semibold text-text">{title}</p>
      <p className="max-w-[460px] text-cell leading-normal text-text-muted">
        {text}
      </p>
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
