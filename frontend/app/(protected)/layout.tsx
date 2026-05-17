import { auth } from '@clerk/nextjs/server'
import { redirect } from 'next/navigation'
import { Show, SignInButton, SignUpButton, UserButton } from '@clerk/nextjs'

export default async function ProtectedLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { userId } = await auth()

  if (!userId) {
    redirect('/sign-in')
  }

  return (
    <>
      <header className="sticky top-0 z-40 w-full border-b border-white/8 bg-[#0b0d10]/95 backdrop-blur-md supports-[backdrop-filter]:bg-[#0b0d10]/88">
        <div className="flex min-h-14 w-full items-center justify-between gap-4 px-4 sm:min-h-16 sm:px-6 lg:px-8 xl:px-12">
          <div className="min-w-0">
            <p className="text-base font-semibold tracking-tight text-white sm:text-lg">CONXA</p>
            <p className="text-xs text-zinc-500 sm:text-[13px]">Skills workspace</p>
          </div>
          <div className="flex items-center gap-2">
            <Show when="signed-out">
              <SignInButton />
              <SignUpButton />
            </Show>
            <Show when="signed-in">
              <UserButton />
            </Show>
          </div>
        </div>
      </header>
      {children}
    </>
  )
}
