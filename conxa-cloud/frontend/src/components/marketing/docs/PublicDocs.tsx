import Link from 'next/link'
import {
  PUBLIC_DOCS_LAST_MODIFIED,
  publicDocs,
  publicDocCategories,
  getPublicDoc,
  getPublicDocsByCategory,
  type PublicDocBlock,
  type PublicDocPage,
} from '@/content/publicDocs'
import { SITE_NAME, absoluteUrl, sitePublisher } from '@/lib/siteMetadata'

function docHref(slug: string) {
  return `/docs/${slug}`
}

function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(data).replace(/</g, '\\u003c'),
      }}
    />
  )
}

function docsIndexStructuredData() {
  return {
    '@context': 'https://schema.org',
    '@type': 'CollectionPage',
    name: 'CONXA docs',
    url: absoluteUrl('/docs'),
    description:
      'Public CONXA documentation for Claude Desktop automation, MCP, local execution, security, privacy, billing, and support.',
    publisher: sitePublisher,
    hasPart: publicDocs.map((doc) => ({
      '@type': 'TechArticle',
      headline: doc.title,
      description: doc.description,
      url: absoluteUrl(docHref(doc.slug)),
      isPartOf: {
        '@type': 'WebSite',
        name: SITE_NAME,
        url: absoluteUrl('/'),
      },
    })),
  }
}

function docStructuredData(doc: PublicDocPage) {
  const url = absoluteUrl(docHref(doc.slug))

  return {
    '@context': 'https://schema.org',
    '@type': 'TechArticle',
    headline: doc.title,
    description: doc.description,
    url,
    mainEntityOfPage: url,
    dateModified: PUBLIC_DOCS_LAST_MODIFIED,
    publisher: sitePublisher,
    isPartOf: {
      '@type': 'WebSite',
      name: SITE_NAME,
      url: absoluteUrl('/'),
    },
  }
}

function SectionLinkList({ doc }: { doc: PublicDocPage }) {
  return (
    <div className="rounded-md border border-white/8 bg-white/[0.025] p-3">
      <p className="text-[11px] font-semibold uppercase tracking-normal text-zinc-500">
        On this page
      </p>
      <div className="mt-2 flex flex-col gap-1">
        {doc.sections.map((section) => (
          <a
            key={section.id}
            href={`#${section.id}`}
            className="rounded-md px-2 py-1.5 text-sm text-zinc-400 transition-colors hover:bg-white/[0.04] hover:text-white"
          >
            {section.title}
          </a>
        ))}
      </div>
    </div>
  )
}

