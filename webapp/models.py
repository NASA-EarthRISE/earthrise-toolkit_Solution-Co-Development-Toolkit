from django.conf import settings
from django.db import models


class PageContent(models.Model):
    slug = models.SlugField(max_length=120, unique=True)
    html_content = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='page_edits'
    )

    def __str__(self):
        return f"PageContent({self.slug})"


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