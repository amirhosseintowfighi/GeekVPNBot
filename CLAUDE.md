# GeekVPN — راهنمای کار روی این پروژه

این فایل حافظه‌ی پروژه است. قبل از هر تغییری کامل بخوانش.

## این پروژه چیست

پلتفرم فروش VPN روی تلگرام. بک‌اند پایتون (FastAPI + aiogram + SQLAlchemy
async)، دو فرانت‌اند Next.js (`admin/` و `miniapp/`).

معماری Clean Architecture با چهار لایه و قرارداد `import-linter` که واقعاً
اجرا می‌شود:

```
domain/         ← هیچ import از بیرون. نه SQLAlchemy، نه FastAPI، هیچ‌چیز.
application/    ← فقط از domain. ممنوع: sqlalchemy, fastapi, aiogram, redis, jwt
infrastructure/ ← پیاده‌سازی پورت‌ها
presentation/   ← API، بات، اسکیماها
```

## تاریخچه‌ای که باید بدانی

پروژه در ۱۲ فاز با یک AI دیگر ساخته شد. کیفیت دامنه و زیرساخت بالاست، ولی یک
الگوی خطای تکرارشونده داشت:

> **مدل‌ها، دامنه و مستندات جلوتر از سیم‌کشی واقعی حرکت کردند.**

نتیجه‌اش چند حفره‌ی بزرگ بود که همه‌شان یک شکل داشتند: کد نوشته شده، تست هم
دارد، ولی هیچ‌کس صدایش نمی‌زند. مثال‌های واقعی که پیدا شدند:

- لایه‌ی `application/provisioning` اصلاً وجود نداشت — پرداخت تأیید می‌شد و
  هیچ اکانتی روی پنل ساخته نمی‌شد.
- `subscribers.register()` یک dispatch table می‌ساخت که هیچ مصرف‌کننده‌ای نداشت.
- `install_keyring()` هیچ‌جا صدا زده نمی‌شد.
- دو فرانت‌اند روی اندپوینت‌هایی ساخته شدند که در `app.py` ثبت نشده‌اند.

**قانون شماره یک این پروژه:** هر چیزی که می‌نویسی باید از یک نقطه‌ی ورودی
واقعی قابل رسیدن باشد. کدی که فقط تست صدایش می‌زند، کد مرده است.

## دستورهای ضروری

```bash
pytest                      # کل سوئیت
pytest tests/unit/x -q      # یک بخش
lint-imports                # قرارداد لایه‌ها — حتماً بعد از هر تغییر
mypy src                    # typing سخت‌گیرانه است
ruff check src tests
alembic upgrade head
alembic downgrade -1        # هر مایگریشن باید برگشت‌پذیر باشد
```

`make check` هر چهارتای اول را با هم اجرا می‌کند.

## قوانین کد

**تایپ‌ها.** هر تابع کامل تایپ شده. `Any` فقط با دلیل نوشته‌شده.

**پورت‌ها `Protocol` هستند، نه ABC.** فیک‌ها ساختاری پیاده‌سازی می‌کنند، نه با ارث‌بری.

**زمان از پورت `Clock` می‌آید.** `datetime.now()` بدون timezone در کل پروژه ممنوع
است. اگر لازم شد، `datetime.now(UTC)`.

**پول `Money` است، نه `int` یا `float`.** واحد ریال، بدون اعشار.

**مایگریشن و مدل باید یکی باشند.** الان دقیقاً می‌خوانند (۳۰ جدول، صفر اختلاف).
این را خراب نکن. بعد از هر تغییر مدل، مایگریشن بنویس و با این چک کن:

```bash
python - <<'PY'
import re, pathlib
tabs = {m.group(1) for f in pathlib.Path("migrations/versions").glob("*.py")
        for m in re.finditer(r'create_table\(\s*"([a-z_]+)"', f.read_text())}
models = {m.group(1) for f in pathlib.Path("src/geekvpn/infrastructure/persistence/models").glob("*.py")
          for m in re.finditer(r'__tablename__\s*=\s*"([a-z_]+)"', f.read_text())}
print("در مدل ولی نه مایگریشن:", sorted(models - tabs))
print("در مایگریشن ولی نه مدل:", sorted(tabs - models))
PY
```

**کامنت‌ها «چرا» را توضیح می‌دهند، نه «چه».** سبک موجود پروژه همین است و ارزش
حفظ کردن دارد. کامنتی که فقط کد را تکرار می‌کند اضافه نکن.

**فارسی.** هر متنی که کاربر می‌بیند فارسی است و در `presentation/bot/ui/text.py`
یا معادلش زندگی می‌کند، نه inline در هندلر.

## تست

سه لایه: `tests/unit/`، `tests/integration/`، `tests/architecture/`.

هر تست یک رفتار را می‌سنجد و اسمش آن رفتار را می‌گوید — نه
`test_provision_works` بلکه `test_an_unreachable_panel_leaves_the_order_failed`.

برای هر باگی که رفع می‌کنی، اول تستی بنویس که آن باگ را نشان دهد.

## دام‌هایی که واقعاً وجود دارند

**دو scope داری، sync و async.** پرداخت‌ها، تیکت‌ها و اعلان‌ها در
`sync_scope.py` هستند (Session معمولی). کاتالوگ، هویت و provisioning در
`scope.py` (AsyncSession). این عمدی است. **هرگز سعی نکن در یک تراکنش هر دو را
مخلوط کنی.** اگر لازم شد چیزی از یک طرف به طرف دیگر برود، الگویش
`OrderPaymentBridge` است: یک پورت sync جداگانه.

**رویدادها الان واقعاً تحویل می‌شوند.** `DispatchingEventPublisher` در
`infrastructure/events/`. اگر رویداد جدیدی اضافه کردی، شنونده‌اش را در
`sync_scope.events` ثبت کن وگرنه فقط لاگ می‌شود.

**`load_bundled_adapters()`** — رجیستری پنل‌ها باید بارگذاری شود. `PanelFactory`
خودش این کار را می‌کند مگر رجیستری تزریق شده باشد.

**اعتبارنامه‌ی پنل رمزنگاری‌شده است.** ستون `EncryptedString("node.password")`
با context اختصاصی. `install_keyring()` در `build_container` صدا زده می‌شود.

## قبل از اینکه بگویی «تمام شد»

```
[ ] pytest سبز
[ ] lint-imports سبز
[ ] mypy سبز
[ ] هر اندپوینت جدید در app.py ثبت شده
[ ] هر سرویس جدید در scope.py یا sync_scope.py هست
[ ] مایگریشن و مدل می‌خوانند
[ ] alembic downgrade -1 کار می‌کند
[ ] فهرست مسیرهایی که فرانت صدا می‌زند با مسیرهای ثبت‌شده تطبیق داده شد
```

آخری را با این بگیر:

```bash
grep -rhoE "'/api/[^']*'" miniapp/src admin/src | tr -d "'" | sed -E 's/\$\{[^}]*\}/{id}/g' | sort -u
```
