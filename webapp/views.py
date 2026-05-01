from django.shortcuts import render

NAV_SECTIONS = [
    {'name': 'Introduction', 'url_name': 'webapp:introduction', 'slug': 'introduction'},
    {'name': 'Designing for Impact', 'url_name': 'webapp:designing_for_impact', 'slug': 'designing-for-impact'},
    {'name': 'Capturing & Communicating Impact', 'url_name': 'webapp:capturing_communicating_impact', 'slug': 'capturing-communicating-impact'},
    {'name': 'Economic Impact Assessments', 'url_name': 'webapp:economic_impact_assessments', 'slug': 'economic-impact-assessments'},
    {'name': 'Stakeholder Mapping & Analysis', 'url_name': 'webapp:stakeholder_mapping', 'slug': 'stakeholder-mapping'},
    {'name': 'Needs Assessment', 'url_name': 'webapp:needs_assessment', 'slug': 'needs-assessment'},
    {'name': 'Information Chain Analysis', 'url_name': 'webapp:information_chain_analysis', 'slug': 'information-chain-analysis'},
    {'name': 'User-Centered Design', 'url_name': 'webapp:user_centered_design', 'slug': 'user-centered-design'},
    {'name': 'Technical Requirements Template', 'url_name': 'webapp:technical_requirements', 'slug': 'technical-requirements'},
    {'name': 'Data Governance & Storage', 'url_name': 'webapp:data_governance', 'slug': 'data-governance'},
    {'name': 'Implementation & Monitoring Plan', 'url_name': 'webapp:implementation_monitoring', 'slug': 'implementation-monitoring'},
    {'name': 'Adoption & Sustainability Plan', 'url_name': 'webapp:adoption_sustainability', 'slug': 'adoption-sustainability'},
    {'name': 'Meaningful Metrics Development', 'url_name': 'webapp:meaningful_metrics', 'slug': 'meaningful-metrics'},
]


def _ctx(active_slug, extra=None):
    ctx = {'nav_sections': NAV_SECTIONS, 'active_slug': active_slug}
    if extra:
        ctx.update(extra)
    return ctx


def home(request):
    return render(request, 'webapp/home.html', {'nav_sections': NAV_SECTIONS, 'active_slug': ''})


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
