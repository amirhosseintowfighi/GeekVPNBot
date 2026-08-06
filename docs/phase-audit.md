# گزارش ممیزی فاز ۱ تا ۱۲

این سند نتیجه‌ی تطبیق **کد موجود** با **متن دقیق پرامپت هر فاز** است. هیچ چیزی
از روی CHANGELOG یا مستندات قبلی پذیرفته نشده؛ هر ردیف با جستجو در کد تأیید شده.

ستون وضعیت سه حالت دارد:

- **کامل** — پیاده‌سازی شده و از طریق API یا ربات قابل استفاده است.
- **ناقص** — منطق نوشته شده ولی به چیزی وصل نیست (روت ندارد، در DI نیست، یا اجرا نمی‌شود).
- **انجام نشده** — کد وجود ندارد.

---

## خلاصه‌ی مدیریتی

| فاز | موضوع | وضعیت کلی |
|---|---|---|
| ۱ | Foundation | کامل |
| ۲ | Auth & Infrastructure | کامل |
| ۳ | Panel Plugin System | کامل (بدون ذخیره‌سازی اعتبارنامه) |
| ۴ | Product & Pricing | ناقص — منطق کامل، مسیرهای ادمین ناهم‌راستا |
| ۵ | Telegram Bot | ناقص — خرید تا پرداخت می‌رود، تحویل سرویس نمی‌شود |
| ۶ | Mini App | **ناقص بحرانی** — فرانت کامل، بک‌اندش وجود ندارد |
| ۷ | Admin Panel | **ناقص بحرانی** — ۶ صفحه بدون API |
| ۸ | Payments & Wallet | کامل در سطح دامنه، بدون اتصال به سفارش |
| ۹ | Support | کامل (بدون attachments) |
| ۱۰ | Notifications | ناقص — موتور کامل، زمان‌بند اجرا نمی‌شود |
| ۱۱ | Analytics | ناقص — بدون تست |
| ۱۲ | Security | ناقص — رمزنگاری اعمال نشده |

**ریشه‌ی مشترک همه‌ی «ناقص»ها یک چیز بود:** لایه‌ی `application/provisioning`
هرگز نوشته نشد. یعنی هیچ‌جای سیستم سفارش نمی‌ساخت و هیچ‌جا بعد از پرداخت به پنل
وصل نمی‌شد. این حلقه در همین بازبینی نوشته شد (بخش پایانی سند).

---

## فاز ۱ — Foundation ✅

همه‌ی بندها موجود است. `import-linter` واقعاً پیکربندی شده و لایه‌ها رعایت
شده‌اند: صفر import از `domain` به بیرون.

**یک نقض پیدا شد و رفع شد:** دو فایل در لایه‌ی application از
`geekvpn.infrastructure.logging` import می‌کردند
(`catalog/storefront_service.py`، `catalog/policy_provider.py`) که قرارداد
`layers` را می‌شکست و CI را قرمز می‌کرد. حالا مستقیم از `structlog` استفاده
می‌کنند که در فهرست ممنوعه نیست و kwargs ساختاریافته را هم حفظ می‌کند.

---

## فاز ۲ — Authentication & Core Infrastructure ✅

| خواسته | وضعیت | محل |
|---|---|---|
| Telegram authentication | کامل | `infrastructure/security/telegram.py` |
| JWT | کامل | `infrastructure/security/jwt.py` |
| Refresh Tokens | کامل (چرخشی + تشخیص reuse) | `refresh_tokens.py` |
| Sessions | کامل | `application/identity/session_service.py` |
| RBAC | کامل، ۲۹ مجوز | `domain/identity/permissions.py` |
| Admin roles | کامل، ۵ نقش | همان |
| Permission system | کامل (deny بر grant غالب است) | `application/identity/authorization.py` |
| Audit logs | کامل، append-only در سطح دیتابیس | `migrations/0001` |
| User / Admin model | کامل | `domain/identity/` |
| Settings module | کامل، با کش Redis | `application/platform/settings_service.py` |

بهترین‌ساخته‌شده‌ترین فاز پروژه. حتی نقص timing-oracle در ورود ادمین پیدا و
رفع شده بود.

---

