# توثيق مشروع Human2API (الإصدار v0.5.0)

منصة مفتوحة المصدر لتحويل المهام المسجلة على المتصفح أو سطح المكتب (Windows / macOS / Linux) أو هاتف Android إلى Workflows قابلة لإعادة الاستخدام عبر:
- واجهة برمجية محلية آمنة (**REST API**).
- أدوات بروتوكول **MCP** لوكلاء الذكاء الاصطناعي (مع بوابة موافقة إلزامية للعمليات المؤثرة).
- استوديو ومحرر بصري ثنائي اللغة (**العربية والإنجليزية**) يدعم الوضعين الفاتح والداكن.
- أوامر سطر الأوامر (**CLI**) والمهام المجدولة (**Scheduler**).
- متجر أدوات موقعة رقميًا (**Ed25519 Signed Marketplace**).

## تشغيل المشروع لأول مرة (Windows / Linux / macOS)

**على Windows:** حمّل مستودع GitHub وفك الضغط، ثم اضغط مرتين على ملف `start-human2api.bat`. ستُنشأ بيئة Python خاصة بالمشروع وتُثبت المتطلبات وتُفتح لوحة التحكم في متصفحك تلقائيًا. يلزم Python 3.10 أو أحدث واتصال إنترنت للتثبيت الأول.

**على Linux / macOS:**

```bash
./start-human2api.sh
```

**التشغيل من الطرفية يدويًا:**

```bash
python -m pip install -e ".[browser]"
python -m playwright install chromium  # لو لم يكن Chromium موجودًا
h2a start
```

الأمر `h2a start` يفتح Studio المحلي ويضيف مهمة تجريبية **Demo Invoice**. شغّلها بعد تفعيل الموافقة على عمليات الكتابة (Write Approval)، وستملأ بيانات داخل نموذج محلي تجريبي وتتحقق من النتيجة. ليست فاتورة مالية حقيقية.

عند ظهور مشكلة في بيئة التشغيل، نفّذ `h2a doctor --json` لعرض تشخيص واضح. السيرفر المحلي يعمل دون Selenium، لكن أتمتة المتصفح تحتاج Selenium أو Playwright مع Chromium. اختبار Android الحقيقي يحتاج SDK وجهاز/محاكي، ولا يمكن اعتباره مُجتازًا بدون تلك البيئة.

## مثال إعداد عميل MCP

```json
{
  "mcpServers": {
    "human2api": {
      "command": "h2a",
      "args": ["mcp"],
      "env": {
        "H2A_ALLOW_WRITE": "0"
      }
    }
  }
}
```

## تشغيل Windows الحقيقي والتحكم في Android

**Windows:** شغّل `start-human2api.bat` أول مرة لتثبيت المتطلبات، وبعدها شغّل `start-windows-demo.bat`. في نافذة أوامر ثانية نفّذ:

```bat
.venv\Scripts\h2a.exe run --workflow src\human2api\examples\windows_demo.json --allow-write
```

لو اشتغل على Windows فعليًا، نافذة الاختبار المفروض تعرض `Saved: مرحبا Windows`؛ ده اختبار لعناصر Windows UI Automation الحقيقية من خلال pywinauto، وليس محاكاة داخل Python.

**Android (هاتف مرتبط بكمبيوتر Windows بكابل USB):** ثبت Android Studio مع SDK Platform 34 وBuild Tools 34.0.0. شغّل `build-android.bat` لبناء APK حقيقي. بعدها ثبت الناتج عبر `adb install -r android-companion/app/build/outputs/apk/debug/app-debug.apk`. افتح التطبيق على الهاتف، وفعّل خدمة إمكانية الوصول Accessibility يدويًا، واكتب في خانة الحزمة المسموحة `dev.human2api.companion` وابدأ جلسة 5 دقائق، وسيظهر كود اقتران مؤقت.

من الكمبيوتر شغّل:

```bat
.venv\Scripts\h2a.exe android doctor
.venv\Scripts\h2a.exe android run --workflow src\human2api\examples\android_companion_demo.json --allow-write
```

هيطلب كود الاقتران من الهاتف، وبعد نجاح التنفيذ المفروض النص الظاهر في شاشة الهاتف يبقى `Saved: مرحبا Android`. الهاتف هنا **تطبيق مرافق** والـAPI الأساسية بتشتغل على الكمبيوتر. لا يحتاج روت؛ يحتاج موافقتك وإعداد USB debugging. الحقول الحساسة مستبعدة، وزر STOP يوقف الجلسة فورًا. بناء APK يتطلب Android SDK، وتجربة هاتف حقيقي لا يمكن إثباتها من بيئة Linux بدون هاتف متصل.
