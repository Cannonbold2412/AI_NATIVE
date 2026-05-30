import { createContext, useContext } from 'react'
import { cmd } from '@/lib/ipc'

export type Identity = {
  email: string
  name?: string
  user_id?: string
  org_id?: string
  org_name?: string
}

type AuthContextValue = {
  identity: Identity | null
  setIdentity: (identity: Identity | null) => void
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue>({
  identity: null,
  setIdentity: () => {},
  logout: async () => {},
})

export function useAuth() {
  return useContext(AuthContext)
}

export async function performLogout(setIdentity: (i: Identity | null) => void) {
  try {
    await cmd('logout')
  } catch {
    // proceed regardless
  }
  setIdentity(null)
}
