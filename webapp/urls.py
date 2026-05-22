from django.urls import path

from . import views
from .views import api_message, api_message_stream, api_chat_upload, api_clear_chat, save_page_content
from .views_upload import upload_page, upload_file

app_name = 'webapp'

urlpatterns = [
    path('', views.home, name='home'),
    path('introduction/', views.introduction, name='introduction'),
    path('designing-for-impact/', views.designing_for_impact, name='designing_for_impact'),
    path('capturing-communicating-impact/', views.capturing_communicating_impact,
         name='capturing_communicating_impact'),
    path('economic-impact-assessments/', views.economic_impact_assessments, name='economic_impact_assessments'),
    path('stakeholder-mapping/', views.stakeholder_mapping, name='stakeholder_mapping'),
    path('needs-assessment/', views.needs_assessment, name='needs_assessment'),
    path('information-chain-analysis/', views.information_chain_analysis, name='information_chain_analysis'),
    path('user-centered-design/', views.user_centered_design, name='user_centered_design'),
    path('technical-requirements/', views.technical_requirements, name='technical_requirements'),
    path('data-governance/', views.data_governance, name='data_governance'),
    path('implementation-monitoring/', views.implementation_monitoring, name='implementation_monitoring'),
    path('adoption-sustainability/', views.adoption_sustainability, name='adoption_sustainability'),
    path('meaningful-metrics/', views.meaningful_metrics, name='meaningful_metrics'),
    path('authors-and-contributors/', views.authors, name='authors'),

    # Dynamic pages (staff-created)
    path('tools/<slug:slug>/', views.dynamic_page, name='dynamic_page'),

    path("api/message", api_message, name="api_message"),
    path("api/stream", api_message_stream, name="api_message_stream"),
    path("api/chat-upload", api_chat_upload, name="api_chat_upload"),
    path("api/clear-chat", api_clear_chat, name="api_clear_chat"),
    path("api/save-page-content", save_page_content, name="save_page_content"),
    path("api/create-page", views.api_create_page, name="api_create_page"),
    path("api/publish-page/<slug:slug>", views.api_publish_page, name="api_publish_page"),
    path("api/delete-page/<slug:slug>", views.api_delete_page, name="api_delete_page"),

    # Admin upload GUI (staff only)
    path("upload", upload_page, name="upload"),
    path("upload_file", upload_file, name="upload_file"),
]
