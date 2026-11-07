from django.apps import AppConfig


class CommunityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "community"

    def ready(self):
        from django.db.models.signals import post_save

        from courses.models import Course

        def create_community_for_course(sender, instance, created, **kwargs):
            if created:
                from community.models import Community

                Community.objects.get_or_create(
                    course=instance,
                    defaults={"name": f"{instance.title} — Community", "description": instance.summary},
                )

        post_save.connect(create_community_for_course, sender=Course, dispatch_uid="community_for_course")
