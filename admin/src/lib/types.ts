/**
 * Admin read models.
 *
 * Mirrors the shapes the admin API will return, which are in turn projections
 * over the existing services: CatalogAdminService, PromotionAdminService and
 * the eight BotServices ports. Nothing here invents a concept the domain does
 * not already have.
 *
 * Two invariants carried over from the Python side and never broken:
 * - Money is an integer count of tomans. Never a float.
 * - Timestamps are ISO-8601 strings, parsed at the edge by fa.ts.
 */

import type { Role } from './rbac'

// Unions shared with the bot and the Mini App. Kept identical on purpose: a
// state that renders green for a customer must render green for an operator.
export type SubscriptionState =
  | 'active'
  | 'expiring'
  | 'expired'
  | 'exhausted'
  | 'suspended'
  | 'pending'

export type PlanType = 'traffic' | 'unlimited' | 'duration'
export type PublicationState = 'draft' | 'published' | 'archived'
export type PaymentMethod = 'wallet' | 'card' | 'crypto'
export type PaymentState =
  | 'draft'
  | 'awaiting_proof'
  | 'pending_review'
  | 'approved'
  | 'rejected'
  | 'expired'
export type TransactionKind =
  | 'topup'
  | 'purchase'
  | 'cashback'
  | 'referral'
  | 'refund'
  | 'adjustment'
export type ServerHealth = 'healthy' | 'degraded' | 'down' | 'maintenance'
export type TicketState = 'open' | 'answered' | 'closed'
export type LoyaltyTier = 'bronze' | 'silver' | 'gold' | 'diamond'
export type PanelKind = 'xui' | 'marzban' | 'marzneshin' | 'hiddify'
export type UserState = 'active' | 'suspended' | 'banned'

/** The signed-in operator. `role` drives every guard in the interface. */
export interface AdminSession {
  operatorId: string
  displayName: string
  telegramUsername: string | null
  role: Role
  lastLoginAt: string | null
}

// ---------------------------------------------------------------- dashboard

/*
 * These mirror `as_dict()` on the analytics domain objects, field for field.
 * They previously described a payload nobody serves - `deltaPercent` for what
 * the API calls `changePercent`, a `date` on each point that is called `at`, a
 * `signupSeries` and a `tierMix` that do not exist. Every screen built on them
 * failed to type-check, which is why this panel had never been built at all.
 *
 * The source of truth is domain/analytics/dashboard.py; change these together.
 */

export type MetricFormat = 'toman' | 'count' | 'percent' | 'gib' | 'days'

/**
 * A headline figure. `changePercent` is period-over-period against the same
 * window length, and is null when there is no comparable prior period - a
 * fake zero would read as "flat" when the truth is "unknown".
 */
export interface MetricCard {
  key: string
  labelFa: string
  format: MetricFormat
  value: number
  previous: number | null
  valueFa: string
  changePercent: number | null
  changeFa: string
  direction: 'up' | 'down' | 'flat'
  isImprovement: boolean | null
  hintFa: string
}

export interface TimeSeriesPoint {
  /** ISO timestamp of the bucket start. */
  at: string
  value: number
  labelFa: string
}

export interface TimeSeries {
  key: string
  labelFa: string
  format: MetricFormat
  granularity: 'day' | 'week' | 'month'
  total: number
  points: TimeSeriesPoint[]
}

export interface BreakdownSlice {
  key: string
  labelFa: string
  value: number
  share: number
}

export interface Breakdown {
  key: string
  labelFa: string
  format: MetricFormat
  total: number
  slices: BreakdownSlice[]
}

/** One queue entry on the dashboard: a count, and where to go and clear it. */
export interface ActionItem {
  key: string
  labelFa: string
  count: number
  href: string
  urgent: boolean
}

export interface DashboardSummary {
  metrics: MetricCard[]
  actions: ActionItem[]
  pendingWork: number
  quiet: boolean
  revenueSeries: TimeSeries | null
  fleet: { nodes: number; healthy: number } | null
}

// -------------------------------------------------------------------- users

