export type Frame =
  | { kind: 'navigate'; tab: string; url: string; dwell: number }
  | { kind: 'move'; to: { x: number; y: number }; duration: number }
  | { kind: 'click'; target: string; ripple?: boolean; dwell?: number }
  | { kind: 'type'; target: string; text: string; dwell?: number }
  | { kind: 'check'; target: string; dwell?: number }
  | { kind: 'upload'; target: string; file: string; dwell?: number }
  | { kind: 'toast'; message: string; tone: 'success' | 'info'; dwell?: number }
  | { kind: 'scroll'; amount: number; dwell?: number }
  | { kind: 'wait'; dwell: number }

export const EXECUTION_SCRIPT: Frame[] = [
  { kind: 'wait', dwell: 1200 },
  { kind: 'navigate', tab: 'HR Portal', url: 'hr.acmecorp.internal', dwell: 800 },
  { kind: 'move', to: { x: 52, y: 38 }, duration: 600 },
  { kind: 'click', target: 'Employees', ripple: true, dwell: 500 },
  { kind: 'move', to: { x: 68, y: 56 }, duration: 500 },
  { kind: 'click', target: '+ Add Employee', ripple: true, dwell: 400 },
  { kind: 'move', to: { x: 40, y: 42 }, duration: 700 },
  { kind: 'type', target: 'First name', text: 'Priya', dwell: 300 },
  { kind: 'move', to: { x: 65, y: 42 }, duration: 400 },
  { kind: 'type', target: 'Last name', text: 'Shah', dwell: 300 },
  { kind: 'move', to: { x: 40, y: 56 }, duration: 500 },
  { kind: 'type', target: 'Email', text: 'priya.shah@acmecorp.com', dwell: 400 },
  { kind: 'move', to: { x: 65, y: 56 }, duration: 400 },
  { kind: 'type', target: 'Department', text: 'Product', dwell: 300 },
  { kind: 'move', to: { x: 40, y: 70 }, duration: 500 },
  { kind: 'type', target: 'Start date', text: '2025-01-20', dwell: 300 },
  { kind: 'move', to: { x: 75, y: 84 }, duration: 600 },
  { kind: 'click', target: 'Save Employee', ripple: true, dwell: 600 },
  { kind: 'check', target: 'Employee created', dwell: 500 },
  { kind: 'navigate', tab: 'Access Control', url: 'access.acmecorp.internal', dwell: 700 },
  { kind: 'move', to: { x: 48, y: 35 }, duration: 600 },
  { kind: 'click', target: 'Role Assignment', ripple: true, dwell: 400 },
  { kind: 'move', to: { x: 55, y: 52 }, duration: 500 },
  { kind: 'type', target: 'Search user', text: 'priya.shah', dwell: 400 },
  { kind: 'move', to: { x: 55, y: 62 }, duration: 300 },
  { kind: 'click', target: 'Priya Shah', ripple: true, dwell: 400 },
  { kind: 'move', to: { x: 45, y: 74 }, duration: 400 },
  { kind: 'click', target: 'Product Contributor', ripple: true, dwell: 300 },
  { kind: 'move', to: { x: 65, y: 74 }, duration: 300 },
  { kind: 'click', target: 'Jira Access', ripple: true, dwell: 300 },
  { kind: 'move', to: { x: 75, y: 86 }, duration: 500 },
  { kind: 'click', target: 'Apply Permissions', ripple: true, dwell: 600 },
  { kind: 'check', target: 'Permissions applied', dwell: 500 },
  { kind: 'navigate', tab: 'Onboarding Docs', url: 'docs.acmecorp.internal/onboarding', dwell: 700 },
  { kind: 'move', to: { x: 55, y: 45 }, duration: 600 },
  { kind: 'click', target: 'Upload documents', ripple: true, dwell: 400 },
  { kind: 'upload', target: 'Drop files', file: 'employment_contract.pdf', dwell: 800 },
  { kind: 'upload', target: 'Drop files', file: 'ndа_agreement.pdf', dwell: 600 },
  { kind: 'move', to: { x: 70, y: 80 }, duration: 500 },
  { kind: 'click', target: 'Send Welcome Email', ripple: true, dwell: 600 },
  { kind: 'toast', message: 'Onboarding complete for Priya Shah', tone: 'success', dwell: 1500 },
  { kind: 'wait', dwell: 800 },
]

export const CHAT_STEPS = [
  { role: 'user' as const, text: 'Prepare onboarding for the new employee.' },
  { role: 'assistant' as const, text: 'Starting onboarding for Priya Shah…', delay: 1600 },
  { role: 'tool' as const, text: 'Open HR Portal', icon: '🌐', delay: 2800 },
  { role: 'tool' as const, text: 'Create employee record', icon: '👤', delay: 7000 },
  { role: 'tool' as const, text: 'Assign access permissions', icon: '🔐', delay: 14000 },
  { role: 'tool' as const, text: 'Upload onboarding documents', icon: '📄', delay: 20000 },
  { role: 'tool' as const, text: 'Send welcome email', icon: '✉️', delay: 26000 },
  { role: 'assistant' as const, text: 'Onboarding complete. Priya has full access and received her welcome email.', delay: 29000 },
]
