from django import forms

from .models import Comment, Post


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ("title", "body")
        widgets = {
            "body": forms.Textarea(attrs={"rows": 5, "placeholder": "Share your question, win, or resource…"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "title":
                field.widget.attrs["class"] = (
                    "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm "
                    "outline-none focus:border-brand focus:ring-1 focus:ring-brand"
                )


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ("body",)
        widgets = {
            "body": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Add a reply…",
                "class": "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm "
                "outline-none focus:border-brand focus:ring-1 focus:ring-brand",
            }),
        }
