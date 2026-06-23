from django.contrib import admin
from .models import NavSection, IngestedDocument, PageContent, VisitorFeedback, ChatPrompt


@admin.register(IngestedDocument)
class IngestedDocumentAdmin(admin.ModelAdmin):
    # Columns to display in the list view
    list_display = ('display_name', 'chunk_count', 'ingested_at', 'filename')

    # Adding a search bar for quick lookups
    search_fields = ('display_name', 'filename')

    # Adding a sidebar filter for dates
    list_filter = ('ingested_at',)

    # Making certain fields read-only (optional, but good for metadata)
    readonly_fields = ('ingested_at', 'chunk_count')

    # Organizing the detail view into sections
    fieldsets = (
        ('Document Info', {
            'fields': ('display_name', 'filename', 'file_path')
        }),
        ('Metadata', {
            'fields': ('chunk_count', 'ingested_at'),
        }),
    )


@admin.register(NavSection)
class NavSectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'order', 'slug', 'is_dynamic', 'is_published', 'url_name')
    list_display_links = ('name',)
    list_editable = ('order', 'is_published')
    list_filter = ('is_dynamic', 'is_published')
    ordering = ('order',)


@admin.register(PageContent)
class PageContentAdmin(admin.ModelAdmin):
    list_display = ('slug', 'updated_at', 'updated_by')
    readonly_fields = ('updated_at', 'updated_by')
    ordering = ('slug',)


@admin.register(VisitorFeedback)
class VisitorFeedbackAdmin(admin.ModelAdmin):
    list_display  = ('submitted_at', 'feedback_type', 'sentiment', 'rating', 'short_text', 'linked_prompt', 'page_url', 'session_key')
    list_filter   = ('feedback_type', 'sentiment', 'rating', 'submitted_at')
    search_fields = ('feedback_text', 'session_key', 'page_url')
    readonly_fields = ('submitted_at', 'session_key')
    raw_id_fields = ('chat_prompt',)
    ordering      = ('-submitted_at',)

    @admin.display(description='Feedback (preview)')
    def short_text(self, obj):
        return obj.feedback_text[:80] + ('…' if len(obj.feedback_text) > 80 else '')

    @admin.display(description='Linked prompt')
    def linked_prompt(self, obj):
        if obj.chat_prompt_id:
            return f"#{obj.chat_prompt_id}: {obj.chat_prompt.prompt[:60]}…"
        return '—'


@admin.register(ChatPrompt)
class ChatPromptAdmin(admin.ModelAdmin):
    list_display  = ('asked_at', 'session_key', 'short_prompt', 'page_url')
    list_filter   = ('asked_at',)
    search_fields = ('prompt', 'response', 'session_key')
    readonly_fields = ('asked_at', 'session_key')
    ordering      = ('-asked_at',)

    @admin.display(description='Prompt (preview)')
    def short_prompt(self, obj):
        return obj.prompt[:80] + ('…' if len(obj.prompt) > 80 else '')
