from django.contrib import admin
from .models import NavSection


@admin.register(NavSection)
class NavSectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'order', 'slug', 'url_name')
    list_display_links = ('name',)
    list_editable = ('order',)
    ordering = ('order',)
