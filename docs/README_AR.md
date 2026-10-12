# Human2API 0.4.0

الإصدار الحالي يضيف محررًا بصريًا، وخزنة أسرار مشفرة، ودعم AX وAT-SPI، وتطبيق Android مساعدًا، وسجل أدوات موقّعة.

**وجود الكود لا يعني أنه اختُبر على كل الأجهزة.** GitHub Actions متوقف بسبب مشكلة فوترة في الحساب. بناء APK وبرامج التثبيت والاستضافة تحتاج بيئاتها وتحققًا فعليًا.

```bash
python -m pip install -e '.[dev,vault,signing]'
python -m playwright install chromium
h2a init
h2a serve
# http://127.0.0.1:8765/editor
h2a complete --repair
```

أداة `complete` تنفّذ البناء والاختبارات وتكشف العوائق، ولا تدّعي النجاح عند تأجيل اختبار.

[المرجع المحدث](../README.md) / [القبول](ACCEPTANCE.md) / [الأمان](../SECURITY.md).

---

## دليل الأوامر السابقة

# Human2API — الدليل العربي

حوّل المهام اليدوية المتكررة إلى خطوات JSON واضحة يمكن تشغيلها من Terminal أو REST API أو وكيل AI متوافق مع MCP.

**الإصدار الحالي v0.2 تجريبي للمطورين، وليس منتجًا جاهزًا لكل الأنظمة.**

## البداية بالمتصفح

```bash
pip install -e .
python -m playwright install chromium
h2a serve
```

افتح `http://127.0.0.1:8765` وجرب تطبيق الفواتير التجريبي. ولتسجيل مهمة:

```bash
h2a record https://example.com --name sample_flow
h2a check sample_flow
h2a run sample_flow --data '{"field":"some text"}' --approve
```

## الكمبيوتر Windows / macOS / Linux

```bash
pip install -e '.[desktop]'
h2a record-desktop --name mouse_demo
h2a run mouse_demo --approve
```

المسجل الحالي يلتقط النقرات والتمرير فقط، وتتوقف عند الضغط على F12. **لا يحفظ الكتابة أو كلمات المرور.** يمكنك إضافة خطوة `type_text` بمتغيرات في JSON. دعم إدخال النص حاليًا باللغة الإنجليزية ASCII فقط ويعتمد التنفيذ على إحداثيات الشاشة.

## أندرويد

ثبت ADB، فعّل USB Debugging على جهاز تملكه، ووافق على توثيق الكمبيوتر من الهاتف:

```bash
h2a devices
h2a record-android --name my_phone_task
h2a run my_phone_task --approve
```

مسجل الهاتف تفاعلي في Terminal وليس تسجيلًا خلفيًا لكل لمس. يمكن تنفيذ النقر والسحب وأوامر الإدخال الآمنة والتحقق من النص وتصوير الشاشة.

## تصحيح عناصر المتصفح

```bash
h2a run sample_flow --approve --heal-selectors
```

دعم AI اختياري جدًا ويحتاج الموافقة عليه واختيار نموذج وAPI key على جهازك. جزء من بيانات أسماء العناصر يمكن إرساله للمزود عند تفعيل `--ai-heal`، لذلك لا تستخدمه مع صفحات حساسة دون مراجعة.

## المشاركة

```bash
h2a pack sample_flow --output catalog/sample_flow.h2a.zip
h2a verify catalog/sample_flow.h2a.zip
h2a install catalog/sample_flow.h2a.zip --approve
```

المتجر الحالي **مكتبة حزم محلية** بآلية تحقق SHA-256؛ لا يوجد متجر مستضاف أو توقيعات هوية للناشرين حتى الآن.

**الأمان:** لا تشغّل Workflow غير معروف على حساباتك الشخصية. تشغيل المهام التي تغيّر بيانات يحتاج موافقة صريحة. راجع [القيود وخطة التطوير](ROADMAP.md) و[سياسة الأمان](../SECURITY.md).

## الجديد في v0.3

يمكنك إيقاف التشغيل الجاري من لوحة التحكم أو REST API من خلال `POST /api/runs/{runId}/cancel` (الإيقاف تدريجي ولا يلغي الأوامر التي انتهت).

**Windows UI Automation:** بإمكانك استخدام `h2a record-desktop --name smart_demo --smart` لتسجيل نقرات الماوس بمعرّفات عناصر Windows المستقرة إن توافرت (ولا يسجل النص المكتوب). بدلاً من النقر بإحداثيات ثابتة، ثبّت `pip install -e '.[accessibility]'` ثم نفّذ `h2a inspect-desktop --window 'عنوان النافذة'` لقراءة معرّفات عناصر الواجهة بدون قراءة الحقول السرية. تدعم أوامر `ui_click` و`ui_fill` و`ui_assert_text` و`ui_extract_text` النصوص العربية على عناصر Windows التي توفر UIA ValuePattern. على macOS وLinux ما زالت المهام المكتبية تعتمد على الإحداثيات.

**التوقيع:** ثبّت `pip install -e '.[signing]'` واستخدم `h2a keygen` لإنشاء مفتاح خاص وعام. استخدم `h2a pack --sign-key ...` للتوقيع و`h2a verify --trust-key ...` للتحقق من هوية الناشر بمفتاح مثبت مسبقاً. لا ترفع المفتاح الخاص للمستودع.

**الجدولة:** `h2a schedule add create_invoice --every-minutes 60 --approve --data-file /full/path/private.json` ثم `h2a scheduler`. تحتاج تشغيل العامل بنفسك، ولا تعمل الجدولة في الخلفية تلقائيًا. على Linux/macOS ضع صلاحية `chmod 600` على ملف المدخلات.

**حالة الجاهزية:** المشروع ما زال إصدار مطور قابلًا للتجربة، وليس منتجًا نهائيًا مضمون العمل على جميع الأجهزة. تحتاج وظائف Android وأجهزة Windows/macOS/Linux اختبارات قبول على الأجهزة الحقيقية، وما زال نشر الموقع عبر GitHub Pages معتمدًا على تفعيل GitHub Actions في الحساب.
