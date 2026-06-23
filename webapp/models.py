from django.conf import settings
from django.db import models


class VisitorFeedback(models.Model):
    """Anonymous qualitative feedback and issue reports submitted via the chat widget."""

    FEEDBACK_TYPES = [
        ('general',    'General feedback'),
        ('chat_issue', 'Chat issue'),
        ('bug_report', 'Bug report'),
    ]

    SENTIMENT_CHOICES = [
        ('up',   'Thumbs up'),
        ('down', 'Thumbs down'),
    ]

    session_key   = models.CharField(max_length=40, db_index=True, blank=True)
    submitted_at  = models.DateTimeField(auto_now_add=True)
    feedback_type = models.CharField(max_length=20, choices=FEEDBACK_TYPES, default='general')
    rating        = models.PositiveSmallIntegerField(null=True, blank=True)  # 1–5
    feedback_text = models.TextField(blank=True)
    page_url      = models.CharField(max_length=500, blank=True)
    sentiment     = models.CharField(max_length=4, choices=SENTIMENT_CHOICES, null=True, blank=True)
    chat_prompt   = models.ForeignKey(
        'ChatPrompt', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='response_feedback',
    )

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"[{self.get_feedback_type_display()}] {self.submitted_at:%Y-%m-%d %H:%M}"


class ChatPrompt(models.Model):
    """Record of every user prompt and AI response, keyed to an anonymous session."""

    session_key = models.CharField(max_length=40, db_index=True, blank=True)
    asked_at    = models.DateTimeField(auto_now_add=True)
    prompt      = models.TextField()
    response    = models.TextField(blank=True)
    page_url    = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['-asked_at']

    def __str__(self):
        return f"[{self.session_key[:8]}…] {self.asked_at:%Y-%m-%d %H:%M}"


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
    order        = models.PositiveSmallIntegerField(default=0)
    name         = models.CharField(max_length=120)
    url_name     = models.CharField(max_length=120, blank=True)
    slug         = models.SlugField(max_length=120, unique=True)
    desc         = models.TextField(blank=True)
    is_dynamic   = models.BooleanField(default=False)
    is_published = models.BooleanField(default=False)

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