import type { BadgeTone } from '@/components/ui/badge'
import type {
  BroadcastState,
  LogLevel,
  PaymentMethod,
  PaymentState,
  PlanType,
  PublicationState,
  ServerHealth,
  SubscriptionState,
  TicketState,
  TransactionKind,
  UserState,
} from './types'

/**
 * Every enum in the system gets its Persian label and its colour in ONE
 * place.
 *
 * The colour semantics are shared with the bot and the Mini App on purpose:
 * green settled, amber waiting on someone, red act now, blue informational,
 * grey inert. An operator and a customer looking at the same order must not
 * read two different stories.
 */

export interface LabelMeta {
  fa: string
  tone: BadgeTone
}

export const PAYMENT_STATE: Record<PaymentState, LabelMeta> = {
  awaiting_receipt: { fa: '\u0645\u0646\u062a\u0638\u0631 \u0631\u0633\u06cc\u062f', tone: 'muted' },
  pending_review: { fa: '\u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 \u0628\u0631\u0631\u0633\u06cc', tone: 'warning' },
  approved: { fa: '\u062a\u0623\u06cc\u06cc\u062f \u0634\u062f\u0647', tone: 'success' },
  rejected: { fa: '\u0631\u062f \u0634\u062f\u0647', tone: 'destructive' },
  refunded: { fa: '\u0645\u0633\u062a\u0631\u062f \u0634\u062f\u0647', tone: 'info' },
  expired: { fa: '\u0645\u0646\u0642\u0636\u06cc \u0634\u062f\u0647', tone: 'muted' },
}

export const PAYMENT_METHOD: Record<PaymentMethod, LabelMeta> = {
  wallet: { fa: '\u06a9\u06cc\u0641 \u067e\u0648\u0644', tone: 'info' },
  card: { fa: '\u06a9\u0627\u0631\u062a \u0628\u0647 \u06a9\u0627\u0631\u062a', tone: 'default' },
  crypto: { fa: '\u0631\u0645\u0632\u0627\u0631\u0632', tone: 'default' },
}

export const SUBSCRIPTION_STATE: Record<SubscriptionState, LabelMeta> = {
  pending: { fa: '\u062f\u0631 \u062d\u0627\u0644 \u0622\u0645\u0627\u062f\u0647\u200c\u0633\u0627\u0632\u06cc', tone: 'muted' },
  active: { fa: '\u0641\u0639\u0627\u0644', tone: 'success' },
  expiring: { fa: '\u0631\u0648 \u0628\u0647 \u0627\u062a\u0645\u0627\u0645', tone: 'warning' },
  expired: { fa: '\u0645\u0646\u0642\u0636\u06cc', tone: 'destructive' },
  exhausted: { fa: '\u062d\u062c\u0645 \u062a\u0645\u0627\u0645 \u0634\u062f\u0647', tone: 'destructive' },
  suspended: { fa: '\u062a\u0639\u0644\u06cc\u0642 \u0634\u062f\u0647', tone: 'muted' },
}

export const PLAN_TYPE: Record<PlanType, LabelMeta> = {
  traffic: { fa: '\u062d\u062c\u0645\u06cc', tone: 'info' },
  unlimited: { fa: '\u0646\u0627\u0645\u062d\u062f\u0648\u062f', tone: 'default' },
  duration: { fa: '\u0632\u0645\u0627\u0646\u06cc', tone: 'muted' },
}

export const PUBLICATION_STATE: Record<PublicationState, LabelMeta> = {
  draft: { fa: '\u067e\u06cc\u0634\u200c\u0646\u0648\u06cc\u0633', tone: 'muted' },
  published: { fa: '\u0645\u0646\u062a\u0634\u0631 \u0634\u062f\u0647', tone: 'success' },
  archived: { fa: '\u0628\u0627\u06cc\u06af\u0627\u0646\u06cc', tone: 'outline' },
}

