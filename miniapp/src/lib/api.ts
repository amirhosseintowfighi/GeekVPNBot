/**
 * The HTTP client.
 *
 * One place that knows how to talk to the backend, so that authentication,
 * error shaping, and Persian error copy are decided once instead of at every
 * call site.
 *
 * Auth: every request carries the raw Telegram initData string in an
 * Authorization header. The backend re-verifies its HMAC signature against the
 * bot token on each request. There is no session cookie and no client-side
 * token to steal, and the browser cannot forge the header because it never
 * has the bot token.
 */

import { getInitData } from './telegram'
import type {
  CouponPreview,
  FaqSection,
  NotificationPreferences,
  PendingPayment,
  ProfileSummary,
  Quote,
  ReferralSummary,
  ServerStatusRow,
  Storefront,
  SubscriptionCard,
  TicketCard,
  TicketMessage,
  WalletSnapshot,
  WalletTransaction,
} from './types'

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? ''

/**
 * An error that already carries copy safe to show a customer.
 *
 * The backend returns a Persian `message_fa` for anything a user caused - a
 * rejected coupon, an insufficient balance. Anything else gets a generic
 * Persian message here, because a raw 500 or a stack trace must never reach
 * the screen.
 */
export class ApiError extends Error {
  readonly status: number
  readonly messageFa: string

  constructor(status: number, messageFa: string) {
    super(`API ${status}: ${messageFa}`)
    this.name = 'ApiError'
    this.status = status
    this.messageFa = messageFa
  }
}

const GENERIC_ERROR =
  '\u0645\u0634\u06a9\u0644\u06cc \u067e\u06cc\u0634 \u0622\u0645\u062f. \u0644\u0637\u0641\u0627\u064b \u062f\u0648\u0628\u0627\u0631\u0647 \u062a\u0644\u0627\u0634 \u06a9\u0646\u06cc\u062f.'

const OFFLINE_ERROR =
  '\u0627\u062a\u0635\u0627\u0644 \u0628\u0647 \u0627\u06cc\u0646\u062a\u0631\u0646\u062a \u0628\u0631\u0642\u0631\u0627\u0631 \u0646\u06cc\u0633\u062a.'

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response

  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        // `tma` is the scheme Telegram documents for Mini App init data.
        Authorization: `tma ${getInitData()}`,
        ...(init.headers ?? {}),
      },
      cache: 'no-store',
    })
  } catch {
    // A network failure is not an API error, and phrasing it as one sends
    // people to support for a problem support cannot fix.
    throw new ApiError(0, OFFLINE_ERROR)
  }

  if (!response.ok) {
    let messageFa = GENERIC_ERROR
    try {
      const body = (await response.json()) as { message_fa?: string }
      if (body.message_fa) messageFa = body.message_fa
    } catch {
      // Body was not JSON. The generic message already covers it.
    }
    throw new ApiError(response.status, messageFa)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

/** Shared SWR fetcher, so every hook gets identical auth and error handling. */
export const fetcher = <T>(path: string): Promise<T> => request<T>(path)

export const api = {
  // -- storefront and checkout -------------------------------------------

  storefront: () => request<Storefront>('/api/miniapp/storefront'),

  quote: (planId: string, couponCode?: string) =>
    post<Quote>('/api/miniapp/quote', { plan_id: planId, coupon_code: couponCode }),

  /**
   * Validates a coupon without committing to anything. Mirrors the bot's
   * `preview_coupon`, which never raises - a bad code is an answer, not an
   * error, and must not blow up the checkout screen.
   */
  previewCoupon: (planId: string, code: string) =>
    post<CouponPreview>('/api/miniapp/coupon/preview', {
      plan_id: planId,
      code,
    }),

  payFromWallet: (planId: string, couponCode?: string) =>
    post<{ subscription_id: string }>('/api/miniapp/checkout/wallet', {
      plan_id: planId,
      coupon_code: couponCode,
    }),

  beginCardPayment: (planId: string, couponCode?: string) =>
    post<PendingPayment>('/api/miniapp/checkout/card', {
      plan_id: planId,
      coupon_code: couponCode,
    }),

  beginCryptoPayment: (planId: string, couponCode?: string) =>
    post<PendingPayment>('/api/miniapp/checkout/crypto', {
      plan_id: planId,
      coupon_code: couponCode,
    }),

  /** Card-to-card receipt. Goes to a human reviewer, not an auto-approver. */
  attachReceipt: (paymentId: string, fileId: string) =>
    post<PendingPayment>(`/api/miniapp/payments/${paymentId}/receipt`, {
      file_id: fileId,
    }),

  attachTxid: (paymentId: string, txid: string) =>
    post<PendingPayment>(`/api/miniapp/payments/${paymentId}/txid`, { txid }),

  pendingPayments: () =>
    request<PendingPayment[]>('/api/miniapp/payments/pending'),

  // -- subscriptions -----------------------------------------------------

  subscriptions: () =>
    request<SubscriptionCard[]>('/api/miniapp/subscriptions'),

  /** Issues a fresh subscription URL and invalidates the old one. */
  rotateLink: (subscriptionId: string) =>
    post<SubscriptionCard>(
      `/api/miniapp/subscriptions/${subscriptionId}/rotate`,
    ),

  renewalOptions: (subscriptionId: string) =>
    request<Storefront>(
      `/api/miniapp/subscriptions/${subscriptionId}/renewal-options`,
    ),

  // -- wallet ------------------------------------------------------------

  wallet: () => request<WalletSnapshot>('/api/miniapp/wallet'),

  walletTransactions: (page: number, pageSize = 10) =>
    request<{ items: WalletTransaction[]; total: number }>(
      `/api/miniapp/wallet/transactions?page=${page}&page_size=${pageSize}`,
    ),

  beginTopup: (amount: number, method: 'card' | 'crypto') =>
    post<PendingPayment>('/api/miniapp/wallet/topup', { amount, method }),

  // -- referral ----------------------------------------------------------

  referral: () => request<ReferralSummary>('/api/miniapp/referral'),

  // -- support -----------------------------------------------------------

  tickets: () => request<TicketCard[]>('/api/miniapp/tickets'),

  ticketMessages: (ticketId: string) =>
    request<TicketMessage[]>(`/api/miniapp/tickets/${ticketId}/messages`),

  openTicket: (topic: string, subject: string, message: string) =>
    post<TicketCard>('/api/miniapp/tickets', { topic, subject, message }),

  replyToTicket: (ticketId: string, message: string) =>
    post<TicketMessage>(`/api/miniapp/tickets/${ticketId}/messages`, {
      message,
    }),

  // -- profile and settings ----------------------------------------------

  profile: () => request<ProfileSummary>('/api/miniapp/profile'),

  updateProfile: (patch: Partial<Pick<ProfileSummary, 'displayName'>>) =>
    post<ProfileSummary>('/api/miniapp/profile', {
      display_name: patch.displayName,
    }),

  preferences: () =>
    request<NotificationPreferences>('/api/miniapp/preferences'),

  savePreferences: (preferences: NotificationPreferences) =>
    post<NotificationPreferences>('/api/miniapp/preferences', preferences),

  // -- static content ----------------------------------------------------

  serverStatus: () => request<ServerStatusRow[]>('/api/miniapp/servers'),

  faq: () => request<FaqSection[]>('/api/miniapp/faq'),
}