export interface UserRow {
  userId: string
  telegramId: number
  displayName: string
  telegramUsername: string | null
  state: UserState
  tier: LoyaltyTier
  walletBalance: number
  lifetimeSpend: number
  activeSubscriptions: number
  joinedAt: string
  lastSeenAt: string | null
}

export interface UserDetail extends UserRow {
  phone: string | null
  email: string | null
  referralCode: string
  referredByCode: string | null
  orderCount: number
  noteFa: string | null
  subscriptions: AdminSubscriptionRow[]
  recentTransactions: WalletTransactionRow[]
}

export interface AdminSubscriptionRow {
  subscriptionId: string
  userId: string
  displayName: string
  productNameFa: string
  planNameFa: string
  state: SubscriptionState
  panelNameFa: string | null
  quotaGib: number | null
  usedGib: number
  deviceLimit: number
  startedAt: string
  expiresAt: string | null
}

// ------------------------------------------------------------------- orders

export interface OrderRow {
  orderId: string
  reference: string
  userId: string
  displayName: string
  telegramUsername: string | null
  productNameFa: string
  planNameFa: string
  amount: number
  discountAmount: number
  method: PaymentMethod
  state: PaymentState
  couponCode: string | null
  campaignNameFa: string | null
  createdAt: string
  reviewedAt: string | null
  reviewedByFa: string | null
}

export interface OrderDetail extends OrderRow {
  subtotal: number
  cashbackAmount: number
  lines: Array<{ kind: string; labelFa: string; amount: number }>
  receiptUrl: string | null
  txid: string | null
  cryptoNetwork: string | null
  cryptoAddress: string | null
  rejectionReasonFa: string | null
  subscriptionId: string | null
}

// ----------------------------------------------------------------- catalog

export interface CategoryRow {
  categoryId: string
  slug: string
  nameFa: string
  icon: string
  state: PublicationState
  productCount: number
  sortOrder: number
}

export interface ProductRow {
  productId: string
  categoryId: string
  slug: string
  nameFa: string
  taglineFa: string | null
  icon: string
  state: PublicationState
  panelId: string | null
  panelNameFa: string | null
  planCount: number
  isFeatured: boolean
  sortOrder: number
}

export interface PlanRow {
  planId: string
  productId: string
  slug: string
  nameFa: string
  planType: PlanType
  state: PublicationState
  durationDays: number
  basePrice: number
  compareAtPrice: number | null
  minPrice: number | null
  quotaGib: number | null
  dailyQuotaGib: number | null
  deviceLimit: number
  cashbackBps: number
  maxPerUser: number | null
  badgeFa: string | null
  isFeatured: boolean
  sortOrder: number
  activeSubscriptions: number
}

/** One rung of the duration ladder, mirroring domain/catalog/durations.py. */
export interface DurationRung {
  days: number
  slug: string
  nameFa: string
  discountBps: number
  badgeFa: string | null
  bonusDevices: number
}

// ------------------------------------------------------------------ panels

export interface PanelRow {
  panelId: string
  nameFa: string
  kind: PanelKind
  baseUrl: string
  health: ServerHealth
  inboundCount: number
  subscriptionCount: number
  lastCheckedAt: string | null
  lastErrorFa: string | null
  isEnabled: boolean
}

export interface ServerRow {
  serverId: string
  nameFa: string
  panelId: string
  panelNameFa: string
  hostname: string
  countryFa: string
  flag: string
  health: ServerHealth
  loadPercent: number | null
  latencyMs: number | null
  capacity: number | null
  activeUsers: number
  isVisible: boolean
}

// -------------------------------------------------------------- promotions

export interface CouponRow {
  couponId: string
  code: string
  discountKindFa: string
  /** Percentage coupons carry bps; fixed coupons carry an amount. */
  discountBps: number | null
  discountAmount: number | null
  state: PublicationState
  usedCount: number
  maxUses: number | null
  maxUsesPerUser: number | null
  minOrderAmount: number | null
  stacksWithCampaign: boolean
  startsAt: string | null
  endsAt: string | null
  createdAt: string
}

