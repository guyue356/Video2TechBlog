"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

export default function MarkdownRenderer({ content }: { content: string }) {
  return (
    <article className="prose prose-zinc max-w-none
      prose-headings:text-zinc-900 prose-headings:font-semibold
      prose-h1:text-2xl prose-h2:text-xl prose-h3:text-lg
      prose-p:text-zinc-700 prose-p:leading-relaxed
      prose-code:text-blue-600 prose-code:text-sm
      prose-pre:bg-zinc-50 prose-pre:border prose-pre:border-zinc-200
      prose-a:text-blue-600 prose-a:no-underline hover:prose-a:underline
      prose-li:text-zinc-700
      prose-strong:text-zinc-800
      prose-blockquote:border-blue-500 prose-blockquote:text-zinc-500
      prose-table:border-zinc-300
      prose-th:text-zinc-700 prose-th:bg-zinc-100
      prose-td:text-zinc-600 prose-td:border-zinc-200
    ">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
      >
        {content}
      </ReactMarkdown>
    </article>
  );
}
