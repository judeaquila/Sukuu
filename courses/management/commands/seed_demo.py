"""
Seed the database with demo data: run `.venv\\Scripts\\python manage.py seed_demo`.
Optional: pass --admin-password to set a specific admin password.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import CreatorProfile, User
from community.models import Comment, Post
from courses.models import Course, Enrollment, Lesson, Module


class Command(BaseCommand):
    help = "Seed demo creators, courses, lessons, a student and a community post."

    def add_arguments(self, parser):
        parser.add_argument("--admin-password", default="admin123")

    def handle(self, *args, **options):
        now = timezone.now()

        # Admin
        if not User.objects.filter(is_superuser=True).exists():
            User.objects.create_superuser(
                email="admin@sukuu.gh",
                full_name="LearnSasa Admin",
                password=options["admin_password"],
            )
            self.stdout.write(self.style.SUCCESS("Created admin: admin@sukuu.gh"))

        def make_user(email, full_name, role):
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "full_name": full_name,
                    "role": role,
                },
            )
            if created:
                user.set_password("pass1234")
                user.save()
                if role == User.Role.CREATOR:
                    CreatorProfile.objects.create(
                        user=user,
                        headline=f"{full_name.split()[0]} teaches on LearnSasa",
                        bio=f"Practical [{full_name.split()[1] if len(full_name.split())>1 else 'pro'}] training for Ghanaians, by a Ghanaian.",
                    )
            return user, created

        # Creators
        kojo, _ = make_user("kojo@creator.gh", "Kojo Mensah", User.Role.CREATOR)
        ama, _ = make_user("ama@creator.gh", "Ama Owusu", User.Role.CREATOR)

        course_data = [
            {
                "creator": kojo,
                "title": "WhatsApp Business for Ghanaian Selling",
                "summary": "Turn WhatsApp into a sales machine — status ads, broadcasting, closing in Twi-friendly tone.",
                "description": "Learn how real Accra sellers use WhatsApp Business to move goods.\n\n- Free and pro account setup\n- Catalogues & broadcast lists\n- Taking payments on delivery\n- Scripts that close in pidgin & Twi",
                "category": Course.Category.BUSINESS,
                "level": Course.Level.BEGINNER,
                "price": 80,
                "modules": [
                    ("Getting set up the Ghanaian way", [
                        ("Why WhatsApp sells in Ghana", True),
                        ("Setting up catalogs that people trust", True),
                        ("Broadcast lists vs Status ads", False),
                    ]),
                    ("Closing your first 100 sales", [
                        ("Follow-up scripts in Twi & pidgin", False),
                        ("Taking MoMo payments safely", False),
                    ]),
                ],
            },
            {
                "creator": ama,
                "title": "Excel for Ghanaian Accountants",
                "summary": "From basic spreadsheets to VAT-ready reports and dashboards employers value.",
                "description": "Practical Excel for bookkeepers, cashiers and small business accountants.\n\n- Formulas, lookups, PivotTables\n- GHS payroll & VAT templates\n- Building a management dashboard",
                "category": Course.Category.TECH,
                "level": Course.Level.INTERMEDIATE,
                "price": 150,
                "modules": [
                    ("Formulas you'll use every day", [
                        ("Working with SUMIFS & lookups", True),
                        ("Dates, payroll and VAT templates", False),
                        ("PivotTables demystified", False),
                    ]),
                    ("Dashboards your boss will love", [
                        ("Building a sales dashboard from scratch", False),
                        ("Printing & sharing professional reports", False),
                    ]),
                ],
            },
            {
                "creator": kojo,
                "title": "Start Shito Making Business",
                "summary": "From family recipe to bottle-ready product — licensing, costing and selling online.",
                "description": "A food business course made for kitchens in Tema, Kumasi and Accra.\n\n- Recipe standardization & costing per bottle\n- FDA Ghana licensing, step by step\n- Selling via WhatsApp & delivery",
                "category": Course.Category.COOKING,
                "level": Course.Level.BEGINNER,
                "price": 0,
                "modules": [
                    ("Foundation", [
                        ("Your shito, standardized", True),
                        ("Costing each bottle (a gutsy walkthrough)", True),
                    ]),
                    ("Making it official", [
                        ("FDA licensing without wahala", False),
                        ("Pricing for at-home & export markets", False),
                    ]),
                ],
            },
        ]

        courses = []
        for data in course_data:
            mods = data.pop("modules")
            course, created = Course.objects.get_or_create(
                title=data["title"],
                defaults={**data, "status": Course.Status.PUBLISHED},
            )
            if created:
                for module_title, lessons in mods:
                    module = Module.objects.create(course=course, title=module_title)
                    for lesson_title, is_preview in lessons:
                        Lesson.objects.create(
                            module=module,
                            title=lesson_title,
                            is_free_preview=is_preview,
                            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                            content=(
                                "In this lesson we walk through the topic step by step, with "
                                "Ghana-specific examples you can copy today.\n"
                                "1. Watch the full video.\n"
                                "2. Open the checklist in the notes.\n"
                                "3. Post your assignment in the community for feedback."
                            ),
                        )
            course.status = Course.Status.PUBLISHED
            course.save()
            courses.append(course)

        # Demo student
        kwame, _ = make_user("kwame@student.gh", "Kwame Boateng", User.Role.STUDENT)
        Enrollment.objects.get_or_create(
            user=kwame,
            course=courses[0],
            defaults={"is_active": True, "source": "admin"},
        )

        # A few seeded community posts on the first course
        community = courses[0].community if hasattr(courses[0], "community") else None
        if community and not community.posts.exists():
            welcome = Post.objects.create(
                community=community,
                author=kojo,
                title="📌  Akwaaba! Read this first",
                body=(
                    "Welcome to the community.\n\n"
                    "House rules:\n"
                    "1. Ask questions with specifics (prices, area, product).\n"
                    "2. Share wins, screenshots & receipts — we celebrate here.\n"
                    "3. No spam; the MoMo scams teachings are NOT allowed."
                ),
                is_pinned=True,
            )
            Comment.objects.create(
                post=welcome, author=kwame, body="Done with setup already — the broadcast trick is gold! 🔥"
            )
            Post.objects.create(
                community=community,
                author=kwame,
                title="My first sale after 2 days 😭",
                body="I followed the catalog cheat sheet and closed my first customer in Shai-Osudoku. Medaase, Kojo!",
            )

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(courses)} courses, student demo & community posts."))
        self.stdout.write("Logins: creators kojo@creator.gh, ama@creator.gh; student kwame@student.gh; password: pass1234")
