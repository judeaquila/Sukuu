from django import forms

from .models import Course, Lesson, Material, Module


class BootstrapFormMixin:
    """Applies the platform's standard Tailwind styling to every widget.

    Checkboxes and file inputs keep their own look; declared fields that
    already carry a width class (e.g. the narrow order input) keep it.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name in ("cover_image",) or name.endswith("_file") or name == "file":
                continue
            if isinstance(field.widget, forms.CheckboxInput):
                continue
            css = field.widget.attrs.get("class", "")
            width = "" if any(c.startswith("w-") for c in css.split()) else "w-full"
            field.widget.attrs["class"] = (
                f"{css} {width} rounded-lg border border-gray-300 px-3 py-2 text-sm "
                "outline-none focus:border-brand focus:ring-1 focus:ring-brand"
            ).strip()


class CourseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Course
        fields = ("title", "summary", "description", "category", "level", "cover_image",
                  "price", "original_price", "status")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["price"].help_text = (
            "In GHS (cedis). Leave 0 for a free course. "
            "Use the discount calculator below to set old/new prices."
        )
        self.fields["original_price"].help_text = (
            "The old price shown crossed out. Leave empty unless you're running a promo."
        )

    def clean(self):
        data = super().clean()
        price = data.get("price")
        original_price = data.get("original_price")
        if price and original_price and original_price <= price:
            self.add_error(
                "original_price",
                "The old (compare-at) price must be higher than the new selling price.",
            )
        return data


class ModuleForm(BootstrapFormMixin, forms.ModelForm):
    order = forms.IntegerField(
        required=False, min_value=1,
        widget=forms.NumberInput(attrs={"min": 1, "class": "w-24"}),
        help_text="Position in the curriculum (1 = first).",
    )

    class Meta:
        model = Module
        fields = ("title",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["order"].initial = self.instance.order
        else:
            self.fields["order"].help_text = "Leave blank to add it last."

    def save(self, commit=True):
        module = super().save(commit=False)
        order = self.cleaned_data.get("order")
        if order:
            module.order = order
        elif not module.pk:
            module.order = 0  # model auto-assigns "last"
        if commit:
            module.save()
        return module


class LessonForm(BootstrapFormMixin, forms.ModelForm):
    order = forms.IntegerField(
        required=False, min_value=1,
        widget=forms.NumberInput(attrs={"min": 1, "class": "w-24"}),
        help_text="Position inside the module (1 = first).",
    )
    duration_minutes = forms.DecimalField(
        required=False, min_value=0.01, max_digits=8, decimal_places=2,
        label="Duration (minutes)",
        widget=forms.NumberInput(attrs={"step": "any", "class": "w-32"}),
        help_text="Rough length of the video/audio, e.g. 7.5 — totals show on the course page.",
        error_messages={
            "invalid": "Enter the duration in minutes, e.g. 7.5.",
            "max_decimal_places": "Use at most 2 decimal places, e.g. 7.5 or 7.25.",
        },
    )

    class Meta:
        model = Lesson
        fields = (
            "module", "title", "video_url", "video_file", "audio_file", "duration_minutes",
            "content", "is_free_preview",
        )
        widgets = {
            "content": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, course=None, **kwargs):
        super().__init__(*args, **kwargs)
        if course is not None:
            self.fields["module"].queryset = Module.objects.filter(course=course)
        if self.instance and self.instance.pk:
            self.fields["order"].initial = self.instance.order
            if self.instance.duration_seconds:
                self.fields["duration_minutes"].initial = round(self.instance.duration_seconds / 60, 2)
        else:
            self.fields["order"].help_text = "Leave blank to add it last in the module."

    def save(self, commit=True):
        lesson = super().save(commit=False)
        order = self.cleaned_data.get("order")
        if order:
            lesson.order = order
        elif not lesson.pk:
            lesson.order = 0  # model auto-assigns "last"
        minutes = self.cleaned_data.get("duration_minutes")
        lesson.duration_seconds = int(round(float(minutes) * 60)) if minutes else None
        if commit:
            lesson.save()
        return lesson


class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields = ("title", "file")
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm "
                    "outline-none focus:border-brand focus:ring-1 focus:ring-brand"
                }
            ),
        }
