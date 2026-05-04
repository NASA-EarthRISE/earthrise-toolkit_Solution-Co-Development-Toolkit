from django.db import models


class NavSection(models.Model):
    order = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=120)
    url_name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    desc = models.TextField(blank=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.name
