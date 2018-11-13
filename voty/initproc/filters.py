import django_filters
from django import forms
from django.conf import settings
from .models import Policy

from .models import Policy


class PolicyFilter(django_filters.FilterSet):
    state = django_filters.MultipleChoiceFilter(choices=settings.PLATFORM_POLICY_STATE_LIST, widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = Policy
        fields = ['state']
