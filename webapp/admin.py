from django.contrib import admin
from .models import NavSection
from .models import IngestedDocument


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
    list_display = ('name', 'order', 'slug', 'url_name')
    list_display_links = ('name',)
    list_editable = ('order',)
    ordering = ('order',)
