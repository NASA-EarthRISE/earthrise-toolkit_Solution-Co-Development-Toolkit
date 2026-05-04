from django.urls import path
from . import views

app_name = 'webapp'

urlpatterns = [
    path('', views.home, name='home'),
    path('introduction/', views.introduction, name='introduction'),
    path('designing-for-impact/', views.designing_for_impact, name='designing_for_impact'),
    path('capturing-communicating-impact/', views.capturing_communicating_impact, name='capturing_communicating_impact'),
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
]
