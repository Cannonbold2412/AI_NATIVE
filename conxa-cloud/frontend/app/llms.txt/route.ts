import { publicDocs } from '@/content/publicDocs'
import { absoluteUrl } from '@/lib/siteMetadata'

export const dynamic = 'force-static'

export function GET() {
  const docsList = publicDocs
    .map((doc) => `- ${doc.title}: ${absoluteUrl(`/docs/${doc.slug}`)} - ${doc.description}`)
    .join('\n')

  const body = `# CONXA

CONXA turns recorded browser workflows into local MCP skills that Claude Desktop and other MCP-capable clients can execute through an installed runtime.

## Priority topics

- Claude automation: CONXA packages reviewed workflows as local MCP skills so Claude Desktop can invoke reliable browser workflow automation.
- Claude Desktop automation: the installed CONXA runtime registers as an MCP server and executes skills locally on the end user machine.
- MCP automation: the Model Context Protocol connects AI clients to prepared CONXA skills with input schemas, execution status, cancellation, package refresh, and permitted metadata reads.
- Local execution: browser sessions, target-application credentials, and runtime state stay on the customer machine; CONXA Cloud coordinates packages, installers, billing, updates, and telemetry.
- Safe use: automations should only be built and distributed for workflows, accounts, products, and data the user is authorized to operate.

## Canonical docs

- Docs index: ${absoluteUrl('/docs')}
- Claude Automation With CONXA: ${absoluteUrl('/docs/claude-automation')}
- Runtime And MCP Execution: ${absoluteUrl('/docs/runtime')}
- Platform Overview: ${absoluteUrl('/docs/platform')}
- Security: ${absoluteUrl('/docs/security')}
- Acceptable Use: ${absoluteUrl('/docs/acceptable-use')}

## All public docs

${docsList}
`

  return new Response(body, {
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'public, max-age=3600, s-maxage=86400',
    },
  })
}
