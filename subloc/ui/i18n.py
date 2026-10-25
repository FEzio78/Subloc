"""Interface language. English is written in the code; Arabic comes from the table below.

- tr("text {n}", n=3)  for dynamic and custom-drawn text,
- translate_tree(widget) translates static texts (labels, buttons, menus, combo items, tooltips) once a
  screen is built, so plain widget code stays plain.
In Arabic the whole interface is mirrored right-to-left (QApplication layout direction).
"""

from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QMenu, QPushButton, QWidget

LANG = "en"
UI_LANGS = [("en", "English"), ("ar", "العربية")]


def set_language(code: str) -> None:
    global LANG
    LANG = code if code in dict(UI_LANGS) else "en"


def rtl() -> bool:
    return LANG == "ar"


def tr(text: str, **values) -> str:
    out = AR.get(text, text) if LANG == "ar" else text
    return out.format(**values) if values else out


def translate_tree(root: QWidget) -> None:
    if LANG == "en":
        return
    widgets = [root, *root.findChildren(QWidget)]
    for w in widgets:
        if w.toolTip():
            w.setToolTip(tr(w.toolTip()))
        if isinstance(w, QLabel) and w.text():
            w.setText(tr(w.text()))
        elif isinstance(w, QAbstractButton) and w.text():
            w.setText(tr(w.text()))
            if isinstance(w, QPushButton) and w.menu():
                _menu(w.menu())
        elif isinstance(w, QComboBox):
            for i in range(w.count()):
                w.setItemText(i, tr(w.itemText(i)))
        elif isinstance(w, QLineEdit) and w.placeholderText():
            w.setPlaceholderText(tr(w.placeholderText()))
        if w.isWindow() and w.windowTitle():
            w.setWindowTitle(tr(w.windowTitle()))


def _menu(menu: QMenu) -> None:
    for a in menu.actions():
        if a.text():
            a.setText(tr(a.text()))


