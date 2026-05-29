'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { Toaster } from '@/components/ui/sonner'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { PluginWorkflowCompileProvider } from '@/hooks/usePluginWorkflowCompileTracker'

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: false },
        },
      }),
  )

  return (
    <QueryClientProvider client={queryClient}>
      <PluginWorkflowCompileProvider>
        <ErrorBoundary>
          {children}
          <Toaster position="top-right" closeButton richColors expand={false} />
        </ErrorBoundary>
      </PluginWorkflowCompileProvider>
    </QueryClientProvider>
  )
}
