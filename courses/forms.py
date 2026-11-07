from django import forms

from .models import Course, Lesson, Material, Module


class BootstrapFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name in ("cover_image",) or name.endswith("_file") or name == "file":
                continue
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} w-full rounded-lg border-gray-300 focus:border-green-600 focus:ring-green-600".strip()


class CourseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Course
        fields = ("title", "summary", "description", "category", "level", "cover_image", "price", "status")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["price"].help_text = "In GHS (cedis). Leave 0 for a free course."


class ModuleForm(BootstrapFormMixin, forms.ModelForm):
    order = forms.IntegerField(
        required=False, min_value=1,
        widget=forms.NumberInput(attrs={"min": 1, "class": "w-24 rounded-lg border-gray-300"}),
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
        widget=forms.NumberInput(attrs={"min": 1, "class": "w-24 rounded-lg border-gray-300"}),
        help_text="Position inside the module (1 = first).",
    )

    class Meta:
        model = Lesson
        fields = (
            "module", "title", "video_url", "video_file", "audio_file",
            "content", "is_free_preview",
        )
        widgets = {
            "content": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, course=None, **kwargs):
        super().__init__(*args, **kwargs)
        if course is not None:
            self.fields["module"].queryset = Module.objects.filter(course=course)
        self.fields["module"].widget.attrs["class"] += " w-full rounded-lg border-gray-300"
        if self.instance and self.instance.pk:
            self.fields["order"].initial = self.instance.order
        else:
            self.fields["order"].help_text = "Leave blank to add it last in the module."

    def save(self, commit=True):
        lesson = super().save(commit=False)
        order = self.cleaned_data.get("order")
        if order:
            lesson.order = order
        elif not lesson.pk:
            lesson.order = 0  # model auto-assigns "last"
        if commit:
            lesson.save()
        return lesson


class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields = ("title", "file")
        widgets = {
            "title": forms.TextInput(
                attrs={"class": "w-full rounded-lg border-gray-300 focus:border-green-600 focus:ring-green-600"}
            ),
        }
