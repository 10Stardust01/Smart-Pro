"""Authenticated, student-scoped team endpoints."""
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError

from .student_views import private_response
from .teams import create_team, eligible_teams


class CreateTeamInput(serializers.Serializer):
    offeringId = serializers.UUIDField()
    name = serializers.CharField(min_length=1, max_length=120, trim_whitespace=True)


@api_view(['POST'])
def create(request):
    if not isinstance(request.data, dict):
        raise ValidationError('Expected a JSON object')
    if set(request.data) != {'offeringId', 'name'}:
        raise ValidationError('Only offeringId and name are accepted')
    serializer = CreateTeamInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    result = create_team(
        request.user.id,
        serializer.validated_data['offeringId'],
        serializer.validated_data['name'],
        request.headers.get('Idempotency-Key'),
    )
    return private_response(result['team'], status=200 if result['replayed'] else 201)


@api_view(['GET'])
def discover(request, offering_id):
    return private_response(eligible_teams(
        request.user.id, offering_id, cursor=request.query_params.get('cursor')))


