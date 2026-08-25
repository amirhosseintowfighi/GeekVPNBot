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
/**
 * Mirrors `domain/provisioning/enums.py`.
 *
 * `revoked` is the one an operator creates by hand, and it was missing - so
 * the moment a subscription was closed its badge looked up `undefined` and
 * rendered blank. `expiring` and `pending` are not stored states at all; they
 * belong to the bot's read model, where "about to expire" is computed from
 * the clock. They stay because other screens type against them, but nothing
 * on the admin API ever sends them.
 */
export type SubscriptionState =
  | 'active'
  | 'expiring'
  | 'expired'
  | 'exhausted'
  | 'suspended'
  | 'revoked'
  | 'pending'

export type PlanType = 'traffic' | 'unlimited' | 'duration'
export type PublicationState = 'draft' | 'published' | 'archived'
export type PaymentMethod = 'wallet' | 'card' | 'crypto'
/** domain/payments/enums.py PaymentState, all ten of them. */
export type PaymentState =
  | 'draft'
  | 'awaiting_proof'
  | 'pending_review'
  | 'pending_gateway'
  | 'approved'
  | 'rejected'
  | 'refunded'
  | 'partially_refunded'
  | 'expired'
  | 'failed'
export type TransactionKind =
  | 'topup'
  | 'purchase'
  | 'cashback'
  | 'referral'
  | 'refund'
  | 'adjustment'
/** domain/provisioning/enums.py NodeState. A node's health *is* its state. */
export type ServerHealth = 'online' | 'degraded' | 'offline' | 'maintenance' | 'retired'
export type TicketState = 'open' | 'waiting_user' | 'answered' | 'closed'
export type LoyaltyTier = 'bronze' | 'silver' | 'gold' | 'diamond'
export type PanelKind = 'xui' | 'marzban' | 'marzneshin' | 'hiddify'
export type UserState = 'active' | 'suspended' | 'banned'
/** domain/provisioning/enums.py OrderState. */
export type OrderState = 'pending' | 'paid' | 'provisioning' | 'active' | 'failed' | 'refunded'
export type NodeState = ServerHealth

