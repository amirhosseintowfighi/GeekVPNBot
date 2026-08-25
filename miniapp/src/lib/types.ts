/**
 * The data contract with the backend.
 *
 * These types mirror `application/bot/read_models.py` one-for-one. They are
 * hand-written rather than generated because the bot's read models are the
 * source of truth and are stable; a generator would add a build step for a
 * contract that changes once a phase.
 *
 * Money is always an integer count of tomans - never a float. Rial/toman
 * amounts routinely exceed the range where float arithmetic is exact, and a
 * rounding error in a wallet balance is not a cosmetic bug.
 *
 * Timestamps arrive as ISO-8601 strings and are parsed at the edge, so no
 * component ever has to wonder whether it holds a string or a Date.
 */

export type SubscriptionState =
  | 'active'
  | 'expiring'
  | 'expired'
  | 'exhausted'
  | 'suspended'
  | 'pending'

export type PlanType = 'traffic' | 'unlimited' | 'duration'

export type TransactionKind =
  | 'topup'
  | 'purchase'
  | 'cashback'
  | 'referral'
  | 'refund'
  | 'adjustment'

// `gateway` is in the read model and no gateway is registered yet, so nothing
// can send it today. Listed anyway: the union's job is to describe what the
// API *can* say, and the day one is registered is not the day to discover a
// lookup returning undefined.
export type PaymentMethod = 'wallet' | 'card' | 'crypto' | 'gateway'

/**
 * Card-to-card and crypto both settle through a human review step today, so
 * `pending_review` is a first-class state rather than a transient one. The
 * gateway that will eventually confirm instantly slots in as another method
 * without adding a state.
 */
export type PaymentState =
  | 'draft'
  | 'awaiting_proof'
  | 'pending_review'
  | 'approved'
  | 'rejected'
  | 'expired'

export type ServerHealth = 'healthy' | 'degraded' | 'down' | 'maintenance'

/**
 * Mirrors `TicketState` in `application/bot/read_models.py`.
 *
 * `waiting` was missing - the state a ticket enters the moment an agent
 * replies. `STATE_META[ticket.state]` was then undefined and the next line
 * read `.variant` off it, so the support page threw as soon as any ticket had
 * ever been answered.
 */
export type TicketState = 'open' | 'answered' | 'waiting' | 'closed'

export type LoyaltyTier = 'bronze' | 'silver' | 'gold' | 'diamond'

export interface SubscriptionCard {
  subscriptionId: string
  planId: string
  productNameFa: string
  planNameFa: string
  state: SubscriptionState
  /** `null` on unlimited packages, where there is no ceiling to draw. */
  quotaGib: number | null
  usedGib: number
  deviceLimit: number
  expiresAt: string | null
  subscriptionUrl: string | null
}

export interface PlanCard {
  planId: string
  productId: string
  nameFa: string
  planType: PlanType
  durationDays: number
  price: number
  /** Struck-through price. Only present where a real discount exists. */
  compareAtPrice: number | null
  quotaGib: number | null
  dailyQuotaGib: number | null
  deviceLimit: number
  badgeFa: string | null
  isFeatured: boolean
  descriptionFa: string | null
}

export interface ProductCard {
  productId: string
  categoryId: string
  nameFa: string
  taglineFa: string | null
  descriptionFa: string | null
  featuresFa: string[]
  icon: string | null
  badgeFa: string | null
  isFeatured: boolean
  plans: PlanCard[]
}

export interface CategoryCard {
  categoryId: string
  nameFa: string
  icon: string | null
  products: ProductCard[]
}

export interface Storefront {
  categories: CategoryCard[]
  walletBalance: number
  loyaltyTier: LoyaltyTier
  isFirstPurchase: boolean
}

/** One line of the price breakdown. Mirrors `PriceLineKind`. */
export interface PriceLine {
  kind:
    | 'base'
    | 'campaign'
    | 'coupon'
    | 'loyalty'
    | 'rounding'
    | 'total'
    | 'cashback'
    | 'referral'
  labelFa: string
  amount: number
}

export interface Quote {
  planId: string
  subtotal: number
  total: number
  lines: PriceLine[]
  /**
   * Disclosed, but NOT subtracted from `total`. Cashback lands in the wallet
   * after the purchase settles. Rendering it as a discount would overstate
   * the saving and produce a total that does not match what is charged.
   */
  cashbackAmount: number
  appliedCouponCode: string | null
  campaignNameFa: string | null
  /** Unix seconds. Present only for flash sales. */
  expiresAt: number | null
}

export interface CouponPreview {
  accepted: boolean
  messageFa: string
  quote: Quote | null
}

export interface WalletSnapshot {
  balance: number
  lifetimeSpend: number
  tier: LoyaltyTier
}

export interface WalletTransaction {
  transactionId: string
  kind: TransactionKind
  amount: number
  descriptionFa: string | null
  createdAt: string
}

export interface ReferralSummary {
  code: string
  invitedCount: number
  convertedCount: number
  totalEarned: number
  pendingEarned: number
  inviteeBonus: number
  firstPurchaseBps: number
  recurringBps: number
}

export interface ProfileSummary {
  userId: string
  displayName: string | null
  username: string | null
  phone: string | null
  tier: LoyaltyTier
  lifetimeSpend: number
  orderCount: number
  joinedAt: string
}

export interface ServerStatusRow {
  nameFa: string
  health: ServerHealth
  loadPercent: number | null
}

export interface TicketCard {
  ticketId: string
  reference: string
  topicFa: string
  state: TicketState
  createdAt: string
  lastReplyAt: string | null
  unreadCount: number
}

export interface TicketMessage {
  messageId: string
  fromSupport: boolean
  bodyFa: string
  createdAt: string
}

export interface NotificationPreferences {
  expiry: boolean
  traffic: boolean
  promos: boolean
  news: boolean
  quietHours: boolean
}

export interface CardPaymentDetails {
  cardNumber: string
  cardHolderFa: string
  bankFa: string
  reviewSlaFa: string
  /** The payment these details are for. Absent only if checkout half-failed. */
  payment: PendingPayment | null
}

export interface CryptoPaymentDetails {
  network: string
  asset: string
  amountDisplay: string
  address: string
  payment: PendingPayment | null
}

export interface PendingPayment {
  paymentId: string
  reference: string
  amount: number
  method: PaymentMethod
  state: PaymentState
  createdAt: string
  card: CardPaymentDetails | null
  crypto: CryptoPaymentDetails | null
}

export interface FaqEntry {
  key: string
  questionFa: string
  answerFa: string
}

export interface FaqSection {
  key: string
  titleFa: string
  icon: string | null
  entries: FaqEntry[]
}
