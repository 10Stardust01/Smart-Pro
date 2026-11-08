from rest_framework.decorators import api_view
from rest_framework.response import Response

from .students import read_student


def private_response(data, *, status=200):
    response = Response(data, status=status)
    response['Cache-Control'] = 'no-store'
    response['Vary'] = 'Authorization, X-Demo-User'
    return response


@api_view(['GET'])
def profile(request):
    return private_response(read_student(request.user.id))


@api_view(['GET'])
def offerings(request):
    return private_response(read_student(
        request.user.id, offerings=True, cursor=request.query_params.get('cursor')))
