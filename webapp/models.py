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


class IngestedDocument(models.Model):
    display_name = models.CharField(max_length=500)
    filename     = models.CharField(max_length=500)
    file_path    = models.CharField(max_length=1000, unique=True)
    chunk_count  = models.IntegerField(default=0)
    ingested_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_name']

    def __str__(self):
        return self.display_name