AR: dict[str, str] = {
    # ---- top bar / navigation
    "Home": "الرئيسية",
    "Queue": "قائمة الانتظار",
    "Queue  {n}": "قائمة الانتظار  {n}",
    "Settings": "الإعدادات",
    "Checking translator…": "جارٍ التحقق من المترجم…",
    "Translator ready · {model}": "المترجم جاهز · {model}",
    "LM Studio isn't running — start its server": "LM Studio لا يعمل — شغّل الخادم",
    "LM Studio is on — load a model": "LM Studio يعمل — حمّل نموذجًا",
    "The translator isn't reachable — check Settings": "تعذّر الوصول إلى المترجم — راجع الإعدادات",
    # ---- home
    "New project": "مشروع جديد",
    "Drop a video or a folder here": "أفلت مقطع فيديو أو مجلدًا هنا",
    "or click to choose · MP4 · MKV · AVI · MOV · WEBM": "أو انقر للاختيار · MP4 · MKV · AVI · MOV · WEBM",
    "Choose video…": "اختر فيديو…",
    "Choose folder…": "اختر مجلدًا…",
    "Choose a folder": "اختر مجلدًا",
    "Choose videos": "اختر مقاطع الفيديو",
    "Recent projects": "المشاريع الأخيرة",
    "{n} videos": "عدد المقاطع: {n}",
    "Videos you open are listed here, so you can come back to them any time.":
        "تظهر هنا مقاطع الفيديو التي تفتحها، لتعود إليها متى شئت.",
    "{p}% translated": "تُرجم {p}%",
    "Not translated yet": "لم يُترجم بعد",
    "Not started": "لم يبدأ بعد",
    "File not found": "الملف غير موجود",
    "Working…": "جارٍ العمل…",
    "Today {t}": "اليوم {t}",
    "Yesterday {t}": "أمس {t}",
    "Open": "فتح",
    "Show in folder": "إظهار في المجلد",
    "Remove from list": "إزالة من القائمة",
    # ---- queue: when it's done
    "When it's done:": "عند الانتهاء:",
    "Do nothing": "لا شيء",
    "Sleep": "السكون",
    "Shut down": "إيقاف التشغيل",
    "What the PC does once every video in the queue is finished": "ما يفعله الجهاز بعد انتهاء كل مقاطع القائمة",
    "Remove from queue": "إزالة من قائمة الانتظار",
    "Queue finished": "انتهت قائمة الانتظار",
    "{d} videos done · {f} failed": "المكتملة: {d} · المتعذّرة: {f}",
    "All {d} videos are done.": "اكتملت كل المقاطع ({d}).",
    "Subloc · queue: {d} of {n} finished": "Subloc · قائمة الانتظار: انتهى {d} من {n}",
    "The queue is done. The PC will go to sleep in {n} seconds.":
        "انتهت قائمة الانتظار. سيدخل الجهاز في وضع السكون بعد {n} ثانية.",
    "The queue is done. The PC will shut down in {n} seconds.": "انتهت قائمة الانتظار. سيُطفأ الجهاز بعد {n} ثانية.",
    "Sleep now": "السكون الآن",
    "Shut down now": "إيقاف التشغيل الآن",
    "Subtitles ready": "الترجمة جاهزة",
    # ---- busy (the command line or an agent is using the graphics card)
    "the queue": "قائمة الانتظار",
    "Subloc is busy": "Subloc مشغول",
    "Another Subloc is working: {who}. Try again when it's done.":
        "نسخة أخرى من Subloc تعمل الآن: {who}. أعد المحاولة بعد انتهائها.",
    "the command line": "سطر الأوامر",
    # ---- toasts
    "Saved: {name}": "تم الحفظ: {name}",
    "Added {n} videos to the queue": "أُضيفت المقاطع إلى قائمة الانتظار ({n})",
    "Those videos are already in the queue": "هذه المقاطع موجودة في قائمة الانتظار بالفعل",
    "Removed from the library. Nothing was deleted from your disk.": "أُزيل من المكتبة. لم يُحذف أي شيء من القرص.",
    "{folder}: {n} videos found": "{folder}: عدد المقاطع {n}",
    # ---- keyboard shortcuts
    "Keyboard shortcuts": "اختصارات لوحة المفاتيح",
    "Open a video": "فتح مقطع فيديو",
    "Open a folder": "فتح مجلد",
    "Play or pause (on a video)": "تشغيل أو إيقاف مؤقت (في صفحة المقطع)",
    "Start the video or the queue": "بدء المقطع أو قائمة الانتظار",
    "Search the library": "البحث في المكتبة",
    "Read the library folders again": "إعادة قراءة مجلدات المكتبة",
    "Back to Home (from a video)": "العودة إلى الرئيسية (من صفحة المقطع)",
    "Space": "مسافة",
    "Close": "إغلاق",
    # ---- settings: animation, about, updates
    "Opening animation": "الحركة الافتتاحية",
    "The short logo animation when Subloc starts. A click skips it.": "حركة الشعار القصيرة عند فتح Subloc. النقر يتخطاها.",
    "On": "تشغيل",
    "Version {v}": "الإصدار {v}",
    "Free and open source (GPL-3.0). Your videos and subtitles never leave this computer.":
        "مجاني ومفتوح المصدر (GPL-3.0). لا تغادر مقاطعك وترجماتها هذا الجهاز أبدًا.",
    "Opens the project page on GitHub": "يفتح صفحة المشروع على GitHub",
    "Licences": "التراخيص",
    "The licences of Subloc and of what it uses": "تراخيص Subloc وما يستخدمه",
    "Check for updates": "البحث عن تحديثات",
    "Only when I ask": "عندما أطلب فقط",
    "Once a day at start-up": "مرة يوميًا عند التشغيل",
    "Asks GitHub whether a newer Subloc exists. Nothing else is sent.": "يسأل GitHub إن كان هناك إصدار أحدث من Subloc. لا يُرسل أي شيء آخر.",
    "Update now": "حدّث الآن",
    "Update Subloc": "تحديث Subloc",
    "Download Subloc {v} ({n} MB) and install it?": "تنزيل Subloc {v} ({n} ميغابايت) وتثبيته؟",
    "Subloc closes, updates and opens again. Your settings, models and projects are kept.": "سيُغلق Subloc ويُحدَّث ثم يفتح من جديد. تبقى إعداداتك ونماذجك ومشاريعك.",
    "What's new": "ما الجديد",
    "Later": "لاحقًا",
    "Downloading Subloc {v}…": "جارٍ تنزيل Subloc {v}…",
    "Downloading {n}…": "جارٍ التنزيل {n}…",
    "Couldn't update": "تعذّر التحديث",
    "Installing the update… Subloc opens again in a moment.": "جارٍ تثبيت التحديث… سيفتح Subloc بعد لحظات.",
    "Subloc is still working. Let it finish or stop it, then update.": "ما زال Subloc يعمل. انتظر حتى ينتهي أو أوقفه، ثم حدّث.",
    "Another Subloc is working ({who}). Update when it's done.": "نسخة أخرى من Subloc تعمل ({who}). حدّث عندما تنتهي.",
    "Another Subloc window is open. Close it, then update.": "توجد نافذة أخرى من Subloc مفتوحة. أغلقها ثم حدّث.",
    "Asks GitHub for the newest version, only when you press it.": "يسأل GitHub عن أحدث إصدار، فقط عند الضغط.",
    "Checking for updates…": "جارٍ البحث عن تحديثات…",
    "Couldn't reach GitHub. Check the internet connection.": "تعذّر الوصول إلى GitHub. تحقّق من الاتصال بالإنترنت.",
    "Subloc {v} is available.": "يتوفّر Subloc {v}.",
    "Download": "تنزيل",
    "You have the latest version ({v}).": "لديك أحدث إصدار ({v}).",
    # ---- library
    "Library": "المكتبة",
    "Translation": "الترجمة",
    "Search": "بحث",
    "All": "الكل",
    "Untranslated": "غير المترجمة",
    "Watch for changes": "متابعة التغييرات",
    "Update the list by itself when videos are added, removed or renamed in these folders. Network drives may "
    "not report changes.":
        "تحديث القائمة تلقائيًا عند إضافة مقاطع أو حذفها أو إعادة تسميتها في هذه المجلدات. قد لا تُبلغ أقراص الشبكة "
        "عن التغييرات.",
    "Refresh": "تحديث",
    "Read every library folder again": "إعادة قراءة كل مجلدات المكتبة",
    "Add folder…": "إضافة مجلد…",
    "Add your video folders": "أضف مجلدات الفيديو",
    "Point Subloc at the folders where you keep movies, series or anime. It finds every video inside them, in all "
    "subfolders, and shows which ones still need subtitles.":
        "حدّد لـ Subloc المجلدات التي تحفظ فيها الأفلام أو المسلسلات أو الأنمي، فيجد كل مقطع فيها وفي مجلداتها "
        "الفرعية، ويُظهر ما يحتاج منها إلى ترجمة.",
    "Choose a library folder": "اختر مجلدًا للمكتبة",
    "Name": "الاسم",
    "Subtitles": "الترجمة",
    "Length": "المدة",
    "{n} videos · {d} done": "المقاطع: {n} · المكتملة: {d}",
    "{d} of {n} done": "{d} من {n} مكتملة",
    "No videos found": "لا توجد مقاطع",
    "Has {lang} subtitles": "توجد ترجمة باللغة {lang}",
    "Has subtitles": "توجد ترجمة",
    "No subtitles": "بلا ترجمة",
    "Everything": "المكتبة كلها",
    "{where} · {d} of {n} done": "{where} · {d} من {n} مكتملة",
    "Translate": "ترجمة",
    "Translate {n} untranslated": "ترجمة غير المترجمة ({n})",
    "Refresh this folder": "تحديث هذا المجلد",
    "Remove from library": "إزالة من المكتبة",
    "Remove from library?": "إزالة من المكتبة؟",
    "{folder} won't be listed any more. Nothing is deleted from your disk.":
        "لن يظهر {folder} في المكتبة بعد الآن. لن يُحذف أي شيء من القرص.",
    "Already in the library": "موجود في المكتبة",
    "{folder} is inside a folder that's already in the library.": "{folder} داخل مجلد موجود في المكتبة بالفعل.",
    "Folder not found": "المجلد غير موجود",
    "{folder} can't be reached. Is the drive connected?": "تعذّر الوصول إلى {folder}. هل القرص موصول؟",
    "Reading {folder}…": "جارٍ قراءة {folder}…",
    "Reading {folder}… {n} videos found": "جارٍ قراءة {folder}… المقاطع حتى الآن: {n}",
    "Checking the subtitles inside new videos… {n} of {total}":
        "جارٍ فحص الترجمات داخل المقاطع الجديدة… {n} من {total}",
    "{name} was moved, renamed or deleted.": "نُقل الملف {name} أو أُعيدت تسميته أو حُذف.",
    "Find it…": "ابحث عنه…",
    "Find {name}": "ابحث عن {name}",
    "Spoken language": "لغة الكلام",
    "Subtitles in": "الترجمة إلى",
    "Quality": "الجودة",
    "Translator": "المترجم",
    "Detect automatically": "اكتشاف تلقائي",
    "Mixed (changes during video)": "مختلطة (تتغير أثناء المقطع)",
    "English": "الإنجليزية",
    "Best": "الأفضل",
    "Faster": "أسرع",
    "Use the model loaded in LM Studio": "النموذج المحمّل في LM Studio",
    "Loaded in LM Studio · {model}": "المحمّل في LM Studio · {model}",
    "Runs on this PC — nothing is uploaded": "يعمل على هذا الجهاز — لا يُرفع أي شيء",
    "Subtitles are saved next to your video": "تُحفظ الترجمة بجانب الفيديو",
    "Stop anytime — it picks up where it left off": "أوقف متى شئت — ويُكمل من حيث توقف",
    "No videos": "لا توجد مقاطع",
    "Those files aren't videos Subloc can read.": "هذه الملفات ليست مقاطع فيديو يستطيع Subloc قراءتها.",
    "Busy": "مشغول",
    "Wait for the current video to finish, or stop it first.": "انتظر انتهاء المقطع الحالي أو أوقفه أولًا.",
    "Can't open this file": "تعذّر فتح هذا الملف",
    # ---- job: ready
    "Make subtitles from": "مصدر الترجمة",
    "Audio track": "المسار الصوتي",
    "Listen to the speech": "الاستماع إلى الكلام",
    "Built-in subtitles: {name}": "الترجمة المدمجة: {name}",
    "Track {n}": "المسار {n}",
    "unknown language": "لغة غير معروفة",
    "Listens to the speech and writes what it hears.": "يستمع إلى الكلام ويكتب ما يسمعه.",
    "Uses the subtitles already inside this file — faster, with professional timing.":
        "يستخدم الترجمة الموجودة داخل الملف — أسرع وبتوقيت احترافي.",
    "Start": "ابدأ",
    "Try again": "أعد المحاولة",
    # ---- job: steps / progress
    "1 · Audio": "1 · الصوت",
    "2 · Listening": "2 · الاستماع",
    "2 · Subtitles": "2 · الترجمة المدمجة",
    "3 · Names": "3 · الأسماء",
    "4 · Translating": "4 · الترجمة",
    "Reading…": "جارٍ القراءة…",
    "Read": "تمت القراءة",
    "Starting…": "جارٍ البدء…",
    "Finding…": "جارٍ البحث…",
    "{n} found": "{n} اسمًا",
    "{n} lines": "{n} سطرًا",
    "Skipped": "تم التخطي",
    "Done": "تم",
    "Progress across the video": "التقدم على امتداد المقطع",
    "Translated": "تمت الترجمة",
    "Speech found": "كلام مكتشف",
    "Preview position": "موضع المعاينة",
    "about {n} min left": "بقي نحو {n} دقيقة",
    "Stopping…": "جارٍ الإيقاف…",
    "Stop": "إيقاف",
    "Watch while it works": "شاهد أثناء العمل",
    "Done in {m} min · {n} lines": "اكتمل في {m} دقيقة · {n} سطرًا",
    "Stopped. Progress is saved — press Start to continue where it left off.":
        "تم الإيقاف. حُفظ التقدم — اضغط «ابدأ» للمتابعة من حيث توقف.",
    "This file is damaged: about {p} of the sound couldn't be read. Subtitles are missing in those parts.":
        "هذا الملف تالف: تعذّرت قراءة نحو {p} من الصوت، لذا تنقص الترجمة في تلك الأجزاء.",
    # ---- job: done / review
    "Play with subtitles": "شغّل مع الترجمة",
    "Pause": "إيقاف مؤقت",
    "Open in my player": "افتح في مشغّلي",
    "Subtitle style…": "شكل الترجمة…",
    "Export": "تصدير",
    "Styled subtitles (.ass)": "ترجمة منسّقة (.ass)",
    "Save subtitles as…": "حفظ الترجمة باسم…",
    "Video with subtitles burned in…": "فيديو بترجمة مدمجة في الصورة…",
    "Show files": "إظهار الملفات",
    "Lines": "الأسطر",
    "Both": "كلاهما",
    "Original": "الأصل",
    "Arabic": "العربية",
    "Translating…": "جارٍ الترجمة…",
    "Not translated": "لم يُترجم",
    "Save": "حفظ",
    "Translate again": "أعد الترجمة",
    "Play from here": "شغّل من هنا",
    "Cancel": "إلغاء",
    "Names in this series": "الأسماء في هذا المسلسل",
    "click one to change it everywhere": "انقر اسمًا لتغييره في كل مكان",
    "Change a name": "تغيير اسم",
    "How should “{name}” be written?": "كيف يُكتب «{name}»؟",
    "Update lines": "تحديث الأسطر",
    "Translate the {n} lines with this name again so they use “{name}”?":
        "هل تريد إعادة ترجمة {n} سطرًا تحتوي هذا الاسم لتستخدم «{name}»؟",
    "Translating again…": "جارٍ إعادة الترجمة…",
    "Translating {n} lines again…": "جارٍ إعادة ترجمة {n} سطرًا…",
    "Couldn't translate": "تعذّرت الترجمة",
    "Couldn't save": "تعذّر الحفظ",
    "Save subtitles as": "حفظ الترجمة باسم",
    "Subtitles (*.srt)": "ترجمة (*.srt)",
    "Save video with subtitles": "حفظ الفيديو مع الترجمة",
    "Video (*.mp4)": "فيديو (*.mp4)",
    "Making the video with subtitles…": "جارٍ إنشاء الفيديو مع الترجمة…",
    # ---- queue
    "Add videos…": "إضافة مقاطع…",
    "Add videos": "إضافة مقاطع",
    "Clear finished": "مسح المنتهية",
    "Start queue": "ابدأ القائمة",
    "Every video is listened to first, then all are translated — names stay the same across episodes in a folder.":
        "يُستمع إلى كل المقاطع أولًا ثم تُترجم جميعها — وتبقى الأسماء موحّدة بين حلقات المجلد.",
    "Drop several videos or a whole folder on the Home screen.": "أفلت عدة مقاطع أو مجلدًا كاملًا في الشاشة الرئيسية.",
    "{n} videos · {d} done · {w} waiting": "{n} مقاطع · {d} منتهية · {w} بالانتظار",
    "Double-click a finished video to review it": "انقر نقرًا مزدوجًا على مقطع منتهٍ لمراجعته",
    "Waiting": "بالانتظار",
    "Listening…": "جارٍ الاستماع…",
    "Heard — waiting to translate": "تم الاستماع — بانتظار الترجمة",
    "Already done": "منتهٍ مسبقًا",
    "Failed": "فشل",
    "Stopped": "متوقف",
    "already has subtitles in that language": "لديه ترجمة بهذه اللغة مسبقًا",
    # ---- settings
    "Translator address": "عنوان المترجم",
    "Where LM Studio's local server runs. Leave as is unless you changed it.":
        "مكان تشغيل خادم المترجم المحلي. اتركه كما هو ما لم تغيّره.",
    "Translation speed": "سرعة الترجمة",
    "Requests sent to LM Studio at the same time. More is faster only if your graphics card has free memory.":
        "عدد الطلبات المرسلة في الوقت نفسه. الأكثر أسرع فقط إذا كانت ذاكرة بطاقة الرسوميات كافية.",
    "{n} at once": "{n} في وقت واحد",
    "{n} at once  (recommended)": "{n} في وقت واحد  (مُوصى به)",
    "Keep names consistent": "توحيد الأسماء",
    "Finds names first so each is spelled the same way in every line and episode.":
        "يجد الأسماء أولًا لتُكتب بالطريقة نفسها في كل سطر وحلقة.",
    "Speakers and voices": "المتحدثون وأصواتهم",
    "Marks who speaks each line and whether the voice is a man's or a woman's (shown in the lines). Runs on this PC after listening.":
        "يحدّد من يتكلم في كل سطر وهل الصوت لرجل أم لامرأة (يظهر في الأسطر). يعمل على هذا الجهاز بعد الاستماع.",
    "Download ({n} GB)": "تنزيل ({n} غيغابايت)",
    "Downloading…": "جارٍ التنزيل…",
    "Speakers and voices are ready. New videos get them after listening.":
        "المتحدثون وأصواتهم جاهزون. تحصل عليهم المقاطع الجديدة بعد الاستماع.",
    "Voices {n}": "الأصوات {n}",
    "Speakers…": "المتحدثون…",
    "man": "رجل",
    "woman": "امرأة",
    "to {who}": "إلى {who}",
    "Who is spoken to": "لمن يُوجَّه الكلام",
    "With speakers and voices: decides who each line is said to, for the right \"you\" (man, woman, several). Reading each scene first finds a listener for more lines but is slower and, in tests so far, not more accurate.":
        "مع المتحدثين وأصواتهم: يحدّد لمن يُقال كل سطر ليُترجَم «أنت» بالصيغة الصحيحة (رجل، امرأة، جمع). قراءة كل مشهد أولًا تجد المخاطَب في أسطر أكثر لكنها أبطأ، ولم تكن أدق في الاختبارات حتى الآن.",
    "While translating (recommended)": "أثناء الترجمة (مُوصى به)",
    "Read each scene first (slower, experimental)": "قراءة كل مشهد أولًا (أبطأ، تجريبي)",
    "Scenes {n}": "المشاهد {n}",
    "to group": "للمجموعة",
    "to a man": "لرجل",
    "to a woman": "لامرأة",
    "Spoken to:": "موجَّه إلى:",
    "a man": "رجل",
    "a woman": "امرأة",
    "several people": "عدة أشخاص",
    "Translate this line again as spoken to {who}": "ترجم هذا السطر مجددًا على أنه موجَّه إلى {who}",
    "Speakers and voices · who speaks, man or woman": "المتحدثون وأصواتهم · من يتكلم، رجل أم امرأة",
    "On (recommended)": "مفعّل (مُوصى به)",
    "Off": "معطّل",
    "Subtitle look": "شكل الترجمة",
    "Used for styled .ass subtitles and burned-in videos. Plain .srt files are always saved too.":
        "يُستخدم لملفات الترجمة المنسّقة بصيغة ASS وللفيديو بترجمة مدمجة، وتُحفظ ملفات SRT العادية دائمًا.",
    "Change…": "تغيير…",
    "Custom": "مخصص",
    "Interface language": "لغة الواجهة",
    "The app restarts its window to switch.": "تُعاد فتح النافذة لتطبيق اللغة.",
    "Subloc runs entirely on this computer. Your videos and subtitles are never uploaded.":
        "يعمل Subloc بالكامل على هذا الجهاز. لا تُرفع مقاطعك ولا ترجماتك أبدًا.",
    "Run setup again…": "أعد تشغيل الإعداد…",
    "Setup": "الإعداد",
    "Choose the language, translator and models again.": "اختر اللغة والمترجم والنماذج من جديد.",
    # ---- style dialog
    "Subtitle style": "شكل الترجمة",
    "Look": "المظهر",
    "Classic": "كلاسيكي",
    "Boxed": "بخلفية",
    "Yellow": "أصفر",
    "Large": "كبير",
    "Font": "الخط",
    "Size": "الحجم",
    "Bold": "عريض",
    "Colours": "الألوان",
    "text": "النص",
    "outline": "الحد",
    "Outline": "الحد",
    "Shadow": "الظل",
    "Box": "الخلفية",
    "Background box": "مربع خلفية",
    "Box opacity": "شفافية الخلفية",
    "Position": "الموضع",
    "Bottom": "أسفل",
    "Top": "أعلى",
    "From edge": "البعد عن الحافة",
    "Reset to Classic": "استعادة الكلاسيكي",
    "Apply": "تطبيق",
    "Check other scenes": "تحقّق من مشاهد أخرى",
    "This is exactly how VLC, MPV and burned-in videos will show it.":
        "هكذا تمامًا ستظهر في VLC وMPV وفي الفيديو بترجمة مدمجة.",
    "Open a video to preview on a real frame.": "افتح مقطعًا للمعاينة على لقطة حقيقية.",
    "Choose a colour": "اختر لونًا",
    "Preview unavailable: {e}": "المعاينة غير متاحة: {e}",
    # ---- leaving
    "Quit Subloc?": "إغلاق Subloc؟",
    "Work is still running. Progress is saved — you can continue later. Quit now?":
        "العمل ما زال جاريًا. التقدم محفوظ ويمكنك المتابعة لاحقًا. هل تريد الإغلاق الآن؟",
    # ---- setup
    "Built-in · {m}": "مدمج · {m}",
    "Your server · {url}": "خادمك · {url}",
    "Translator not installed — run Setup": "المترجم غير مثبّت — شغّل الإعداد",
    "Back": "رجوع",
    "Next": "التالي",
    "Install": "تثبيت",
    "Open Subloc": "افتح Subloc",
    "Subtitles for any video, made on your own PC.": "ترجمة لأي مقطع فيديو، تُصنع على جهازك.",
    "This short setup picks the right models for this computer. Nothing you watch is ever uploaded.":
        "يختار هذا الإعداد القصير النماذج المناسبة لجهازك. لا يُرفع أي شيء تشاهده أبدًا.",
    "Your PC": "جهازك",
    "Checking this computer…": "جارٍ فحص الجهاز…",
    "Found: {hw} · {free} GB free disk": "تم العثور على: {hw} · {free} غيغابايت متاحة على القرص",
    "Recommended for this PC": "مُوصى به لهذا الجهاز",
    "Balanced": "متوازن",
    "Light": "خفيف",
    "Speech: Whisper {m}": "التعرف على الكلام: Whisper {m}",
    "Translator: {m}": "المترجم: {m}",
    "Download: about {n} GB": "التنزيل: نحو {n} غيغابايت",
    "a 1-hour episode in about 6–10 minutes": "حلقة مدتها ساعة في نحو 6–10 دقائق",
    "a 1-hour episode in about 10–20 minutes": "حلقة مدتها ساعة في نحو 10–20 دقيقة",
    "a 1-hour episode in about 1–3 hours on a laptop processor": "حلقة مدتها ساعة في نحو 1–3 ساعات على معالج حاسوب محمول",
    "This translator needs about {n} GB of graphics memory; on this PC it will run partly on the processor and be slower.":
        "يحتاج هذا المترجم إلى نحو {n} غيغابايت من ذاكرة الرسوميات؛ وسيعمل جزئيًا على المعالج في هذا الجهاز فيكون أبطأ.",
    "No NVIDIA graphics card found: everything runs on the processor or built-in graphics. It works, just slower.":
        "لم يُعثر على بطاقة رسوميات NVIDIA: سيعمل كل شيء على المعالج أو الرسوميات المدمجة. يعمل، لكن أبطأ.",
    "Which program translates the subtitles?": "أي برنامج يترجم النصوص؟",
    "Built-in": "مدمج",
    "Recommended": "مُوصى به",
    "Subloc installs and runs the translator itself. No other app needed.": "يثبّت Subloc المترجم ويشغّله بنفسه. لا حاجة لأي برنامج آخر.",
    "Works offline after setup.": "يعمل دون إنترنت بعد الإعداد.",
    "My own server": "خادمي الخاص",
    "LM Studio, Ollama, llama.cpp or any OpenAI-compatible address.": "LM Studio أو Ollama أو llama.cpp أو أي عنوان متوافق مع OpenAI.",
    "For people who already run local models.": "لمن يشغّلون نماذج محلية مسبقًا.",
    "Use a model file I already have (.gguf)…": "استخدم ملف نموذج لديّ (gguf)…",
    "Choose a model file": "اختر ملف نموذج",
    "Server address": "عنوان الخادم",
    "Test connection": "اختبار الاتصال",
    "Enter the server address first.": "أدخل عنوان الخادم أولًا.",
    "Connecting…": "جارٍ الاتصال…",
    "Connected. Loaded model: {m}": "تم الاتصال. النموذج المحمّل: {m}",
    "Connected. {n} models available — load one in your server.": "تم الاتصال. يتوفر {n} من النماذج — حمّل أحدها في الخادم.",
    "Connected, but the server has no models.": "تم الاتصال، لكن لا توجد نماذج في الخادم.",
    "Speech recognition · Whisper {m}": "التعرف على الكلام · Whisper {m}",
    "Translator · {m}": "المترجم · {m}",
    "About {n} GB to download into {path}. Free space: {free} GB.": "نحو {n} غيغابايت للتنزيل إلى {path}. المساحة المتاحة: {free} غيغابايت.",
    "Everything needed is already on this PC.": "كل ما يلزم موجود على هذا الجهاز.",
    "Built-in translator · engine for NVIDIA cards": "المترجم المدمج · محرّك بطاقات NVIDIA",
    "NVIDIA graphics card support (CUDA)": "دعم بطاقة رسوميات NVIDIA (CUDA)",
    "Already installed": "مثبّت مسبقًا",
    "Installed": "تم التثبيت",
    "Not enough free disk space. Free at least {n} GB and try again.": "المساحة غير كافية. حرّر {n} غيغابايت على الأقل ثم أعد المحاولة.",
    "You can stop and continue later — finished parts are kept.": "يمكنك الإيقاف والمتابعة لاحقًا — تُحفظ الأجزاء المكتملة.",
    "You're all set": "كل شيء جاهز",
    "Drop a video on Subloc to make subtitles.": "أفلت مقطع فيديو في Subloc لصنع الترجمة.",
    "built-in translator ({m})": "المترجم المدمج ({m})",
    "your server at {url}": "خادمك على {url}",
    "Speech: Whisper {s} · Translation: {t}": "الكلام: Whisper {s} · الترجمة: {t}",
    # ---- language names
    "Korean": "الكورية", "Japanese": "اليابانية", "Russian": "الروسية", "Turkish": "التركية",
    "Chinese": "الصينية", "Spanish": "الإسبانية", "French": "الفرنسية", "German": "الألمانية",
    "Italian": "الإيطالية", "Portuguese": "البرتغالية", "Hindi": "الهندية", "Thai": "التايلاندية",
    "Vietnamese": "الفيتنامية", "Indonesian": "الإندونيسية", "Tagalog (Filipino)": "التاغالوغية (الفلبينية)",
    "Persian": "الفارسية", "Urdu": "الأردية", "Ukrainian": "الأوكرانية", "Polish": "البولندية",
}  # fmt: skip