## فاز ۳ — VPN Panel Plugin System ✅ (با یک شکاف)

پنج آداپتور، رجیستری، فکتوری بدون منطق panel-specific، و تست conformance
پارامتریک روی رجیستری — یعنی افزودن پنل جدید واقعاً فقط یک فایل است. UML هم
تولید شده (`docs/uml/`).

**شکاف:** جدول `nodes` فقط `base_url` و `panel_kind` دارد و **ستون
username/password رمزنگاری‌شده ندارد**. پس `PanelFactory` از دیتابیس قابل ساخت
نیست. تا وقتی این ستون‌ها اضافه نشوند، آداپتورها کد مرده‌اند. (کار باقی‌مانده:
مایگریشن `0005` — در نقشه‌ی راه پایین سند.)

---

## فاز ۴ — Product & Pricing Engine ⚠️

منطق کامل و باکیفیت است: `domain/catalog/` شامل قیمت‌گذاری پویا، نردبان مدت
زمان، کوپن، کمپین، flash sale، cashback و پاداش معرف — با تست.

**مشکل:** «Everything configurable from Admin Panel» محقق نشده، چون مسیرهای API
با چیزی که پنل ادمین صدا می‌زند فرق دارد:

| پنل ادمین صدا می‌زند | API واقعاً دارد |
|---|---|
| `/api/v1/admin/categories` | `/api/v1/admin/catalog/categories` |
| `/api/v1/admin/products` | `/api/v1/admin/catalog/products` |
| `/api/v1/admin/plans` | `/api/v1/admin/catalog/plans` |
| `/api/v1/admin/coupons` | `/api/v1/admin/catalog/coupons` |
| `/api/v1/admin/duration-ladder` | وجود ندارد |
| `/api/v1/admin/plans/generate-ladder` | وجود ندارد |

یعنی هر درخواست از پنل ۴۰۴ می‌گیرد.

---

## فاز ۵ — Telegram Bot ⚠️

ساختار aiogram درست است: میدل‌ور هویت، throttle، FSM، کیبوردهای فارسی، متون
RTL. هر ۱۲ بخش خواسته‌شده هندلر دارد.

**مشکل:** جریان خرید تا «پرداخت را ثبت کن» می‌رود و آنجا تمام می‌شود. چون
`OrderService` وجود نداشت، هیچ سفارشی ساخته نمی‌شد و بعد از تأیید پرداخت هیچ
اکانتی روی پنل ساخته نمی‌شد. مشتری پول می‌داد و سرویس نمی‌گرفت.

---

## فاز ۶ — Telegram Mini App ❌ بحرانی

فرانت‌اند کامل و باکیفیت است: Next.js، Tailwind، shadcn، RTL، تم تیره،
Framer Motion، ۱۴ صفحه.

**اما بک‌اندش وجود ندارد.** مینی‌اپ این ۱۶ اندپوینت را صدا می‌زند و **هیچ‌کدام
در `app.py` ثبت نشده‌اند**:

```
/api/miniapp/storefront      /api/miniapp/wallet
/api/miniapp/quote           /api/miniapp/wallet/topup
/api/miniapp/coupon/preview  /api/miniapp/payments/pending
/api/miniapp/checkout/card   /api/miniapp/tickets
/api/miniapp/checkout/crypto /api/miniapp/profile
/api/miniapp/checkout/wallet /api/miniapp/referral
/api/miniapp/subscriptions   /api/miniapp/servers
/api/miniapp/faq             /api/miniapp/preferences
```

ضمناً مینی‌اپ هدر `Authorization: tma <initData>` می‌فرستد، ولی بک‌اند مدل JWT
دارد (`POST /auth/telegram/mini-app`). حتی اگر روت‌ها ساخته شوند، احراز هویت هم
باید هم‌راستا شود.

---

## فاز ۷ — Admin Panel ❌ بحرانی

۱۶ صفحه ساخته شده. اما شش بخش از پانزده بخش خواسته‌شده **هیچ API ندارند**:

