"""
Seed content of the WhatsApp auto menu (decided 2026-10-28), as plain data.

Read by patches/seed_auto_menu.py and checked against the WhatsApp limits by
tests/test_auto_menu_pure.py. Row titles exclude the "n. " prefix the engine
adds from `digit`. `{{business_hours}}` renders from Inbox Settings.
"""

NOTIFY_USER = "ali.s@alkhora.com"

GROUPS = [
    ("Nano Lab", ["mukhalad@alkhora.com", "info@alkhora.com"]),
    ("Medical/Lab Equipment", ["aziz@alkhora.com", "h.ghaith@alkhora.com", "gm@alkhora.com"]),
    ("Oil & Gas", ["as@alkhora.com", "ali.s@alkhora.com"]),
    ("FESTO/Warehouse", ["a.kh@alkhora.com"]),
    ("General information", ["info@alkhora.com"]),
]

TAGS = ["Nano Lab", "Medical Lab", "Oil & Gas", "FESTO", "Info", "Vendor", "Careers", "Follow-up"]

BAGHDAD = {
    "location_lat": 33.297612, "location_lng": 44.340369,
    "location_name": "ALKHORA Nano Lab — Al Yarmook",
    "location_address_ar": "اليرموك، تقاطع الأربع شوارع، بغداد",
    "location_address_en": "Al Yarmook, four-streets intersection, Baghdad",
}
ERBIL = {
    "location_lat": 36.177067, "location_lng": 44.020945,
    "location_name": "ALKHORA — Erbil branch",
    "location_address_ar": "شارع 60، الإسكان، أربيل، مجاور مطعم كباب فاروق",
    "location_address_en": "60 St., Eskan, Erbil, beside Kabab Farouq restaurant",
}


def _opt(digit, title_ar, title_en, action, **extra):
    row = {"digit": digit, "title_ar": title_ar, "title_en": title_en, "action": action,
           "sort_order": int(digit) if digit != "0" else 10}
    row.update(extra)
    return row


def _nano(**extra):
    return dict(tag="Nano Lab", assign_group="Nano Lab", **extra)


_TESTS_AR = (
    "فحوصات مختبر النانو وأسعارها (للعينة الواحدة، بالألف دينار عراقي):\n"
    "FESEM: 40 · SEM: 40 · SEM + EDS: 70 · XRD: 25 · AFM: 15 · FTIR: 10 · UV-Vis: 5 · EDX: يُسعّر مع SEM\n"
    "المختبر يقوم بالفحص فقط ولا يوفر تحضير العينات. للعينات المسحوقة يكفي نصف غرام تقريباً."
)
_TESTS_EN = (
    "Nano Lab tests and prices (per sample, thousand IQD):\n"
    "FESEM: 40 · SEM: 40 · SEM + EDS: 70 · XRD: 25 · AFM: 15 · FTIR: 10 · UV-Vis: 5 · EDX: quoted with SEM\n"
    "The lab performs the tests only; no sample preparation. For powders about half a gram is enough."
)
_SAMPLES_AR = (
    "موقع المختبر في بغداد: اليرموك، تقاطع الأربع شوارع (محلة 612، شارع 14، دار 61). "
    "أوقات العمل: من السبت إلى الخميس، 9:00 صباحاً – 4:00 عصراً. "
    "يُرجى كتابة اسمك ورقم هاتفك ونوع الفحص على كل عينة. هاتف المختبر: 07833461529"
)
_SAMPLES_EN = (
    "Lab location in Baghdad: Al Yarmook, four-streets intersection (LO612, St. 14, H. 61). "
    "Hours: Saturday to Thursday, 9:00 AM – 4:00 PM. "
    "Please label each sample with your name, phone and the test required. Lab phone: 07833461529"
)
_TURNAROUND_AR = ("النتائج عادةً خلال 1 إلى 3 أيام عمل، وقد تصل إلى أسبوع عند الازدحام. "
                  "الفحص بنفس اليوم ممكن فقط عندما يكون المختبر غير مشغول.")
_TURNAROUND_EN = ("Results usually take 1 to 3 working days, up to a week when the lab is busy. "
                  "Same-day testing is possible only when the lab is free.")
_HOURS_AR = ("الخورة — بغداد: اليرموك، تقاطع الأربع شوارع (محلة 612، شارع 14، دار 61). "
             "أوقات العمل: {{business_hours}}.")
