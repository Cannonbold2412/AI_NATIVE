import { auth } from '@clerk/nextjs/server'
import { redirect } from 'next/navigation'
import { AppChrome } from '@/components/layout/AppChrome'

export default async function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const { userId } = await auth()

  if (!userId) {
    redirect('/sign-in')
  }

  return <AppChrome>{children}</AppChrome>
}
