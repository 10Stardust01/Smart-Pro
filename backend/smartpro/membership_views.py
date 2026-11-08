from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError

from .memberships import change_membership, own_memberships
from .student_views import private_response


class DepartureInput(serializers.Serializer):
    reason = serializers.CharField(max_length=500, allow_blank=True, required=False, default='')


class TransferInput(DepartureInput):
    targetTeamId = serializers.UUIDField()


@api_view(['GET'])
def current(request):
    return private_response(own_memberships(request.user.id, request.query_params.get('cursor')))


def parse_input(request, serializer_class, allowed, required=frozenset()):
    if not isinstance(request.data, dict) or not required <= set(request.data) <= allowed:
        raise ValidationError('Invalid membership command fields')
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def respond(request, action, **values):
    result = change_membership(request.user.id, action,
                               idempotency_key=request.headers.get('Idempotency-Key'), **values)
    return private_response(result['membership'],
                            status=200 if result['replayed'] or action == 'LEAVE' else 201)


@api_view(['POST'])
def join(request, team_id):
    parse_input(request, serializers.Serializer, set())
    return respond(request, 'JOIN', team_id=team_id)


@api_view(['POST'])
def leave(request, membership_id):
    data = parse_input(request, DepartureInput, {'reason'})
    return respond(request, 'LEAVE', membership_id=membership_id, reason=data['reason'])


@api_view(['POST'])
def transfer(request, membership_id):
    data = parse_input(request, TransferInput, {'reason', 'targetTeamId'}, {'targetTeamId'})
    return respond(request, 'TRANSFER', membership_id=membership_id,
                   team_id=data['targetTeamId'], reason=data['reason'])
