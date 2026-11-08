from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError

from .projects import register_project, student_projects, _enabled
from .student_views import private_response
from .staff import _execute


class ProjectInput(serializers.Serializer):
    teamId = serializers.UUIDField()
    projectType = serializers.ChoiceField(choices=['MINI', 'MAJOR'])
    projectCode = serializers.CharField(min_length=1, max_length=120)
    title = serializers.CharField(min_length=1, max_length=500)

class ProposalInput(serializers.Serializer):
    description=serializers.CharField(max_length=10000,allow_blank=True,required=False)
    offeringId=serializers.UUIDField()
    teamId=serializers.UUIDField()
    title=serializers.CharField(min_length=1,max_length=500)


@api_view(['POST'])
def register(request):
    if isinstance(request.data,dict) and set(request.data) in ({'offeringId','teamId','title'},{'offeringId','teamId','title','description'}):
        serializer=ProposalInput(data=request.data);serializer.is_valid(raise_exception=True);data=serializer.validated_data
        result=register_project(request.user.id,data['teamId'],None,None,data['title'],request.headers.get('Idempotency-Key'),offering_id=data['offeringId'],description=data.get('description'))
        return private_response(result['project'],status=200 if result['replayed'] else 201)
    # Preserve compatibility with pre-022 databases, never permit manual codes
    # through the current application once the managed-reference contract exists.
    if _execute("SELECT to_regprocedure('public.smartpro_register_proposal(uuid,uuid,uuid,text,text)') IS NOT NULL",()):
        raise ValidationError('Select an offering, confirm your team and enter a title. Project references and classification are assigned by the system.')
    if not isinstance(request.data, dict) or set(request.data) != {'teamId','projectType','projectCode','title'}:
        raise ValidationError('Only teamId, projectType, projectCode and title are accepted')
    serializer = ProjectInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    result = register_project(request.user.id, data['teamId'], data['projectType'],
                              data['projectCode'], data['title'], request.headers.get('Idempotency-Key'))
    return private_response(result['project'], status=200 if result['replayed'] else 201)

@api_view(['GET'])
def proposal_offering(request,offering_id):
    _enabled()
    return private_response(_execute('SELECT public.smartpro_proposal_offering(%s,%s)',(request.user.id,offering_id)))


@api_view(['GET'])
def current(request):
    return private_response(student_projects(request.user.id, request.query_params.get('cursor'),request.query_params.get('offeringId')))
