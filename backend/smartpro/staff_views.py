from datetime import timezone

from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_naive
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError

from .command_input import command_body
from .staff import staff_command, staff_read
from .student_views import private_response


class AwareDateTime(serializers.DateTimeField):
    def to_internal_value(self, value):
        try:
            parsed = parse_datetime(value) if isinstance(value, str) else None
        except (ValueError, TypeError):
            parsed = None
        if parsed is None or is_naive(parsed):
            raise ValidationError('An ISO timestamp with timezone is required')
        return super().to_internal_value(value)


class PolicyInput(serializers.Serializer):
    expectedRevision = serializers.IntegerField(min_value=0)
    reason = serializers.CharField(allow_blank=True, default="", max_length=500)


class PublicationInput(PolicyInput):
    visibleFrom = AwareDateTime(allow_null=True)
    visibleUntil = AwareDateTime(allow_null=True)
    teamCreationEnabled = serializers.BooleanField()

    def validate(self, attrs):
        start, end = attrs['visibleFrom'], attrs['visibleUntil']
        if (start is None) != (end is None) or (start is not None and start >= end):
            raise ValidationError('Provide an ordered window or two null values to unpublish')
        return attrs


class TeamPolicyInput(PolicyInput):
    allowJoin = serializers.BooleanField()
    allowLeave = serializers.BooleanField()
    allowTransfer = serializers.BooleanField()
    minimumMembers = serializers.IntegerField(min_value=0, allow_null=True)
    maximumMembers = serializers.IntegerField(min_value=1, allow_null=True)
    sizeMode = serializers.ChoiceField(choices=['ADVISORY','ENFORCED'])

    def validate(self, attrs):
        low, high = attrs['minimumMembers'], attrs['maximumMembers']
        if low is not None and high is not None and low > high:
            raise ValidationError('Minimum cannot exceed maximum')
        return attrs


class RegistrationInput(PolicyInput):
    projectType = serializers.ChoiceField(choices=['MINI','MAJOR'])
    policyVersionId = serializers.UUIDField(allow_null=True)
    opensAt = AwareDateTime(allow_null=True)
    closesAt = AwareDateTime(allow_null=True)

    def validate(self, attrs):
        policy, start, end = attrs['policyVersionId'], attrs['opensAt'], attrs['closesAt']
        if all(v is None for v in (policy,start,end)):
            return attrs
        if any(v is None for v in (policy,start,end)) or start >= end:
            raise ValidationError('Provide an approved policy and ordered window, or three null values to disable')
        return attrs


class TitleInput(serializers.Serializer):
    expectedProjectVersion = serializers.IntegerField(min_value=1)
    title = serializers.CharField(min_length=1, max_length=500)
    reason = serializers.CharField(allow_blank=True, default="", max_length=500)


def command(request, department_id, target_id, action, schema):
    body=command_body(request.data,set(schema().fields))
    serializer = schema(data=body)
    serializer.is_valid(raise_exception=True)
    payload = dict(serializer.validated_data)
    for key, value in payload.items():
        if hasattr(value, 'astimezone'):
            payload[key] = value.astimezone(timezone.utc).isoformat()
        elif key == 'policyVersionId' and value is not None:
            payload[key] = str(value)
    result = staff_command(request.user.id, department_id, action, target_id, payload,
                           request.headers.get('Idempotency-Key'))
    return private_response(result['result'])


@api_view(['GET'])
def policies(request, department_id):
    return private_response(staff_read(request.user.id, department_id, cursor=request.query_params.get('cursor'),acting_role=request.user.role))


@api_view(['GET'])
def projects(request, department_id):
    return private_response(staff_read(request.user.id, department_id, projects=True,
                                       cursor=request.query_params.get('cursor'),acting_role=request.user.role))


@api_view(['POST'])
def publication(request, department_id, offering_id):
    return command(request, department_id, offering_id, 'PUBLICATION', PublicationInput)


@api_view(['POST'])
def team_policy(request, department_id, offering_id):
    return command(request, department_id, offering_id, 'TEAM_POLICY', TeamPolicyInput)


@api_view(['POST'])
def registration_policy(request, department_id, offering_id):
    return command(request, department_id, offering_id, 'REGISTRATION', RegistrationInput)


@api_view(['POST'])
def correct_title(request, department_id, project_id):
    return command(request, department_id, project_id, 'CORRECT_TITLE', TitleInput)
