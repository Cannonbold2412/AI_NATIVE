import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

type Props = {
  children: ReactNode
}

type State = { hasError: boolean; message: string }

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, message: '' }
  }

  static getDerivedStateFromError(err: Error): State {
    return { hasError: true, message: err?.message || 'Unknown error' }
  }

  override componentDidCatch(err: Error, info: ErrorInfo) {
    console.error('ErrorBoundary', err, info.componentStack)
  }

  override render() {
    if (this.state.hasError) {
      return (
        <div className="bg-background text-foreground flex min-h-svh items-center justify-center p-4">
          <Card className="w-full max-w-md">
            <CardHeader>
              <CardTitle>Something went wrong</CardTitle>
              <CardDescription>
                The UI hit an error. Copy the message below or reload. Check the browser console for a stack
                trace.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <pre className="bg-muted/50 text-destructive max-h-32 overflow-auto rounded-md p-3 font-mono text-xs">
                {this.state.message}
              </pre>
              <Button type="button" onClick={() => window.location.reload()}>
                Reload page
              </Button>
            </CardContent>
          </Card>
        </div>
      )
    }
    return this.props.children
  }
}
