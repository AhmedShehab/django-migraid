from django.db import models


class Article(models.Model):
    title = models.CharField(max_length=200)

    class Meta:
        app_label = "testapp"
