// Where the setup stands: creating the first admin, the step the installation offers.
export function SetupSteps() {
  return (
    <div className="flex items-center gap-6">
      <span className="text-cell text-text-muted">Setting up</span>
      <span className="inline-flex items-center gap-2 text-cell font-medium text-text">
        <span
          aria-hidden="true"
          className="inline-flex size-5 items-center justify-center rounded-full bg-text text-caption font-semibold text-surface"
        >
          1
        </span>
        Create the admin
      </span>
    </div>
  );
}
