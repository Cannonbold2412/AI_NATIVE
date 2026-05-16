import { PluginDetailPage } from '@/PluginDetailPage'

type Params = Promise<{ id: string }>

export default async function PluginDetailRoute({ params }: { params: Params }) {
  const { id } = await params
  return <PluginDetailPage pluginId={id} />
}
