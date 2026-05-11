export default function Loading() {
  return (
    <div className="flex min-h-screen items-center justify-center text-ink-500">
      <div className="flex items-center gap-3">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
        <span>Loading…</span>
      </div>
    </div>
  );
}
