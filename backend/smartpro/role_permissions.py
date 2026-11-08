"""Active responsibility narrows presentation/actions; domain grants remain required."""
import os
from rest_framework.permissions import BasePermission

class ActiveRolePermission(BasePermission):
    message='Switch to the responsibility authorized for this action.'

    def has_permission(self,request,view):
        user=request.user
        if not user or not getattr(user,'is_authenticated',False):return False
        role=getattr(user,'role',None)
        if request.path.startswith('/api/v1/faculty-reference/'):
            return role in ('Admin','HOD','Coordinator')
        if request.path=='/api/v1/workspace':return True
        if not role:
            return len(getattr(user,'role_choices',()))<=1
        if request.method not in ('GET','HEAD','OPTIONS') and not isinstance(request.data,dict):return False
        if isinstance(request.data,dict) and 'action' in request.data and not isinstance(request.data['action'],str):return False
        path=request.path;read=request.method in ('GET','HEAD','OPTIONS')
        if path.endswith('/course-notifications'):return read
        if '/courses/' in path:
            if path.endswith('/coordinators'):return role in ('HOD','Admin')
            if path.endswith('/commands'):
                action=request.data.get('action')
                if action=='FRAMEWORK':return role in ('HOD','Admin')
                if action in ('REQUEST_CORRECTION','APPLY_CORRECTION','REQUEST_EXCEPTIONAL_STAGE_CORRECTION','APPLY_EXCEPTIONAL_STAGE_CORRECTION','REOPEN_SYNOPSIS'):return role=='Faculty'
                if action in ('AUTHORIZE_CORRECTION','AUTHORIZE_EXCEPTIONAL_STAGE_CORRECTION','AUTHORIZE_FINAL_REVISION'):return role=='Coordinator'
                if action=='COMPLETE_MILESTONE':return role in ('Student','Faculty','Coordinator','HOD')
                return role in ('HOD','Coordinator')
            return role in ('HOD','Admin','Coordinator')
        if path=='/api/v1/demo/workspace':return True
        if path.endswith('/proposal-details'):return role=='Student'
        if '/document-versions/' in path:return role in ('Student','Faculty','Coordinator','HOD')
        if '/submission-cases/' in path:return role in ('Student','Faculty','Coordinator','HOD')
        if '/documents/departments/' in path:
            if '/uploads' in path:return role=='Student'
            if read:return True
            action=request.data.get('action')
            return action in {'Student':{'PREPARE','SUBMIT'},'Faculty':{'DECIDE'},'Admin':{'CONFIGURE'},'HOD':{'AUTHORIZE','ASSIGN_REVIEWER'},'Coordinator':{'ASSIGN_REVIEWER'}}.get(role,set())
        if '/staff/' in path:
            if path.endswith('/intake') or '/records/' in path:return role=='Admin'
            if path.endswith('/appointment-candidates'):return role in ('Admin','HOD')
            if path.endswith('/leadership'):return role in ('Admin','HOD')
            if path.endswith('/assignment-management'):return role in ('HOD','Coordinator')
            if path.endswith(('/offering-management','/configuration-management','/document-requirements')):return role in ('Admin','HOD','Coordinator') if read else role=='Admin'
            if path.endswith('/coordinator-operations'):return role=='HOD'
            if path.endswith('/setup'):
                if role=='Coordinator' and os.getenv('SMARTPRO_COURSE_API')=='YES':return False
                if read:return role in ('Admin','HOD','Coordinator')
                return request.data.get('action') in ({'REQUEST','APPLY','RECORD'} if role=='Admin' else {'APPROVE'} if role=='HOD' else set())
            if role=='Faculty':return (read and path.endswith(('/policies','/projects'))) or path.endswith('/title')
            return role in ('HOD','Coordinator')
        if '/academic/' in path:
            if path.endswith('/management'):return role in ('HOD','Coordinator')
            if path.endswith(('/draft','/finalize','/evaluations')):return role=='Faculty'
            if '/coordinators' in path:return role=='HOD'
            if '/delegations' in path:return role=='Coordinator'
            if path.endswith('/policies') and not read:return role=='HOD'
            if role in ('HOD','Coordinator'):return True
            if role=='Faculty':return path.endswith(('/draft','/finalize','/evaluations')) or (read and path.endswith('/results'))
            return role=='Student' and read and path.endswith('/results')
        if '/me/' in path or '/teams' in path or '/memberships' in path or path=='/api/v1/projects' or path.endswith('/proposal') or path=='/api/v1/demo/enrollment':
            return role=='Student'
        return read