| بخش | API |
|---|---|
| Dashboard | فقط زیر `/admin/analytics/dashboard` (مسیر متفاوت) |
| Users | ❌ وجود ندارد (`admin_users` فقط `/admin/admins` دارد) |
| Orders | ❌ وجود ندارد |
| Panels | ❌ وجود ندارد |
| Servers | ❌ وجود ندارد |
| Broadcast | ❌ وجود ندارد |
| Permissions | جزئی (`PUT /admin/admins/{id}/permissions`) |
| Products / Coupons / Campaigns | مسیر متفاوت (فاز ۴) |
| Analytics / Tickets / Wallet / Logs / Settings | ✅ |

---

## فاز ۸ — Payments & Wallet ⚠️

دامنه‌ی پرداخت بهترین بخش طراحی‌شده‌ی پروژه است: کیف پول با دفتر دوطرفه،
`GatewayRegistry`، پرداخت دستی به‌عنوان «درگاهی که تأییدکننده‌اش انسان است»،
digest رسید برای جلوگیری از رسید تکراری، سقف بازپرداخت در سطح دیتابیس.

**مشکل:** رویداد `PaymentApproved` که خودش در کد نوشته «تنها ماشه‌ی
provisioning»، هیچ شنونده‌ای نداشت. تنها پیاده‌سازی `EventPublisher` در کل
پروژه `LoggingEventPublisher` بود — یعنی رویداد فقط در لاگ می‌نشست.

---

## فاز ۹ — Support System ✅ (یک قلم کم)

تیکت، اولویت، دسته‌بندی، یادداشت داخلی، قالب پاسخ، جستجو (با ایندکس trigram)،
تاریخچه و اعلان — همه موجود و تست‌شده. API ادمین کامل است.

**کم:** `Attachments`. جدول `support_messages` ستون فایل ندارد و هیچ مسیر آپلودی
نیست.

---

## فاز ۱۰ — Notification Engine ⚠️

موتور، کانال‌ها، ترجیحات کاربر، ساعات سکوت، broadcast با batching، کمپین،
یادآور انقضا و یادآور ترافیک — همه نوشته و تست شده‌اند (۱۳ فایل تست).

**مشکل:** هیچ پروسه‌ای آن‌ها را اجرا نمی‌کند. در `docker-compose.prod.yml` فقط
`api_blue`، `api_green` و `bot` هستند. `scheduler.py` و `reminders.py` کد مرده‌اند.

---

## فاز ۱۱ — Analytics & Marketing ⚠️

دامنه‌ی تحلیل دقیق و فکرشده است (تبدیل جلالی، هفته از شنبه، بازه‌های نیم‌باز،
دوره‌ی مهلت ۱۴ روزه برای churn). API ادمین هم دارد.

**مشکل:** خود CHANGELOG می‌نویسد «فاز ۱۱ به‌جای تست، مستندات تحویل داد». برای
~۲۳ ماژول محاسباتی که عدد پول تولید می‌کنند، صفر تست وجود دارد.

---

## فاز ۱۲ — Security & Optimization ⚠️

همه‌ی ۱۵ بند پیاده‌سازی شده و گزارش امنیتی هم تولید شده — و گزارش، برخلاف
معمول، صادق است و کمبودها را خودش می‌نویسد:

- رمزنگاری «موجود» است ولی «اعمال» نشده: مدل‌ها هنوز از `EncryptedString`
  استفاده نمی‌کنند و backfill نوشته نشده.
- Recovery codeها ساخته شده‌اند ولی هیچ‌جا enroll نمی‌شوند.
- محافظت از replay در پنجره‌ی TOTP متمرکز نیست.

---

# آنچه در همین بازبینی رفع شد

## ۱. لایه‌ی `application/provisioning` نوشته شد (حلقه‌ی گم‌شده)

| فایل | نقش |
|---|---|
| `ports.py` | `NodeRecord`، و پورت‌های سفارش/اشتراک/نود/پنل |
| `node_selector.py` | انتخاب سرور — تابع خالص، بدون I/O |
| `order_service.py` | ساخت سفارش + پل `PaymentApproved → OrderPaid` |
| `provisioning_service.py` | تحویل سرویس: ساخت اکانت روی پنل، تمدید، صف تلاش مجدد |

تصمیم‌های کلیدی:

- **نام کاربری پنل مشتق است، نه تصادفی.** `username_for(order)` تابعی خالص از
  شماره‌ی سفارش است، پس یک retry بعد از timeout همان نام را می‌خواهد و طبق
  قرارداد آداپتور، اکانت موجود برگردانده می‌شود. نام تصادفی یعنی هر timeout
  می‌شود یک اکانت تکراری که کسی بابتش پول نمی‌گیرد.
- **منبع حقیقت «آیا انجام شد» سفارش ماست، نه پنل.** وجود اشتراک متصل به سفارش،
  کل روال را کوتاه می‌کند. برای همین `provision` هم‌زمان از وبهوک، از حلقه‌ی
  retry و از دکمه‌ی «تلاش مجدد» اپراتور قابل فراخوانی است.
- **شکست یعنی بازپرداخت نیست.** پنل در دسترس نباشد، سفارش FAILED می‌شود و صف
  retry دوباره برش می‌دارد. پول کپچرشده می‌ماند چون مشتری هنوز محصول را می‌خواهد.
- **کشور یک وعده است، نه ترجیح.** اگر پلن آلمان فروخته شده و نود آلمانی پر است،
  انتخاب به هلند نمی‌افتد؛ سفارش می‌رود در صف. تحویل محصول اشتباه بدتر از تأخیر است.
- **تمدید، اکانت جدید نمی‌سازد.** وگرنه مشتری هر ماه باید کانفیگ جدید نصب کند،
  که شایع‌ترین دلیل قطع تمدید است.

**۳۵ تست نوشته و اجرا شد — هر ۳۵ پاس می‌شوند.** درستی خودِ هارنس هم با یک
mutation آزمایش شد.

## ۲. نقض معماری (CI-breaking)

دو import از application به infrastructure حذف شد. حالا `lint-imports` تمیز است.

## ۳. `datetime.now()` بدون timezone

در `presentation/bot/notifications.py` ساعات سکوت به timezone کانتینر وابسته
بود. به `datetime.now(UTC)` تغییر کرد، هم‌راستا با بقیه‌ی سیستم.

---

# نقشه‌ی راه باقی‌مانده (به ترتیب اولویت)

اینها **قبل از هر فاز جدیدی** باید انجام شوند. ترتیب مهم است؛ هر مرحله به قبلی
وابسته است.

### گام ۱ — ذخیره‌سازی اعتبارنامه‌ی پنل
مایگریشن `0005`: افزودن `username`, `password_encrypted`, `verify_tls`,
`config_json` به `nodes` با نوع ستون `EncryptedString` که از قبل موجود است.
سپس `SqlAlchemyNodeRepository` که `NodeRecord` برمی‌گرداند، و `PanelProvider`
که با `PanelFactory` آداپتور می‌سازد. بدون این گام، فاز ۳ کد مرده می‌ماند.

### گام ۲ — سیم‌کشی provisioning در DI
افزودن `PanelProvider` و سرویس‌های جدید به `Container` و `RequestScope`، و ثبت
`OrderPaymentBridge` به‌عنوان شنونده‌ی `PaymentApproved` در `sync_scope.py` —
دقیقاً همان الگویی که `subscribers.py` در فاز ۱۰ استفاده می‌کند.

### گام ۳ — Event dispatcher واقعی
جایگزینی `LoggingEventPublisher` با outbox در Postgres (که
`docs/architecture.md` وعده داده). بدون این، رویدادها همچنان فقط لاگ می‌شوند.

### گام ۴ — پروسه‌ی worker
`entrypoints/worker.py` + سرویس در `docker-compose.prod.yml` که اجرا کند:
`drain_stuck` (صف provisioning)، یادآورهای فاز ۱۰، sweeper تأیید پرداخت، و
همگام‌سازی مصرف با پنل.

### گام ۵ — روت‌های گم‌شده‌ی ادمین
`admin_orders`, `admin_subscriptions`, `admin_panels`, `admin_users` (کاربران
نهایی، نه ادمین‌ها)، `admin_broadcast`. سپس هم‌راستاسازی مسیرهای کاتالوگ با
`admin/src/lib/api.ts` — یا تغییر prefix در بک‌اند، یا تغییر `ROOT` در فرانت.
تصمیم را یک‌بار بگیرید و در `admin/docs/api-contract.md` بنویسید.

