"""Template helpers for the new UI (category icons, initials, cache-busting)."""
import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static as static_url

register = template.Library()


@register.simple_tag
def static_v(path):
    """
    คืน URL ของไฟล์ static พร้อมพารามิเตอร์ ?v=<เวลาที่แก้ไขไฟล์>
    เพื่อบังคับให้เบราว์เซอร์โหลดใหม่ทุกครั้งที่ไฟล์เปลี่ยน (กัน CSS/JS ค้างแคช).
    """
    url = static_url(path)
    abs_path = finders.find(path)
    if abs_path:
        try:
            return f"{url}?v={int(os.path.getmtime(abs_path))}"
        except OSError:
            pass
    return url

# ชื่อประเภทงาน → ไอคอน Bootstrap Icons (ตรงกับดีไซน์ใหม่)
_EXACT = {
    "ไฟฟ้า": "bi-lightning-charge",
    "ประปา": "bi-droplet",
    "เครื่องปรับอากาศ": "bi-snow",
    "คอมพิวเตอร์ & เครือข่าย": "bi-pc-display",
    "คอมพิวเตอร์และเครือข่าย": "bi-pc-display",
    "เฟอร์นิเจอร์": "bi-hammer",
    "อาคารสถานที่": "bi-building",
}

# จับคู่จากคำสำคัญ เผื่อชื่อประเภทไม่ตรงเป๊ะกับตารางด้านบน
_KEYWORDS = [
    (("ไฟฟ้า", "ไฟ", "ปลั๊ก", "หลอด"), "bi-lightning-charge"),
    (("ประปา", "น้ำ", "ก๊อก", "ท่อ", "ชักโครก", "สุขา"), "bi-droplet"),
    (("แอร์", "ปรับอากาศ", "เย็น"), "bi-snow"),
    (("คอม", "เน็ต", "เครือข่าย", "ปริ้น", "พิมพ์", "โปรเจก", "อิเล็ก"), "bi-pc-display"),
    (("เฟอร์", "โต๊ะ", "เก้าอี้", "ตู้", "ไม้"), "bi-hammer"),
    (("อาคาร", "ประตู", "หน้าต่าง", "สถานที่", "ผนัง", "หลังคา", "พื้น"), "bi-building"),
]

_FALLBACK = "bi-wrench-adjustable"


@register.filter
def cat_icon(name):
    """คืนชื่อคลาสไอคอนของประเภทงานซ่อมตามชื่อ (มี fallback อัจฉริยะ)."""
    if not name:
        return _FALLBACK
    name = str(name)
    if name in _EXACT:
        return _EXACT[name]
    for words, icon in _KEYWORDS:
        if any(w in name for w in words):
            return icon
    return _FALLBACK


@register.filter
def initial(value):
    """ตัวอักษรแรกแบบตัวใหญ่ (ใช้ทำ avatar)."""
    s = (str(value) if value is not None else "").strip()
    return s[:1].upper() if s else "?"
