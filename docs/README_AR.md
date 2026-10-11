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

## سجل التشغيل المحلي

الإصدار 0.2.2 يوفّر سجل SQLite محليًا لمدة 30 يومًا (بحد أقصى 1000 مهمة)، ويسجّل فقط اسم المهمة وحالتها ووقتها ومدتها وعدد خطواتها، بدون حفظ كلمات المرور أو المدخلات أو النتائج. يمكن عرض الفهرس العام للأدوات من الواجهة أو عبر `h2a catalog --remote`؛ التثبيت لا يحدث بدون أمر صريح وموافقة.
