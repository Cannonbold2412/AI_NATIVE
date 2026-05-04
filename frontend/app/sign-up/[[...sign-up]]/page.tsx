import { SignUp } from '@clerk/nextjs'

export default function SignUpPage() {
  return (
    <main className="flex min-h-[calc(100vh-4rem)] items-center justify-center bg-[#0a0c0f] px-4 py-8">
      <SignUp />
    </main>
  )
}