export const USER_STATE: Record<UserState, LabelMeta> = {
  active: { fa: '\u0641\u0639\u0627\u0644', tone: 'success' },
  suspended: { fa: '\u062a\u0639\u0644\u06cc\u0642', tone: 'warning' },
  banned: { fa: '\u0645\u0633\u062f\u0648\u062f', tone: 'destructive' },
}

export const SERVER_HEALTH: Record<ServerHealth, LabelMeta> = {
  healthy: { fa: '\u0633\u0627\u0644\u0645', tone: 'success' },
  degraded: { fa: '\u06a9\u0646\u062f', tone: 'warning' },
  down: { fa: '\u0642\u0637\u0639', tone: 'destructive' },
  unknown: { fa: '\u0646\u0627\u0645\u0634\u062e\u0635', tone: 'muted' },
}

export const TICKET_STATE: Record<TicketState, LabelMeta> = {
  open: { fa: '\u0628\u0627\u0632', tone: 'warning' },
  answered: { fa: '\u067e\u0627\u0633\u062e \u062f\u0627\u062f\u0647 \u0634\u062f\u0647', tone: 'success' },
  waiting_user: { fa: '\u0645\u0646\u062a\u0638\u0631 \u06a9\u0627\u0631\u0628\u0631', tone: 'info' },
  closed: { fa: '\u0628\u0633\u062a\u0647', tone: 'muted' },
}

export const TRANSACTION_KIND: Record<TransactionKind, LabelMeta> = {
  topup: { fa: '\u0634\u0627\u0631\u0698', tone: 'success' },
  purchase: { fa: '\u062e\u0631\u06cc\u062f', tone: 'muted' },
  refund: { fa: '\u0627\u0633\u062a\u0631\u062f\u0627\u062f', tone: 'info' },
  cashback: { fa: '\u06a9\u0634\u0628\u06a9', tone: 'success' },
  referral: { fa: '\u067e\u0627\u062f\u0627\u0634 \u0645\u0639\u0631\u0641\u06cc', tone: 'success' },
  adjustment: { fa: '\u062a\u0639\u062f\u06cc\u0644 \u062f\u0633\u062a\u06cc', tone: 'warning' },
}

export const BROADCAST_STATE: Record<BroadcastState, LabelMeta> = {
  draft: { fa: '\u067e\u06cc\u0634\u200c\u0646\u0648\u06cc\u0633', tone: 'muted' },
  scheduled: { fa: '\u0632\u0645\u0627\u0646\u200c\u0628\u0646\u062f\u06cc \u0634\u062f\u0647', tone: 'info' },
  sending: { fa: '\u062f\u0631 \u062d\u0627\u0644 \u0627\u0631\u0633\u0627\u0644', tone: 'warning' },
  sent: { fa: '\u0627\u0631\u0633\u0627\u0644 \u0634\u062f\u0647', tone: 'success' },
  cancelled: { fa: '\u0644\u063a\u0648 \u0634\u062f\u0647', tone: 'outline' },
  failed: { fa: '\u0646\u0627\u0645\u0648\u0641\u0642', tone: 'destructive' },
}

export const LOG_LEVEL: Record<LogLevel, LabelMeta> = {
  debug: { fa: '\u062f\u06cc\u0628\u0627\u06af', tone: 'outline' },
  info: { fa: '\u0627\u0637\u0644\u0627\u0639', tone: 'info' },
  warning: { fa: '\u0647\u0634\u062f\u0627\u0631', tone: 'warning' },
  error: { fa: '\u062e\u0637\u0627', tone: 'destructive' },
  critical: { fa: '\u0628\u062d\u0631\u0627\u0646\u06cc', tone: 'destructive' },
}

/**
 * SLA colour for a queue that a customer is sitting in.
 *
 * Thresholds come from the promise the FAQ makes: card-to-card review in
 * under thirty minutes. Amber at 30 means the promise is now at risk; red at
 * 120 means it is broken and someone should be told.
 */
export function waitTone(minutes: number): BadgeTone {
  if (minutes >= 120) return 'destructive'
  if (minutes >= 30) return 'warning'
  return 'muted'
}
