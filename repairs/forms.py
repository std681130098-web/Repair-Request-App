"""Forms for the repair-request system (Bootstrap-styled)."""
from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Assignment, Rating, RepairRequest, User


class BootstrapMixin:
    """เติมคลาส Bootstrap ให้ทุก field อัตโนมัติ."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class SignUpForm(BootstrapMixin, UserCreationForm):
    """สมัครสมาชิกสำหรับ 'ผู้แจ้งซ่อม' (บทบาทอื่นสร้างผ่านผู้ดูแล)."""

    first_name = forms.CharField(label="ชื่อ-นามสกุล", max_length=150)
    phone = forms.CharField(label="เบอร์โทรศัพท์", max_length=20, required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "phone")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.REPORTER
        if commit:
            user.save()
        return user


class RepairRequestForm(BootstrapMixin, forms.ModelForm):
    """ฟอร์มแจ้งซ่อม / แก้ไขใบแจ้งซ่อม."""

    class Meta:
        model = RepairRequest
        fields = ("category", "title", "detail", "location")
        widgets = {
            "detail": forms.Textarea(attrs={"rows": 4}),
            "title": forms.TextInput(attrs={"placeholder": "เช่น แอร์ห้อง 201 ไม่เย็น"}),
            "location": forms.TextInput(attrs={"placeholder": "เช่น อาคาร 3 ห้อง 201"}),
        }


class AssignForm(BootstrapMixin, forms.Form):
    """ผู้ดูแลเลือกช่างเพื่อมอบหมายงาน."""

    technician = forms.ModelChoiceField(
        label="เลือกช่างผู้รับผิดชอบ",
        queryset=User.objects.filter(role=User.Role.TECHNICIAN, is_active=True),
        empty_label="— เลือกช่าง —",
    )
    note = forms.CharField(
        label="หมายเหตุ (ถ้ามี)", max_length=255, required=False,
        widget=forms.TextInput(attrs={"placeholder": "รายละเอียดเพิ่มเติมถึงช่าง"}),
    )


class WorkLogForm(BootstrapMixin, forms.ModelForm):
    """ช่างบันทึกผลการซ่อม."""

    class Meta:
        model = Assignment
        fields = ("work_detail",)
        widgets = {
            "work_detail": forms.Textarea(
                attrs={"rows": 4, "placeholder": "อธิบายการซ่อม อะไหล่ที่ใช้ ฯลฯ"}
            ),
        }


class ReturnForm(BootstrapMixin, forms.Form):
    """ผู้ดูแลตีกลับใบแจ้งซ่อมพร้อมเหตุผล."""

    reason = forms.CharField(
        label="เหตุผลที่ตีกลับ",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "ระบุสิ่งที่ต้องแก้ไข"}),
    )


class RatingForm(BootstrapMixin, forms.ModelForm):
    """ผู้แจ้งซ่อมประเมินความพึงพอใจ."""

    class Meta:
        model = Rating
        fields = ("score", "comment")
        widgets = {
            "score": forms.RadioSelect,
            "comment": forms.Textarea(attrs={"rows": 3, "placeholder": "ความคิดเห็นเพิ่มเติม"}),
        }
