import { SignIn } from '@clerk/nextjs'

export default function SignInPage() {
  return (
    <main className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-[#0a0c0f] px-4 py-8">
      <SignIn />
    </main>
  )
}
