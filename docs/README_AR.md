# Human2API 0.4.1

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
