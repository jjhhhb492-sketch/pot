# بوت دسكورد متكامل

## الميزات
ترحيب/وداع + رتبة تلقائية + رسالة خاص • معلومات (user/avatar/server/profile) • مودريشن (ban/kick/timeout/warn/clear/lock/slowmode) + حماية تلقائية (روابط/كلمات) • تذاكر مع سجل • مستويات + رتب مستويات + يومي/رصيد • ردود تلقائية • لوحة رتب بالأزرار • ستاربورد • لوقز • رومات صوتية مؤقتة • say/announce/dm/dmrole

## التشغيل خطوة بخطوة
1. **البوت:** discord.com/developers/applications → New Application → Bot → Reset Token (انسخه).
   فعّل **SERVER MEMBERS INTENT** و **MESSAGE CONTENT INTENT**.
2. **الدعوة:** OAuth2 → URL Generator → scopes: `bot` + `applications.commands` → صلاحية Administrator → افتح الرابط وأضف البوت.
3. **قاعدة البيانات (مجانية):** mongodb.com/atlas → Free Cluster → Database Access (يوزر وباسورد) → Network Access: `0.0.0.0/0` → Connect → Drivers → انسخ `MONGO_URI`.
   (ضروري لأن ديسك Render المجاني يتمسح.)
4. **GitHub:** ارفع الملفات (بدون `.env`).
5. **Render:** New → Web Service → اختر الريبو
   - Build: `pip install -r requirements.txt`
   - Start: `python main.py`
   - Plan: Free
   - Environment: `DISCORD_TOKEN` ، `MONGO_URI` ، `PYTHON_VERSION=3.11.9`
6. **UptimeRobot:** New Monitor → HTTP(s) → رابط Render → كل 5 دقايق.
7. **رتبة البوت** لازم تكون أعلى من الرتب اللي يديرها.

## الإعداد الأول داخل السيرفر
`/setup welcome` • `/setup goodbye` • `/setup autorole` • `/logs set` • `/ticket setup` • `/starboard setup` • `/tempvoice setup` • `/automod antilink`

## تشغيل محلي
نسخ `.env.example` إلى `.env` وتعبئته ثم: `pip install -r requirements.txt` و `python main.py`
