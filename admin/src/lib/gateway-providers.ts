/**
 * Every online provider the server can build, with what its credential field
 * means. One list for the operator's screen and the reseller's, so the two
 * cannot drift apart again - they did, and the reseller's offered providers
 * the server then refused.
 */
export const GATEWAY_PROVIDERS = {
  zarinpal: { label: 'زرین‌پال', field: 'مرچنت‌کد', hint: 'مرچنت‌کد ۳۶ کاراکتری زرین‌پال' },
  zibal: { label: 'زیبال', field: 'مرچنت', hint: 'مرچنت زیبال' },
  aqayepardakht: { label: 'آقای پرداخت', field: 'پین', hint: 'پین درگاه آقای پرداخت' },
  atlaspay: { label: 'اطلس‌پی', field: 'کلید API', hint: 'کلید API اطلس‌پی' },
  nowpayments: {
    label: 'NowPayments (ارز دیجیتال)',
    field: 'کلید API',
    hint: 'کلید API از پنل NowPayments. نرخ دلار و ارز پرداخت در تنظیمات پرداخت تعیین می‌شه.',
  },
  plisio: {
    label: 'Plisio (ارز دیجیتال)',
    field: 'Secret key',
    hint: 'Secret key از پنل Plisio. نرخ دلار در تنظیمات پرداخت تعیین می‌شه.',
  },
  ton: {
    label: 'TON',
    field: 'آدرس کیف پول TON',
    hint: 'آدرس کیف پول TON خودت. اختیاری: بعدش | و کلید API تون‌سنتر. نرخ TON در تنظیمات پرداخت.',
  },
  stars: {
    label: 'استارز تلگرام',
    field: 'قیمت هر استار (تومان)',
    hint: 'مثلاً 1500. استارها به موجودی ربات همین فروشگاه واریز می‌شن.',
  },
} as const

export type GatewayProvider = keyof typeof GATEWAY_PROVIDERS

export const GATEWAY_PROVIDER_KEYS = Object.keys(GATEWAY_PROVIDERS) as GatewayProvider[]