export interface CampaignRow {
  campaignId: string
  nameFa: string
  discountBps: number
  state: PublicationState
  scopeFa: string
  isFlashSale: boolean
  startsAt: string
  endsAt: string | null
  orderCount: number
  revenue: number
  discountGiven: number
}

// ------------------------------------------------------------------ wallet

export interface WalletTransactionRow {
  transactionId: string
  userId: string
  displayName: string
  kind: TransactionKind
  amount: number
  balanceAfter: number
  descriptionFa: string
  actorFa: string | null
  createdAt: string
}

// ----------------------------------------------------------------- tickets

export interface AdminTicketRow {
  ticketId: string
  reference: string
  userId: string
  displayName: string
  topicFa: string
  subjectFa: string
  state: TicketState
  assigneeFa: string | null
  messageCount: number
  createdAt: string
  lastReplyAt: string | null
  waitingMinutes: number | null
}

export interface AdminTicketMessage {
  messageId: string
  fromSupport: boolean
  authorFa: string
  bodyFa: string
  createdAt: string
}

// --------------------------------------------------------------- broadcast

export type BroadcastState =
  | 'draft'
  | 'scheduled'
  | 'sending'
  | 'sent'
  | 'cancelled'
  | 'failed'

export interface BroadcastRow {
  broadcastId: string
  titleFa: string
  bodyFa: string
  audienceFa: string
  state: BroadcastState
  recipientCount: number
  sentCount: number
  failedCount: number
  scheduledAt: string | null
  createdAt: string
  createdByFa: string
}

/** Audience filter for a new broadcast, resolved to a count before sending. */
export interface BroadcastAudience {
  segment:
    | 'all'
    | 'active'
    | 'expiring'
    | 'expired'
    | 'never_purchased'
    | 'tier'
  tier: LoyaltyTier | null
}

// -------------------------------------------------------------------- logs

export type LogLevel = 'debug' | 'info' | 'warning' | 'error' | 'critical'

export interface AuditLogRow {
  entryId: string
  at: string
  level: LogLevel
  actorFa: string
  action: string
  entityType: string
  entityId: string | null
  summaryFa: string
  correlationId: string | null
  /** Before/after pairs for a mutation, already redacted server-side. */
  changes: Array<{ field: string; before: string | null; after: string | null }>
}

// ---------------------------------------------------------------- settings

/**
 * A single policy knob. `key` matches the policy provider key in the Python
 * domain exactly, so a value changed here lands in the same place the pricing
 * pipeline reads from.
 */
export interface PolicySetting {
  key: string
  labelFa: string
  descriptionFa: string
  kind: 'toman' | 'bps' | 'count' | 'boolean' | 'text'
  value: number | boolean | string
  min: number | null
  max: number | null
  groupFa: string
}

export interface OperatorRow {
  operatorId: string
  displayName: string
  telegramUsername: string | null
  role: Role
  isEnabled: boolean
  lastLoginAt: string | null
  createdAt: string
}

// --------------------------------------------------------------- envelopes

/** Every list endpoint returns this shape. */
export interface Paged<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

/** GET /api/v1/admin/analytics - AnalyticsBundle.as_dict(), field for field. */
export interface AnalyticsBundle {
  range: {
    start: string
    end: string
    days: number
    labelFa: string
    granularity: 'day' | 'week' | 'month'
  }
  metrics: MetricCard[]
  revenueSeries: TimeSeries | null
  ordersSeries: TimeSeries | null
  planBreakdown: Breakdown | null
  methodBreakdown: Breakdown | null
  topPlans: Array<{
    planId: string
    planName: string
    orders: number
    revenue: number
    trafficGib: number
    daysSold: number
    averagePrice: number
  }>
  campaigns: Array<{
    campaignId: string
    nameFa: string
    kind: string
    redemptions: number
    redemptionRate: number
    discountGiven: number
    netRevenue: number
    grossRevenue: number
    newCustomerShare: number
    returnOnDiscount: number
  }>
  segments: {
    totalCustomers: number
    winBackAudience: number
    stats: Array<{ segment: string; labelFa: string; customers: number }>
  }
}