/** GET /api/v1/admin/auth/me - AdminResponse. `role` drives every guard. */
export interface AdminSession {
  id: string
  username: string
  role: Role
  permissions: string[]
  isTotpEnabled: boolean
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

/** GET /api/v1/admin/customers - CustomerResponse. */
export interface UserRow {
  id: string
  telegramId: number
  username: string | null
  displayName: string
  status: UserState
  isPremium: boolean
  referralCode: string
  referredByCode: string | null
  suspendedReason: string | null
  lastSeenAt: string | null
  createdAt: string
}

/** GET /api/v1/admin/customers/{id} - CustomerDetail. Counts, not lists. */
export interface UserDetail {
  customer: UserRow
  subscriptions: number
  orders: number
}

/** GET /api/v1/admin/subscriptions - SubscriptionResponse. */
export interface AdminSubscriptionRow {
  id: string
  userId: number
  orderId: string
  planId: string
  state: SubscriptionState
  nodeId: string | null
  remoteUsername: string | null
  subscriptionUrl: string | null
  startedAt: string
  expiresAt: string
  trafficLimitMib: number | null
  trafficUsedMib: number
  deviceLimit: number
  lastSyncedAt: string | null
  revokedAt: string | null
}

// ------------------------------------------------------------------- orders

/** GET /api/v1/admin/orders - OrderResponse. */
export interface OrderRow {
  id: string
  number: string
  userId: number
  state: OrderState
  planId: string
  planNameFa: string
  durationDays: number
  trafficMib: number | null
  deviceLimit: number
  listPrice: number
  discount: number
  total: number
  couponCode: string | null
  isRenewal: boolean
  placedAt: string
  paidAt: string | null
  provisionedAt: string | null
  failureReason: string | null
}

/** The single-order endpoint returns the same model. */
export type OrderDetail = OrderRow

// ----------------------------------------------------------------- catalog

/** PATCH /api/v1/admin/panels/{id} - UpdateNodeRequest. Every field optional. */
/**
 * POST /api/v1/admin/panels - CreateNodeRequest.
 *
 * Distinct from `NodeUpdateBody`: creating a node needs the identity and the
 * credentials that an update leaves alone. `savePanel` used to take the update
 * shape, which cannot satisfy the endpoint - every required field was optional
 * in the only type describing the call.
 */
export interface NodeCreateBody {
  id: string
  nameFa: string
  panelKind: string
  baseUrl: string
  username: string
  password: string
  countryCode?: string | null
  capacity?: number
  verifyTls?: boolean
  timeoutSeconds?: number
  sortOrder?: number
}

export interface NodeUpdateBody {
  nameFa?: string
  baseUrl?: string
  username?: string
  password?: string
  countryCode?: string | null
  capacity?: number
  verifyTls?: boolean
  timeoutSeconds?: number
  sortOrder?: number
  state?: NodeState
  acceptingNew?: boolean
}

/** GET /api/v1/admin/catalog/categories - CategoryAdminResponse. */
export interface CategoryRow {
  id: string
  slug: string
  nameFa: string
  nameEn: string | null
  descriptionFa: string | null
  icon: string | null
  sortOrder: number
  state: PublicationState
}

/** GET /api/v1/admin/catalog/products - ProductAdminResponse. */
export interface ProductRow {
  id: string
  categoryId: string
  slug: string
  tier: string
  nameFa: string
  taglineFa: string | null
  descriptionFa: string | null
  featuresFa: string[]
  icon: string | null
  nodeId: string | null
  sortOrder: number
  state: PublicationState
}

/** GET /api/v1/admin/catalog/plans - PlanAdminResponse. */
export interface PlanRow {
  id: string
  productId: string
  slug: string
  planType: PlanType
  nameFa: string
  descriptionFa: string | null
  badgeFa: string | null
  durationDays: number
  quotaGib: number | null
  dailyQuotaGib: number | null
  deviceLimit: number
  basePrice: number
  compareAtPrice: number | null
  minPrice: number
  cashbackBps: number
  maxPerUser: number | null
  sortOrder: number
  isFeatured: boolean
  state: PublicationState
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

/**
 * GET /api/v1/admin/panels - NodeResponse.
 *
 * One model, not two. `PanelRow` and `ServerRow` described a panel and the
 * servers under it as separate resources; the API has a single Node, which is
 * both. Kept as an alias rather than renamed everywhere, because the screens
 * are already split that way.
 */
export interface PanelRow {
  id: string
  nameFa: string
  panelKind: PanelKind
  state: NodeState
  baseUrl: string
  username: string
  hasPassword: boolean
  verifyTls: boolean
  timeoutSeconds: number
  capacity: number
  accountCount: number
  acceptingNew: boolean
  countryCode: string | null
  sortOrder: number
  lastCheckAt: string | null
  lastError: string | null
}

export type ServerRow = PanelRow

// -------------------------------------------------------------- promotions

/** GET /api/v1/admin/catalog/coupons - CouponAdminResponse. */
export interface CouponRow {
  id: string
  code: string
  kind: string
  descriptionFa: string | null
  /** Already formatted by the API - "۲۰٪" or "۵۰٬۰۰۰ تومان". */
  discountLabel: string
  startsAt: string | null
  endsAt: string | null
  maxRedemptions: number | null
  maxPerUser: number
  redemptionCount: number
  remainingRedemptions: number | null
  minOrderAmount: number
  targetUserId: string | null
  stacksWithCampaign: boolean
  firstPurchaseOnly: boolean
  state: PublicationState
}

/**
 * POST /api/v1/admin/catalog/coupons - CouponCreateRequest.
 *
 * A create body is not a partial row: the row carries a formatted
 * `discountLabel` and a redemption count, and the endpoint wants a
 * discountKind and a discountValue. Sending `Partial<CouponRow>` produced a
 * 422 on every field.
 */
export interface CouponCreateBody {
  code: string
  kind: string
  discountKind: 'percentage' | 'fixed_amount'
  discountValue: number
  maxDiscount?: number | null
  startsAt?: string | null
  endsAt?: string | null
  scope?: { planIds: string[]; productIds: string[]; tiers: string[] }
  descriptionFa?: string | null
  maxRedemptions?: number | null
  maxPerUser?: number
  minOrderAmount?: number
  targetUserId?: string | null
  stacksWithCampaign?: boolean
}

/** GET /api/v1/admin/catalog/campaigns - CampaignAdminResponse. */
/**
 * POST /api/v1/admin/catalog/campaigns - CampaignCreateRequest.
 *
 * Not `Partial<CampaignRow>`: the row carries a rendered `discountLabel` where
 * the request needs a kind and a value, so the create call was typed against a
 * shape the endpoint does not accept.
 */
export interface CampaignCreateBody {
  slug: string
  kind: string
  nameFa: string
  discountKind: 'percentage' | 'fixed_amount'
  /** Basis points for a percentage, Toman for a fixed amount. */
  discountValue: number
  maxDiscount?: number | null
  startsAt?: string | null
  endsAt?: string | null
  descriptionFa?: string | null
  maxRedemptions?: number | null
  priority?: number
}

export interface CampaignRow {
  id: string
  slug: string
  kind: string
  nameFa: string
  descriptionFa: string | null
  bannerUrl: string | null
  discountLabel: string
  startsAt: string | null
  endsAt: string | null
  maxRedemptions: number | null
  redemptionCount: number
  remainingStock: number | null
  priority: number
  state: PublicationState
}

// ------------------------------------------------------------------ wallet

/** GET /api/v1/admin/wallet/{userId}/ledger - routers/admin_wallet.py. */
export interface WalletTransactionRow {
  entryId: string
  kind: TransactionKind
  amount: number
  balanceAfter: number
  occurredAt: string
  descriptionFa: string | null
  reference: string | null
  actorId: string | null
  isCredit: boolean
}

// ----------------------------------------------------------------- tickets

/** GET /api/v1/admin/tickets - routers/admin_support.py. */
export interface AdminTicketRow {
  ticketId: string
  userId: number
  reference: string
  category: string
  priority: string
  state: TicketState
  subjectFa: string
  assigneeId: number | null
  createdAt: string
  updatedAt: string
  messageCount: number
  unreadForAgent: number
  unreadForCustomer: number
  waitingMinutes: number | null
}

export interface AdminTicketMessage {
  messageId: string
  ticketId: string
  kind: string
  bodyFa: string
  authorId: number | null
  createdAt: string
  attachmentCount: number
  templateId: string | null
  isRead: boolean
}

// --------------------------------------------------------------- broadcast

export type BroadcastState =
  | 'draft'
  | 'scheduled'
  | 'sending'
  | 'sent'
  | 'cancelled'
  | 'failed'

/** GET /api/v1/admin/broadcasts - routers/admin_broadcasts.py `_view`. */
export interface BroadcastRow {
  id: string
  titleFa: string
  bodyFa: string
  segment: string
  segmentLabelFa: string
  category: string
  state: BroadcastState
  audienceSize: number
  deliveredCount: number
  suppressedCount: number
  failedCount: number
  scheduledAt: string | null
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
  error: string | null
}

/**
 * Audience filter, resolved to a count before sending.
 *
 * These are `AudienceKind` from domain/notifications/enums.py, not a parallel
 * vocabulary: `active` and `never_purchased` were the panel's own words and
 * matched no rule the resolver has.
 */
export interface BroadcastAudience {
  segment:
    | 'all'
    | 'active_subscribers'
    | 'expired'
    | 'expiring_soon'
    | 'never_purchased'
    | 'tier'
    | 'explicit'
  /** Only read for `tier` (a loyalty tier) and `explicit` (ids, comma-separated). */
  reference?: string | null
}

// -------------------------------------------------------------------- logs

export type LogLevel = 'debug' | 'info' | 'warning' | 'error' | 'critical'

/**
 * GET /api/v1/admin/audit-logs - AuditEntryResponse.
 *
 * No severity level, no Persian summary and no before/after diff: the trail
 * records who did what to which target and whether it worked, plus a free-form
 * `metadata` object. The screen was built on a richer record that has never
 * existed, so every row rendered blank.
 */
export interface AuditLogRow {
  id: string
  action: string
  outcome: string
  occurredAt: string
  actorType: string
  actorId: string | null
  actorLabel: string | null
  targetType: string | null
  targetId: string | null
  ip: string | null
  correlationId: string | null
  metadata: Record<string, unknown>
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

/**
 * GET /api/v1/admin/admins - AdminResponse, the same model /auth/me returns.
 *
 * An operator signs in with a username and a password: there is no display
 * name, no email and no Telegram handle on this account, and no enabled flag -
 * disabling is a delete, which is also what ends their sessions.
 */
export type OperatorRow = AdminSession

// --------------------------------------------------------------- envelopes

/** Every list endpoint returns this shape. */
/**
 * What every paged admin endpoint returns: the rows and how many there are.
 *
 * No `page` or `pageSize` - the API pages with `limit`/`offset` and does not
 * echo them back, so the caller already knows both and the server never sent
 * them. Reading `data.page` returned undefined, which `Pagination` then
 * rendered as page NaN of NaN.
 */
export interface Paged<T> {
  items: T[]
  total: number
}

/**
 * The other half of the API, which does echo the page back.
 *
 * Endpoints built on a Pydantic response model page with limit/offset and
 * return `{items, total}`; the ones that hand-build their payload - tickets,
 * payments, the wallet statement - take a `page` and return it alongside
 * `pageSize`. Two shapes, so two types, rather than one type that is wrong
 * half the time.
 */
export interface PagedWithCursor<T> extends Paged<T> {
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

/** GET /api/v1/admin/payments/cards - the card-to-card destinations. */
export interface CardRow {
  id: string
  holderFa: string
  bankFa: string
  cardNumber: string
  sheba: string | null
  active: boolean
  sortOrder: number
  dailyLimit: number | null
}

export interface CardBody {
  holderFa: string
  bankFa: string
  cardNumber: string
  sheba?: string | null
  active?: boolean
  sortOrder?: number
  dailyLimit?: number | null
}

/** GET /api/v1/admin/payments - the review queue. */
export interface PaymentRow {
  id: string
  invoiceId: string
  userId: number
  method: string
  state: string
  amount: number
  gatewayKey: string | null
  gatewayReference: string | null
  expiresAt: string | null
  waitingMinutes?: number
  proof: {
    method: string
    reference: string | null
    digest: string | null
    submittedAt: string
    fileId: string | null
    network: string | null
    noteFa: string | null
  } | null
}

