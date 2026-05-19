import { CreateOrganization } from '@clerk/nextjs'

export default function OnboardingPage() {
  return (
    <div className="flex w-full max-w-md flex-col items-center gap-6 px-4">
      <div className="space-y-1 text-center">
        <h1 className="text-2xl font-semibold text-white">Create your workspace</h1>
        <p className="text-sm text-zinc-400">
          Set up your Conxa organization to start building and publishing plugins.
        </p>
      </div>
      <CreateOrganization afterCreateOrganizationUrl="/dashboard" skipInvitationScreen />
    </div>
  )
}
