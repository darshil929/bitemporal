import { RotateCw, TriangleAlert } from "lucide-react";

import { Button } from "@/components/controls/Button";

type ErrorStateProps = Readonly<{
  title: string;
  text: string;
  onRetry: () => void;
}>;

// Says what failed and what the failure leaves unaffected.
export function ErrorState({ title, text, onRetry }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-2 px-6 py-10 text-center"
    >
      <TriangleAlert aria-hidden="true" className="size-5 text-flag" />
      <p className="text-body font-semibold text-text">{title}</p>
      <p className="max-w-[460px] text-cell leading-normal text-text-muted">
        {text}
      </p>
      <div className="mt-2">
        <Button onClick={onRetry}>
          <RotateCw aria-hidden="true" />
          Retry
        </Button>
      </div>
    </div>
  );
}