### گام ۶ — روترهای `/api/miniapp/*`
۱۶ اندپوینت + احراز هویت هدر `tma`. اینها اغلب read model هستند و بیشترشان
معادل بات را دارند (`application/bot/read_models.py`) — یعنی کار کمتری از آن
است که به‌نظر می‌رسد.

### گام ۷ — بدهی‌های باقی‌مانده
تست برای analytics، اعمال رمزنگاری روی مدل‌ها + backfill، enroll کردن recovery
code، و attachment برای تیکت.

---

## یک قانون برای فازهای بعدی

الگوی خطا در این پروژه یک چیز بود: **مدل و مستندات جلوتر از سیم‌کشی حرکت
کردند، و فرانت‌اندها روی قراردادی ساخته شدند که کسی پیاده‌اش نکرد.**

در هر پرامپت بعدی این بند را اضافه کنید:

> هر اندپوینتی که فرانت‌اند صدا می‌زند باید در همان فاز در `app.py` ثبت شده
> باشد و یک تست integration داشته باشد. در پایان فاز، فهرست مسیرهای ثبت‌شده را
> با فهرست مسیرهای صداشده مقایسه کن و اختلاف را گزارش بده.

---

# پیوست: کار انجام‌شده در دور دوم

## گام ۱ — ذخیره‌سازی اعتبارنامه‌ی پنل ✅

- **مایگریشن `0005_panel_credentials`**: افزودن `username`، `password_encrypted`
  (با `EncryptedString` و context اختصاصی `node.password`)، `verify_tls`،
  `config_json` و `timeout_seconds` به جدول `nodes`.
- **یک constraint که ارزش بحث دارد**: `nodes_online_requires_credentials` —
  نودی که online است و مشتری قبول می‌کند ولی رمز ندارد، یک خطای provisioning
  در آینده است. constraint آن را به خطای نوشتن در زمان پیکربندی تبدیل می‌کند.
- **`config_json` عمداً opaque است**: یک ستون به‌ازای هر پنل یعنی «افزودن پنل
  جدید = ویرایش کد موجود»، که دقیقاً همان چیزی است که معماری پلاگین فاز ۳ برای
  اجتنابش ساخته شد.
- `SqlAlchemyNodeRepository` که `NodeRecord` برمی‌گرداند — بدون رمز. رمز فقط در
  لحظه‌ی ساخت آداپتور و با `credentials_for()` خوانده می‌شود.

## گام ۲ — `DatabasePanelProvider` و سیم‌کشی DI ✅

- `infrastructure/panels/provider.py`: حلقه‌ی آخر فاز ۳. آداپتورها per-node کش
  می‌شوند (هر آداپتور یک connection pool دارد؛ ساخت مجدد به‌ازای هر سفارش یعنی
  دور ریختن هر keep-alive و لاگین دوباره در هر خرید).
- `panel_id_for()` در لایه‌ی application تعریف شد تا provider و
  `provisioning_service` نتوانند از هم فاصله بگیرند — اگر واگرا می‌شدند، تمدید
  به اکانتی آدرس می‌داد که وجود ندارد.
- `RequestScope` حالا `orders`، `subscriptions`، `nodes`، `panel_provider`،
  `order_service` و `provisioning` دارد، به‌علاوه‌ی `aclose()` برای آزادسازی
  سوکت‌های پنل.

## گام ۳ — Event dispatcher واقعی ✅

اینجا یک کشف مهم بود: **شنونده‌های اعلان فاز ۱۰ هم مرده بودند.** تابع
`subscribers.register()` یک dispatch table می‌ساخت که هیچ‌کس مصرفش نمی‌کرد.

`infrastructure/events/dispatcher.py` آن مصرف‌کننده است:

- **یک handler هرگز عملیات را شکست نمی‌دهد.** رویداد توصیف چیزی است که *قبلاً*
  اتفاق افتاده؛ برگرداندن یک پرداخت موفق چون تلگرام قطع بوده، معامله‌ی بدی است.
- **مسیریابی با نام سیم است، نه کلاس.** روزی که این رویدادها از جدول outbox به
  شکل JSON برسند، همین جدول بدون import کردن دامنه‌ی پرداخت مسیریابی می‌کند.
