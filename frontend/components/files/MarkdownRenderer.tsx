'use client';

import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { useMemo } from 'react';

marked.setOptions({ gfm: true, breaks: true });

export function MarkdownRenderer({ source, className = '' }: { source: string; className?: string }) {
  const html = useMemo(() => {
    try {
      const raw = marked.parse(source ?? '', { async: false }) as string;
      if (typeof window === 'undefined') return raw;
      return DOMPurify.sanitize(raw, { ADD_ATTR: ['target', 'rel'] });
    } catch (err) {
      return `<pre>${String(err)}</pre>`;
    }
  }, [source]);

  return (
    <article
      className={`prose prose-sm max-w-none prose-headings:text-ink-900 prose-a:text-brand-600 prose-a:no-underline hover:prose-a:underline ${className}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
