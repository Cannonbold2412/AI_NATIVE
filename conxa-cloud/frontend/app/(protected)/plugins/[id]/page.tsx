import { PluginVersionsPage } from '@/PluginVersionsPage'

export default async function PluginVersionsRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return <PluginVersionsPage pluginId={id} />
}
