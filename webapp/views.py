from django.shortcuts import render
from .models import NavSection


def _nav():
    return NavSection.objects.all()


def _ctx(active_slug, extra=None):
    ctx = {'nav_sections': _nav(), 'active_slug': active_slug}
    if extra:
        ctx.update(extra)
    return ctx


def home(request):
    return render(request, 'webapp/home.html', {'nav_sections': _nav(), 'active_slug': ''})


def introduction(request):
    return render(request, 'webapp/introduction.html', _ctx('introduction'))


def designing_for_impact(request):
    return render(request, 'webapp/designing_for_impact.html', _ctx('designing-for-impact'))


def capturing_communicating_impact(request):
    return render(request, 'webapp/capturing_communicating_impact.html', _ctx('capturing-communicating-impact'))


def economic_impact_assessments(request):
    return render(request, 'webapp/economic_impact_assessments.html', _ctx('economic-impact-assessments'))


def stakeholder_mapping(request):
    return render(request, 'webapp/stakeholder_mapping.html', _ctx('stakeholder-mapping'))


def needs_assessment(request):
    return render(request, 'webapp/needs_assessment.html', _ctx('needs-assessment'))


def information_chain_analysis(request):
    return render(request, 'webapp/information_chain_analysis.html', _ctx('information-chain-analysis'))


def user_centered_design(request):
    return render(request, 'webapp/user_centered_design.html', _ctx('user-centered-design'))


def technical_requirements(request):
    return render(request, 'webapp/technical_requirements.html', _ctx('technical-requirements'))


def data_governance(request):
    return render(request, 'webapp/data_governance.html', _ctx('data-governance'))


def implementation_monitoring(request):
    return render(request, 'webapp/implementation_monitoring.html', _ctx('implementation-monitoring'))


def adoption_sustainability(request):
    return render(request, 'webapp/adoption_sustainability.html', _ctx('adoption-sustainability'))


def meaningful_metrics(request):
    return render(request, 'webapp/meaningful_metrics.html', _ctx('meaningful-metrics'))


def authors(request):
    return render(request, 'webapp/authors.html', _ctx('authors'))
