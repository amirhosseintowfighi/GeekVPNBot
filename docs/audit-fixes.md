# رفع یافته‌های ممیزی خارجی

هر گروه یک کامیت است. هر بند یک تست رگرسیون دارد که **قبل** از اصلاح قرمز
می‌شود — این شرط پذیرش بود، چون تمام این باگ‌ها از دروازه‌ی سبز
(pytest + ruff + mypy strict + import-linter) رد می‌شدند.

الگوی مشترک همه‌شان همان است که `CLAUDE.md` هشدارش را می‌دهد: **کدی نوشته شده
که هیچ‌کس صدایش نمی‌زند، یا سیم‌کشی‌ای که به جای واقعی وصل نیست.**

---

## گروه ۱ — مسیر درآمد از اولین کلیک مرده بود (`c98f6ff`)

`match_ref` دنبال فیلدهایی می‌گشت که DTOهای کاتالوگ ندارند، پس هر کلیک روی
دسته/محصول/پلن جواب «این دکمه معتبر نیست» می‌گرفت. وبهوک هم برخلاف کامنتش
خطا را دوباره پرتاب می‌کرد و تلگرام آپدیت را تکرار می‌کرد.

## گروه ۲ — اسکیما اصلاً ساخته نمی‌شد (`3dffaba`)

`alembic_version.version_num` پیش‌فرض ۳۲ کاراکتر است و دو revision id اینجا ۴۷
و ۳۷ کاراکترند؛ stamp شکست می‌خورد. `0004` سه ایندکس تکراری می‌ساخت. و
موتورهای sync با scheme نامعتبر `psycopg://` ساخته می‌شدند در حالی که خود
`psycopg` اصلاً dependency نبود. `test_migrations.py` حالا `upgrade head` را
روی یک دیتابیس واقعی اجرا می‌کند و اسکیمای زنده را با `Base.metadata` diff
می‌گیرد.

## گروه ۳ — مسیر پول (`d170c69`, `792c7ab`)

`WalletRepository.lock` نوشته شده بود و هیچ صداکننده‌ای نداشت (double-spend).
`next_sequence` برای اولین فاکتور هر سال شمسی صفر برمی‌گرداند و LIKE‌اش
anchor نداشت. `submit_proof` هرگز نمی‌پرسید چه کسی درخواست داده (IDOR).
شارژ کیف پول کامل نوشته شده بود و هیچ‌وقت اعتبار نمی‌خورد. سقف کوپن و
digest رسید هم همین شکل بودند.

## گروه ۴ — provisioning، تمدید، سرویس تکراری (`28d30c0`)

`PROVISIONING` حالت قابل‌retry نبود، پس کارگری که وسط کار کشته می‌شد سفارشی
پرداخت‌شده و بی‌سرویس جا می‌گذاشت که هیچ‌چیز نمی‌توانست بازیابی‌اش کند. سهمیه‌ی
تمدید بین دامنه و پنل ناهم‌خوان بود. `subscriptions.order_id` unique نبود، پس
دو provision هم‌زمان دو اکانت برای یک پرداخت می‌ساختند.

---

## گروه ۵ — سیم‌کشی امنیتی

### ۲۰. Mini App از rate limiting معاف بود

جدول سیاست‌ها کلید `/api/v1/miniapp` داشت ولی روتر روی `/api/miniapp` سوار
است. آن سطر با هیچ درخواستی تطبیق نمی‌کرد، پس **هر ۲۶ اندپوینت Mini App —
از جمله checkout و شارژ کیف پول — هیچ محدودیتی نداشتند.**

- `security_middleware.py`: پیشوند اصلاح شد. دو پیشوند دقیق‌تر هم اضافه شد،
  چون `miniapp.read` (۱۸۰ در دقیقه) برای مسیر پول بی‌معنی است:
  `/api/miniapp/checkout` → `payments.checkout`، `/api/miniapp/wallet/topup`
  → `payments.topup`. زیردرخت‌هایی که خواندن و نوشتن را قاطی دارند
  (`/api/miniapp/payments`، `/api/miniapp/tickets`) روی سیاست شل ماندند —
  تطبیق پیشوندی نمی‌تواند GET و POST را از هم تشخیص دهد.
- `tests/integration/test_rate_limit_coverage.py`: هر مسیر ثبت‌شده یا به یک
  سیاست می‌رسد یا در `UNLIMITED_PATHS` با دلیل فهرست شده. نیمه‌ی دوم همان
  باگ هم بسته شد: هر پیشوند سیاست باید حداقل یک روت واقعی را بگیرد، مگر در
  `RESERVED_PREFIXES` باشد. هفت پیشوند دیگر مرده بودند (`/api/v1/payments`،
  `/api/v1/wallet`، `/api/v1/support/*`، …) — روت‌هایی که هرگز ثبت نشدند.

### ۲۱. تولید کلید JWT داخل مخزن را قبول می‌کرد

`AUTH__JWT_SECRET_KEY` در `.env.example` مقدار داشت، به‌اندازه‌ی کافی بلند بود
که از چک طول رد شود و با `SECURITY__SECRET_KEY` فرق داشت که از آن چک هم رد
شود. یعنی اپراتوری که فقط دو رمز واضح را ست می‌کرد، توکن‌هایش را با کلیدی
عمومی امضا می‌کرد.

- `settings.py`: `INSECURE_SECRET_PREFIX` حالا روی `jwt_secret` هم چک می‌شود —
  جدا از `SECURITY__SECRET_KEY`، چون `jwt_secret` روی آن fallback دارد.
- `.env.example`: مقدار خالی شد.

### ۲۲. مقادیر comma-separated در `.env.example` بوت را می‌شکستند