- **رویداد بدون شنونده لاگ می‌شود، بی‌صدا دور ریخته نمی‌شود.**

نتیجه: `PaymentApproved` حالا هم‌زمان مشتری را مطلع می‌کند **و** سفارش را PAID
می‌کند. هر دو قبلاً کار نمی‌کردند.

ضمناً `install_keyring()` که هیچ‌جا صدا زده نمی‌شد، حالا در `build_container`
صدا زده می‌شود — وگرنه اولین خواندن ستون رمزنگاری‌شده در production خطا می‌داد.

## گام ۴ — پروسه‌ی worker ✅

`entrypoints/worker.py` + سرویس `worker` در `docker-compose.prod.yml`.

- **قفل Redis به‌ازای هر tick**: دو worker یعنی یادآور تکراری، و مشتری که دو بار
  پیام «۳ روز تا انقضا» بگیرد به پیام بعدی کمتر اعتماد می‌کند.
- **صف provisioning جداگانه و سریع‌تر (۴۵ ثانیه)**: مشتری که منتظر اکانتِ
  پول‌داده است، حساس‌ترین چیز در این سیستم است.
- **مهلت ۶۰ ثانیه قبل از retry**: تا sweep با درخواست checkout در حال پرواز
  مسابقه ندهد.
- `SqlSubscriptionReader` نوشته شد (فاز ۱۰ پورتش را داشت، پیاده‌سازی SQL نداشت).
  فیلتر در SQL انجام می‌شود، نه در پایتون — وگرنه sweep باید هر اشتراک metered
  را لود کند تا ۹۵٪ را دور بریزد.
- `BROADCAST_DISPATCH` و `CAMPAIGN_ANNOUNCE` **عمداً ثبت نشده‌اند**، چون
  `BroadcastService` و `CampaignService` هرکدام یک reader می‌خواهند که
  پیاده‌سازی SQL ندارد. ثبت کردن handlerی که ساخته نمی‌شود، یک شکاف شناخته‌شده را
  به tickی تبدیل می‌کند که هر ۳۰ ثانیه fail می‌شود. scheduler jobهای ثبت‌نشده را
  رد می‌کند.

## اعتبارسنجی

چون `pytest` و اینترنت در محیط من نبود، این‌ها را انجام دادم:

- ۴۳ تست نوشته و اجرا شد (۳۵ provisioning + ۸ dispatcher) — همه پاس.
- درستی خودِ هارنس با یک mutation آزمایش شد.
- یک checker با AST نوشتم که تأیید کند هر kwarg در هر construction site با
  `__init__` هدفش می‌خواند — این دقیقاً همان کلاس باگی بود که در نوشتن worker
  گرفتارش شدم (`scope.reminders` وجود نداشت).
- زنجیره‌ی مایگریشن‌ها بررسی شد: `0001 → 0005` بدون شکاف.
- صفر import از application/domain به لایه‌های بالاتر.

## هنوز باقی مانده

| کار | چرا هنوز نیست |
|---|---|
| روترهای `/api/miniapp/*` (۱۶ اندپوینت) | کار بزرگ و مستقل؛ نیازمند تصمیم درباره‌ی احراز هویت `tma` |
| روترهای ادمین: `orders`, `subscriptions`, `panels`, `users`, `broadcast` | ~۵ فایل روتر + schema |
| هم‌راستاسازی مسیرهای کاتالوگ با فرانت ادمین | تصمیم یک‌خطی، ولی باید یک‌بار گرفته شود |
| readerهای SQL برای broadcast و campaign | تا آن‌ها نباشند دو job زمان‌بندی‌شده خاموش‌اند |
| Outbox واقعی به‌جای dispatch درون-تراکنشی | dispatcher فعلی seam درست را دارد؛ فقط پیاده‌سازی عوض می‌شود |
| تست برای analytics | فاز ۱۱ صفر تست دارد |
| backfill رمزنگاری برای ستون‌های موجود | مکانیزم آماده است، اعمال روی داده‌ی قدیمی نه |
| attachment تیکت | ستون و مسیر آپلود ندارد |
