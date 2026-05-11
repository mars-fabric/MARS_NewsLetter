import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="text-center">
        <h1 className="text-2xl font-semibold text-ink-900">Page not found</h1>
        <p className="mt-2 text-ink-500">The URL you followed doesn’t exist.</p>
        <Link href="/" className="mt-4 inline-block rounded-md bg-brand-600 px-4 py-2 text-white hover:bg-brand-700">
          Back to dashboard
        </Link>
      </div>
    </div>
  );
}
