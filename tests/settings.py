DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "migraid",
    "tests.testapp",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
