import { PluginWorkflowCompilePage } from '@/PluginWorkflowCompilePage'

type Params = Promise<{ id: string; workflowId: string }>
type SearchParams = Promise<{ start?: string; mode?: string }>

export default async function PluginWorkflowCompileRoute({
  params,
  searchParams,
}: {
  params: Params
  searchParams: SearchParams
}) {
  const { id, workflowId } = await params
  const sp = await searchParams
  return (
    <PluginWorkflowCompilePage
      pluginId={id}
      workflowId={workflowId}
      initialMode={sp.mode === 'recompile' ? 'recompile' : 'compile'}
      autoStart={sp.start === '1'}
    />
  )
}