pydantic-settings یک فیلد complex را مستقیم از محیط JSON-decode می‌کند —
**قبل** از اینکه هر validator با `mode="before"` اجرا شود. پس
`SECURITY__CORS_ORIGINS=http://localhost:3000` در همان مرحله `SettingsError`
می‌داد و splitter هرگز آن را نمی‌دید. یعنی فایلی که به هر اپراتوری گفته
می‌شود کپی کند، اصلاً بارگذاری نمی‌شد.

- `settings.py`: `CommaSeparated = Annotated[tuple[str, ...], NoDecode]` روی
  `cors_origins`، `admin_ip_allowlist`، `encryption_retired_key_ids`
  (و دو فهرست CORS دیگر).
- `.env.example` / `scripts/install.sh`: `SECURITY__ALLOWED_HOSTS` حذف شد —
  چنین تنظیمی در کد وجود ندارد.
- تست: `Settings(_env_file=".env.example")` عیناً بوت می‌شود.

### ۲۳. allow-list آی‌پی ورود ادمین قابل جعل و رشته‌ای بود

دو نقص جدا، هر دو ریشه‌ای:

- `presentation/api/security.py`: `request_context` **چپ‌ترین** ورودی
  `X-Forwarded-For` را می‌خواند. آن ورودی را خود تماس‌گیرنده می‌نویسد. همین
  یک مقدار هم‌زمان سه تصمیم را تغذیه می‌کرد: allow-list ادمین، کلید
  rate-limit ورود، و ستون `ip` هر ردیف audit. حالا از `client_ip()` استفاده
  می‌کند که از **راست** و به تعداد پراکسی‌های خودمان می‌شمارد.
- `application/identity/authenticate_admin.py`: تطبیق `frozenset[str]` با
  `in` بود، پس CIDRای که `.env.example` توصیه می‌کند با هیچ آدرسی تطبیق
  نمی‌کرد و کل تیم را بیرون می‌گذاشت. حالا پورت `IpAllowlistPort` تزریق
  می‌شود (`application/ports/ip_allowlist.py`) و `IpAllowlist` ساختاری
  پیاده‌اش می‌کند. آدرس نامعلوم (`None`) رد می‌شود، نه اینکه عبور کند.

### ۲۴. هر درخواست Mini App یک نشست جدید می‌ساخت

`current_mini_app_user` کل use case ورود را اجرا می‌کرد. Mini App روی هر
فراخوانی initData می‌فرستد، پس هر بارگذاری صفحه یک ردیف session، یک refresh
token و یک `AUTH_LOGIN_SUCCEEDED` تولید می‌کرد — که یعنی هیچ ورود واقعی‌ای
در audit قابل دیدن نبود.

- `authenticate_telegram.py`: `verify_mini_app_request()` جدا شد — امضا را
  تأیید می‌کند، کاربر را پیدا/می‌سازد، `ensure_can_authenticate` را اجرا
  می‌کند، و همان‌جا می‌ایستد. ساخت توکن فقط روی
  `/api/v1/auth/telegram/mini-app` مانده.
- ساختن کاربر جدید عمداً در مسیر per-request ماند: فرانت‌اند Mini App هرگز
  اندپوینت ورود را صدا نمی‌زند، و مشتری تازه‌وارد بدون آن پشت در می‌ماند.
- پنجره‌ی تازگی per-request کوتاه شد: `TELEGRAM__MINI_APP_REQUEST_MAX_AGE_SECONDS`
  با پیش‌فرض ۹۰۰ ثانیه، در برابر ۸۶۴۰۰ ثانیه‌ی ورود.

> **هشدار عملیاتی.** تلگرام `auth_date` را برای یک Mini App باز تازه نمی‌کند،
> و فرانت‌اند فعلی روی 401 خودش را بارگذاری مجدد نمی‌کند. یعنی نشستی که
> بیش از ۱۵ دقیقه باز بماند خطا می‌گیرد. اگر گزارش رسید، یا این عدد را بالا
> ببرید یا فرانت‌اند را طوری کنید که روی 401 از `Telegram.WebApp` initData
> تازه بگیرد. رفع درست‌ترش این است که Mini App یک بار initData را با توکن
> عوض کند — که تغییر فرانت‌اند است و در دامنه‌ی این ممیزی نبود.


---

## پیوست — نصب‌کننده

دو خرابی که فقط روی سرور تازه دیده شدند، هر دو از همان جنس: فایلی که
تولید می‌شود هرگز به مصرف‌کننده‌اش داده نشده بود.

- `docker/backend/Dockerfile`: `.dockerignore` فایل `README.md` را کنار
  می‌گذارد ولی هر سه `COPY` نامش را می‌بردند، پس build شکست می‌خورد.
  `pyproject.toml` فیلد `readme` ندارد، پس فایل اصلاً لازم نیست.
- `scripts/install.sh`: ویزارد `TELEGRAM__WEBHOOK_URL` می‌نوشت، که یک
  `computed_field` است و مدل آن را به‌عنوان ورودی اضافه رد می‌کند. یعنی
  `alembic upgrade` روی `.env` تولیدشده می‌مرد — بعد از اینکه اپراتور همه‌چیز
  را تایپ کرده بود. حالا `TELEGRAM__WEBHOOK_BASE_URL` نوشته می‌شود و URL از
  آن ساخته می‌شود.

`tests/integration/test_install_contract.py` تا حالا فقط install.sh را با
compose مقابله می‌کرد. حالا خروجی خود ویزارد را رندر می‌کند و به `Settings`
می‌دهد — با `APP__ENV=production`، پس تمام guardrailهای تولید هم سنجیده
می‌شوند. هر کلیدی که مدل نپذیرد از این به بعد همین‌جا می‌افتد، نه روی سرور.