_HOURS_EN = ("AL KHORA — Baghdad: Al Yarmook, four-streets intersection (LO612, St. 14, H. 61). "
             "Hours: {{business_hours}}.")

_MEDICAL_Q = {
    "question_ar": "الآن أرسل أسماء المواد أو أرقام الكتالوج والكميات، ويمكنك إرفاق صور أو ملف PDF.",
    "question_en": "Now send the item names or catalogue numbers and quantities. Photos or a PDF are welcome.",
}
_FESTO_Q = {
    "question_ar": "الآن أرسل رقم قطعة FESTO أو صورة للقطعة مع الكمية.",
    "question_en": "Now send the FESTO part number or a photo of the part, and the quantity.",
}
_MEDICAL = dict(tag="Medical Lab", assign_group="Medical/Lab Equipment", **_MEDICAL_Q)
_OILGAS = dict(tag="Oil & Gas", assign_group="Oil & Gas")
_FESTO = dict(tag="FESTO", assign_group="FESTO/Warehouse", **_FESTO_Q)
_INFO = "General information"

# Inserted in this order (targets are inserted with ignore_links).
MENUS = [
    {
        "menu_key": "after_location", "title_ar": "خيارات أخرى", "title_en": "Anything else?",
        "body_ar": "هل تحتاج شيئاً آخر؟", "body_en": "Anything else?",
        "options": [
            _opt("1", "فرع أربيل", "Erbil branch", "Location", target_menu="after_location", **ERBIL),
        ],
    },
    {
        "menu_key": "nano", "title_ar": "مختبر النانو", "title_en": "Nano Lab",
        "body_ar": "مختبر النانو — اختر ما تحتاجه:", "body_en": "Nano Lab — choose what you need:",
        "options": [
            _opt("1", "الفحوصات والأسعار", "Tests & prices", "Reply",
                 reply_ar=_TESTS_AR, reply_en=_TESTS_EN, **_nano()),
            _opt("2", "تسليم العينات", "Delivering samples", "Location", target_menu="after_location",
                 reply_ar=_SAMPLES_AR, reply_en=_SAMPLES_EN, **_nano(**BAGHDAD)),
            _opt("3", "مدة النتائج", "Turnaround time", "Reply",
                 reply_ar=_TURNAROUND_AR, reply_en=_TURNAROUND_EN, **_nano()),
            _opt("4", "نتائجي", "My results", "Form then handoff", **_nano(
                question_ar="ما الاسم الذي سُجّلت به العينات؟",
                question_en="What name were the samples registered under?")),
            _opt("5", "طلب فحص جديد", "Request a test", "Form then handoff", **_nano(
                question_ar="ما هي الفحوصات المطلوبة وكم عدد العينات؟ يمكنك إرسال صور أو ملف.",
                question_en="Which tests do you need and how many samples? Photos or a file are welcome.")),
        ],
    },
    {
        "menu_key": "medical", "title_ar": "أجهزة طبية ومختبرية", "title_en": "Medical & Lab Equipment",
        "body_ar": "قسم الأجهزة الطبية والمختبرية — اختر نوع الطلب:",
        "body_en": "Medical & Laboratory Equipment — choose the request type:",
        "options": [
            _opt("1", "أجهزة", "Equipment", "Form then handoff", **_MEDICAL),
            _opt("2", "كتات ومواد كيميائية", "Kits & chemicals", "Form then handoff", **_MEDICAL),
            _opt("3", "مستهلكات", "Consumables", "Form then handoff", **_MEDICAL),
        ],
    },
    {
        "menu_key": "oilgas", "title_ar": "النفط والغاز", "title_en": "Oil & Gas",
        "body_ar": "قسم النفط والغاز — اختر نوع الطلب:", "body_en": "Oil & Gas Department — choose the request type:",
        "options": [
            _opt("1", "طلب عرض سعر", "Request a quotation", "Form then handoff",
                 question_ar="الآن أرسل أرقام القطع (Part numbers) والكميات، ويمكنك إرفاق صور أو ملف PDF.",
                 question_en="Now send the part numbers and quantities. Photos or a PDF are welcome.", **_OILGAS),
            _opt("2", "التدريب والدورات", "Training courses", "Form then handoff",
                 reply_ar="الدورات الحالية: Mobius Institute Vibration Analysis — VCAT II (البصرة).",
                 reply_en="Current courses: Mobius Institute Vibration Analysis — VCAT II (Basra).",
                 question_ar="أي دورة تهمّك وفي أي مدينة؟",
                 question_en="Which course are you interested in, and in which city?", **_OILGAS),
        ],
    },
    {
        "menu_key": "festo", "title_ar": "فيستو والنيوماتك", "title_en": "FESTO & Pneumatics",
        "body_ar": "فيستو وأنظمة الهواء المضغوط — اختر نوع الطلب:", "body_en": "FESTO & Pneumatics — choose the request type:",
        "options": [
            _opt("1", "طلب عرض سعر", "Request a quotation", "Form then handoff", **_FESTO),
            _opt("2", "توفر قطعة", "Part availability", "Form then handoff", **_FESTO),
        ],
    },
    {
        "menu_key": "info", "title_ar": "معلومات عامة", "title_en": "General information",
        "body_ar": "معلومات عامة — اختر ما تحتاجه:", "body_en": "General information — choose what you need:",
        "options": [
            _opt("1", "الموقع وأوقات العمل", "Location & hours", "Location", target_menu="after_location",
                 reply_ar=_HOURS_AR, reply_en=_HOURS_EN, tag="Info", **BAGHDAD),
            _opt("2", "متابعة طلب سابق", "Follow up a request", "Form then handoff", short_form=1,
                 last_handler=1, tag="Follow-up", assign_group=_INFO,
                 question_ar="أرسل رقم العرض أو الطلب، أو الاسم الذي سُجّل به.",
                 question_en="Send the quotation or order number, or the name it was registered under."),
            _opt("3", "موردون وشراكات", "Suppliers & partners", "Auto-resolve", tag="Vendor",
                 reply_ar="شكراً لتواصلكم. يُرجى إرسال ملف الشركة والكتالوج إلى info@alkhora.com، "
                          "حيث تتم مراجعة عروض التعاون عبر البريد الإلكتروني فقط.",
                 reply_en="Thank you for reaching out. Please email your company profile and catalogue to "
                          "info@alkhora.com. Partnership proposals are reviewed by email only."),
            _opt("4", "التوظيف", "Careers", "Auto-resolve", tag="Careers",
                 reply_ar="شكراً لاهتمامك بالعمل معنا. يُرجى إرسال سيرتك الذاتية إلى career@alkhora.com.",
                 reply_en="Thank you for your interest in working with us. Please send your CV to career@alkhora.com."),
            _opt("5", "أخرى", "Other", "Form then handoff", short_form=1, tag="Info", assign_group=_INFO,
                 question_ar="كيف يمكننا مساعدتك؟", question_en="How can we help you?"),
        ],
    },
    {
        "menu_key": "root", "is_root": 1, "title_ar": "الخورة", "title_en": "AL KHORA",
        "button_ar": "اختر القسم", "button_en": "Choose",
        "body_ar": "أهلاً بك في الخورة. اختر القسم المطلوب من القائمة:",
        "body_en": "Welcome to AL KHORA. Please choose the department you need from the list:",
        "options": [
            _opt("1", "فحوصات مختبر النانو", "Nano Lab tests", "Submenu", target_menu="nano",
                 description_ar="الفحوصات والعينات الخاصة بمختبر النانو (SEM, XRD, FTIR...)",
                 description_en="Tests and samples for the Nano Lab (SEM, XRD, FTIR...)"),
            _opt("2", "أجهزة طبية ومختبرية", "Medical/Lab Equipment", "Submenu", target_menu="medical",
                 description_ar="قسم الأجهزة والمستلزمات الطبية والمختبرية",
                 description_en="Medical & Laboratory Equipment Department"),
            _opt("3", "قسم النفط والغاز", "Oil & Gas Dept.", "Submenu", target_menu="oilgas",
                 description_ar="أجهزة القياس وقطع الغيار والتدريب",
                 description_en="Oil & Gas Department: instruments, spare parts, training"),
            _opt("4", "فيستو والنيوماتك", "FESTO & Pneumatics", "Submenu", target_menu="festo",
                 description_ar="منتجات FESTO وأنظمة الهواء المضغوط",
                 description_en="FESTO products & pneumatic systems"),
            _opt("0", "معلومات عامة", "General Information", "Submenu", target_menu="info",
                 description_ar="الموقع، أوقات العمل، متابعة طلب، الموردون، التوظيف",
                 description_en="Location, hours, follow up a request, suppliers, careers"),
        ],
    },
]
ROOT_MENU = "root"