function DocsSidebar({ currentSlug }: { currentSlug?: string }) {
  return (
    <aside className="hidden w-72 shrink-0 lg:block">
      <div className="sticky top-24 flex max-h-[calc(100vh-7rem)] flex-col gap-3 overflow-y-auto pr-2">
        <Link
          href="/docs"
          className={`rounded-md border px-3 py-2 text-sm transition-colors ${
            currentSlug
              ? 'border-white/8 bg-white/[0.025] text-zinc-300 hover:bg-white/[0.04] hover:text-white'
              : 'border-cyan-400/30 bg-cyan-400/10 text-cyan-200'
          }`}
        >
          Docs home
        </Link>
        {publicDocCategories.map((category) => (
          <div key={category.id} className="rounded-md border border-white/8 bg-white/[0.025] p-3">
            <p className="text-[11px] font-semibold uppercase tracking-normal text-zinc-500">
              {category.title}
            </p>
            <div className="mt-2 flex flex-col gap-1">
              {getPublicDocsByCategory(category).map((doc) => {
                const active = doc.slug === currentSlug
                return (
                  <Link
                    key={doc.slug}
                    href={docHref(doc.slug)}
                    className={`rounded-md px-2 py-1.5 text-sm transition-colors ${
                      active
                        ? 'bg-cyan-400/10 text-cyan-200'
                        : 'text-zinc-400 hover:bg-white/[0.04] hover:text-white'
                    }`}
                  >
                    {doc.title}
                  </Link>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}

function MobileDocsNav({ currentDoc }: { currentDoc?: PublicDocPage }) {
  return (
    <div className="lg:hidden">
      <details className="rounded-md border border-white/8 bg-white/[0.025]">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-white">
          Browse docs
        </summary>
        <div className="border-t border-white/8 px-4 py-3">
          <Link
            href="/docs"
            className="block rounded-md px-2 py-2 text-sm text-zinc-300 hover:bg-white/[0.04] hover:text-white"
          >
            Docs home
          </Link>
          {publicDocCategories.map((category) => (
            <div key={category.id} className="mt-4">
              <p className="px-2 text-[11px] font-semibold uppercase tracking-normal text-zinc-500">
                {category.title}
              </p>
              <div className="mt-1">
                {getPublicDocsByCategory(category).map((doc) => (
                  <Link
                    key={doc.slug}
                    href={docHref(doc.slug)}
                    className={`block rounded-md px-2 py-2 text-sm ${
                      currentDoc?.slug === doc.slug
                        ? 'bg-cyan-400/10 text-cyan-200'
                        : 'text-zinc-400 hover:bg-white/[0.04] hover:text-white'
                    }`}
                  >
                    {doc.title}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      </details>
      {currentDoc ? (
        <details className="mt-3 rounded-md border border-white/8 bg-white/[0.025]">
          <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-white">
            Page sections
          </summary>
          <div className="border-t border-white/8 px-4 py-3">
            {currentDoc.sections.map((section) => (
              <a
                key={section.id}
                href={`#${section.id}`}
                className="block rounded-md px-2 py-2 text-sm text-zinc-400 hover:bg-white/[0.04] hover:text-white"
              >
                {section.title}
              </a>
            ))}
          </div>
        </details>
      ) : null}
    </div>
  )
}

function BlockRenderer({ block }: { block: PublicDocBlock }) {
  if (block.type === 'paragraphs') {
    return (
      <div className="space-y-4">
        {block.items.map((item) => (
          <p key={item} className="text-[15px] leading-7 text-zinc-300">
            {item}
          </p>
        ))}
      </div>
    )
  }

  if (block.type === 'bullets' || block.type === 'numbered') {
    const ListTag = block.type === 'numbered' ? 'ol' : 'ul'
    return (
      <ListTag
        className={`space-y-2 text-[15px] leading-7 text-zinc-300 ${
          block.type === 'numbered' ? 'list-decimal pl-5' : 'list-disc pl-5'
        }`}
      >
        {block.items.map((item) => (
          <li key={item} className="pl-1">
            {item}
          </li>
        ))}
      </ListTag>
    )
  }

  if (block.type === 'callout') {
    return (
      <div className="rounded-md border border-cyan-400/25 bg-cyan-400/[0.06] p-4">
        <p className="text-sm font-semibold text-cyan-200">{block.title}</p>
        <p className="mt-2 text-sm leading-6 text-zinc-300">{block.body}</p>
      </div>
    )
  }

  if (block.type === 'links') {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {block.items.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="rounded-md border border-white/8 bg-white/[0.025] p-4 transition-colors hover:border-cyan-400/30 hover:bg-white/[0.04]"
          >
            <p className="text-sm font-semibold text-white">{item.label}</p>
            <p className="mt-2 text-sm leading-6 text-zinc-400">{item.description}</p>
          </Link>
        ))}
      </div>
    )
  }

  if (block.type === 'table') {
    return (
      <div className="overflow-hidden rounded-md border border-white/8">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse text-left text-sm">
            <thead className="bg-white/[0.04]">
              <tr>
                {block.columns.map((column) => (
                  <th
                    key={column}
                    className="border-b border-white/8 px-4 py-3 font-medium text-zinc-200"
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr
                  key={row.join('|')}
                  className={rowIndex % 2 === 0 ? 'bg-black/10' : 'bg-white/[0.015]'}
                >
                  {row.map((cell, cellIndex) => (
                    <td
                      key={`${rowIndex}-${cellIndex}`}
                      className="border-b border-white/8 px-4 py-3 align-top leading-6 text-zinc-300 last:border-b-0"
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  return null
}

function RelatedDocs({ doc }: { doc: PublicDocPage }) {
  const related = (doc.relatedSlugs ?? [])
    .map((slug) => getPublicDoc(slug))
    .filter((item): item is PublicDocPage => Boolean(item))

  if (!related.length) return null

  return (
    <section className="border-t border-white/8 pt-8">
      <h2 className="text-lg font-semibold text-white">Related docs</h2>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {related.map((item) => (
          <Link
            key={item.slug}
            href={docHref(item.slug)}
            className="rounded-md border border-white/8 bg-white/[0.025] p-4 transition-colors hover:border-cyan-400/30 hover:bg-white/[0.04]"
          >
            <p className="text-sm font-semibold text-white">{item.title}</p>
            <p className="mt-2 line-clamp-3 text-sm leading-6 text-zinc-400">{item.description}</p>
          </Link>
        ))}
      </div>
    </section>
  )
}

function ReferenceLinks({ doc }: { doc: PublicDocPage }) {
  if (!doc.references?.length) return null

  return (
    <section className="border-t border-white/8 pt-8">
      <h2 className="text-lg font-semibold text-white">Drafting references</h2>
      <p className="mt-2 text-sm leading-6 text-zinc-500">
        These public resources informed the policy structure. They are not a substitute for legal
        review.
      </p>
      <div className="mt-4 flex flex-col gap-2">
        {doc.references.map((reference) => (
          <Link
            key={reference.href}
            href={reference.href}
            className="text-sm text-cyan-300 underline-offset-4 hover:underline"
          >
            {reference.label}
          </Link>
        ))}
      </div>
    </section>
  )
}

export function DocsIndex() {
  return (
    <>
      <JsonLd data={docsIndexStructuredData()} />
      <div className="min-h-screen bg-[#06080b] px-6 pb-20 pt-28">
        <div className="mx-auto flex max-w-7xl gap-8">
          <DocsSidebar />
          <div className="min-w-0 flex-1">
            <MobileDocsNav />
            <header className="max-w-3xl">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
                CONXA docs
              </p>
              <h1 className="mt-4 text-4xl font-semibold tracking-normal text-white sm:text-5xl">
                Public product, trust, legal, billing, and support docs.
              </h1>
              <p className="mt-5 text-base leading-7 text-zinc-400">
                Customer-facing documentation for Claude Desktop automation, MCP, local browser
                workflow execution, data movement, and the policies that govern use of the
                platform.
              </p>
            </header>

            <div className="mt-10 grid gap-5">
              {publicDocCategories.map((category) => (
                <section key={category.id} className="border-t border-white/8 pt-6">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                      <h2 className="text-xl font-semibold text-white">{category.title}</h2>
                      <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-500">
                        {category.description}
                      </p>
                    </div>
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {getPublicDocsByCategory(category).map((doc) => (
                      <Link
                        key={doc.slug}
                        href={docHref(doc.slug)}
                        className="rounded-md border border-white/8 bg-white/[0.025] p-4 transition-colors hover:border-cyan-400/30 hover:bg-white/[0.04]"
                      >
                        <p className="text-xs font-semibold uppercase tracking-normal text-cyan-300">
                          {doc.eyebrow}
                        </p>
                        <h3 className="mt-2 text-base font-semibold text-white">{doc.title}</h3>
                        <p className="mt-2 text-sm leading-6 text-zinc-400">{doc.description}</p>
                        <p className="mt-4 text-xs text-zinc-600">
                          Updated {doc.lastUpdated} - {doc.readingTime}
                        </p>
                      </Link>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

export function DocsPage({ doc }: { doc: PublicDocPage }) {
  return (
    <>
      <JsonLd data={docStructuredData(doc)} />
      <div className="min-h-screen bg-[#06080b] px-6 pb-20 pt-28">
        <div className="mx-auto flex max-w-7xl gap-8">
          <DocsSidebar currentSlug={doc.slug} />
          <article className="min-w-0 flex-1">
            <MobileDocsNav currentDoc={doc} />
            <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_15rem]">
              <div className="min-w-0">
                <header className="max-w-3xl">
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
                    {doc.eyebrow}
                  </p>
                  <h1 className="mt-4 text-4xl font-semibold tracking-normal text-white sm:text-5xl">
                    {doc.title}
                  </h1>
                  <p className="mt-5 text-base leading-7 text-zinc-400">{doc.description}</p>
                  <div className="mt-5 flex flex-wrap gap-2 text-xs text-zinc-600">
                    <span className="rounded-full border border-white/8 px-3 py-1">
                      Updated {doc.lastUpdated}
                    </span>
                    <span className="rounded-full border border-white/8 px-3 py-1">
                      {doc.readingTime}
                    </span>
                  </div>
                </header>

                <section className="mt-8 rounded-md border border-white/8 bg-white/[0.025] p-5">
                  <h2 className="text-sm font-semibold uppercase tracking-normal text-zinc-500">
                    Summary
                  </h2>
                  <ul className="mt-4 space-y-2 text-sm leading-6 text-zinc-300">
                    {doc.summary.map((item) => (
                      <li key={item} className="flex gap-3">
                        <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-300" />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </section>

                <div className="mt-10 space-y-12">
                  {doc.sections.map((section) => (
                    <section key={section.id} id={section.id} className="scroll-mt-28">
                      <h2 className="text-2xl font-semibold tracking-normal text-white">
                        {section.title}
                      </h2>
                      {section.intro ? (
                        <p className="mt-3 text-[15px] leading-7 text-zinc-400">
                          {section.intro}
                        </p>
                      ) : null}
                      <div className="mt-5 space-y-5">
                        {section.blocks.map((block, index) => (
                          <BlockRenderer key={`${section.id}-${index}`} block={block} />
                        ))}
                      </div>
                    </section>
                  ))}
                  <ReferenceLinks doc={doc} />
                  <RelatedDocs doc={doc} />
                </div>
              </div>
              <div className="hidden xl:block">
                <div className="sticky top-24">
                  <SectionLinkList doc={doc} />
                </div>
              </div>
            </div>
          </article>
        </div>
      </div>
    </>
  )
}
