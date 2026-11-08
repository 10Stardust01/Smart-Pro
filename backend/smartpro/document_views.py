"""Private document routes. Existing document/attempt models and local object store."""
import hashlib
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from uuid import uuid4

from django.http import HttpResponse
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError

from . import private_storage
from .staff import StaffUnavailable, _execute, staff_sql_command
from .student_views import private_response
from .views import domain
from .staff_views import AwareDateTime
from .command_input import command_body

logger = logging.getLogger(__name__)


class BoundedPDFUpload(FileUploadHandler):
    def receive_data_chunk(self, raw_data, start):
        if start+len(raw_data)>domain.MAX_SIZE:
            raise StopUpload(connection_reset=True)
        return raw_data

    def file_complete(self, file_size):
        return None


def enabled():
    if os.getenv('SMARTPRO_DOCUMENT_API') != 'YES' or os.getenv('SMARTPRO_ACADEMIC_API') != 'YES':
        raise StaffUnavailable('Document workflow is not enabled')


def command(actor, dept, action, body, key):
    enabled()
    return staff_sql_command('SELECT public.smartpro_document_command(%s,%s,%s,%s,%s)',
                             actor, dept, action, body, key)


FIELDS = {
    'AUTHORIZE': {'configuration', 'reason'}, 'CONFIGURE': {'instructionId'},
    'ASSIGN_REVIEWER': {'projectId', 'facultyId'}, 'PREPARE': {'projectId'},
    'SUBMIT': {'projectId', 'documentVersionId', 'expectedCaseVersion'},
    'DECIDE': {'projectId', 'attemptId', 'expectedCaseVersion', 'decision', 'comment'},
}


@api_view(['GET', 'POST'])
def workspace(request, department_id):
    enabled()
    if request.method == 'GET':
        role=getattr(request.user,'role',None)
        if request.query_params.get('listing') == '1':
            query = serializers.CharField(max_length=120, allow_blank=True).run_validation(request.query_params.get('q', ''))
            page = serializers.IntegerField(min_value=1, max_value=2147483647).run_validation(request.query_params.get('page', '1'))
            offering = serializers.UUIDField(allow_null=True).run_validation(request.query_params.get('offering'))
            return private_response(_execute('SELECT public.smartpro_document_project_page(%s,%s,%s,%s,%s,%s)',
                                             (request.user.id, department_id, role, query, page, offering)))
        if request.query_params.get('configuration') == '1':
            from django.db import connection, transaction
            from rest_framework.exceptions import PermissionDenied

            if role != 'Admin':
                raise PermissionDenied('Operational Admin responsibility required')
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT to_regprocedure('public.smartpro_course_project_documents(uuid,uuid,uuid,text)') IS NOT NULL")
                    if not cursor.fetchone()[0]:
                        raise StaffUnavailable('Bounded configuration requires candidate 049')
                    cursor.execute("SELECT current_setting('smartpro.document_project',true)")
                    previous_scope = cursor.fetchone()[0]
                    cursor.execute("SELECT set_config('smartpro.document_project','configuration-only',true)")
                    result = _execute('SELECT public.smartpro_configured_document_workspace(%s,%s,%s)',
                                      (request.user.id, department_id, role))
                    cursor.execute("SELECT set_config('smartpro.document_project',%s,true)", (previous_scope or '',))
                return private_response(result)
        project = request.query_params.get('project')
        if project is not None:
            project_id = serializers.UUIDField().run_validation(project)
            if not _execute("SELECT to_regprocedure('public.smartpro_course_project_documents(uuid,uuid,uuid,text)') IS NOT NULL", ()):
                raise StaffUnavailable('Scoped project evidence requires candidate 049')
            return private_response(_execute('SELECT public.smartpro_course_project_documents(%s,%s,%s,%s)',
                                             (request.user.id, department_id, project_id, role)))

        if role:
            return private_response(_execute('SELECT public.smartpro_configured_document_workspace(%s,%s,%s)',(request.user.id,department_id,role)))
        return private_response(_execute('SELECT public.smartpro_document_disposition(%s,%s)',(request.user.id,department_id)))
    if not isinstance(request.data, dict):
        raise ValidationError('Document command must be an object')
    action = request.data.get('action')
    body = {k: v for k, v in request.data.items() if k != 'action'}
    if not isinstance(action,str) or action not in FIELDS:
        raise ValidationError('Unknown document command')
    fields=FIELDS[action]|({'requirementKey'} if 'requirementKey' in body and action in ('PREPARE','SUBMIT','DECIDE') else set())
    body=command_body(body,fields)
    if 'requirementKey' in body:
        body['requirementKey']=serializers.CharField(max_length=100).run_validation(body['requirementKey'])
    if action=='AUTHORIZE':
        config=body['configuration']
        if not isinstance(config,dict) or any(v is None for v in config.values()):
            raise ValidationError('Complete approved configuration required')
        for field in ['visibleFrom','visibleUntil','submissionOpensAt','submissionClosesAt']:
            AwareDateTime().run_validation(config.get(field))
        if any(type(config.get(k)) is not bool for k in ['facultyApprovalEnabled','teamCreationEnabled']):
            raise ValidationError('Explicit boolean approval and team-creation choices required')
    if action=='SUBMIT':
        verified_file(request.user.id,body['documentVersionId'],getattr(request.user,'role',None))
    if action=='ASSIGN_REVIEWER' and os.getenv('SMARTPRO_COURSE_API')=='YES':
        body['_actingRole']=getattr(request.user,'role',None)
    return private_response(command(request.user.id, department_id, action, body,
                                    request.headers.get('Idempotency-Key')))


def verify_pdf(content):
    """Bounded, passive-PDF demo validation; production needs scanning/parser isolation."""
    digest, size = domain.verify_local_pdf(content)
    if not content.rstrip().endswith(b'%%EOF'):
        raise ValidationError('A complete PDF containing a page is required')
    if re.search(rb'/(JavaScript|JS|Launch|EmbeddedFile|OpenAction|AA|RichMedia|Encrypt|XFA)\b', content):
        raise ValidationError('Active, embedded or encrypted PDF content is not supported')
    pdf_pages(content)
    return digest, size


def pdf_pages(content):
    binary=shutil.which('pdfinfo')
    if not binary:
        raise StaffUnavailable('Local PDF validation dependency is unavailable')
    with tempfile.TemporaryDirectory(prefix='smartpro-pdf-') as directory:
        path=Path(directory)/'document.pdf';path.write_bytes(content)
        try:
            process=subprocess.run([binary,str(path)],capture_output=True,timeout=8,check=False)
        except (OSError,subprocess.TimeoutExpired):
            raise ValidationError('PDF validation did not complete') from None
        match=re.search(rb'^Pages:\s+(\d+)',process.stdout,re.M)
        if process.returncode or not match or not 1<=int(match[1])<=50:
            raise ValidationError('A valid PDF with 1–50 pages is required')
        return int(match[1])


@api_view(['POST'])
def upload(request, department_id, project_id):
    enabled()
    try: length=int(request.META.get('CONTENT_LENGTH','0'))
    except ValueError: raise ValidationError('Invalid upload length') from None
    if not 0<length<=domain.MAX_SIZE+65536:
        raise ValidationError('Upload request exceeds the supported PDF limit')
    request._request.upload_handlers.insert(0,BoundedPDFUpload(request._request))
    if set(request.data) != {'file'} or len(request.FILES.getlist('file')) != 1:
        raise ValidationError('One PDF file is required')
    file = request.FILES['file']
    if Path(file.name).suffix.lower() != '.pdf' or file.content_type != 'application/pdf' or file.size > domain.MAX_SIZE:
        raise ValidationError('Upload a PDF of at most 2 MiB')
    content = bytearray()
    for chunk in file.chunks():
        content.extend(chunk)
        if len(content) > domain.MAX_SIZE:
            raise ValidationError('PDF exceeds 2 MiB')
    digest, size = verify_pdf(bytes(content))
    actor, dept, pid = request.user.id, department_id, str(project_id)
    key = request.headers.get('Idempotency-Key', '')
    if len(key) > 110:
        raise ValidationError('Upload request keys must be at most 110 characters')
    requirement_key=request.query_params.get('requirementKey')
    context={'projectId':pid}
    if requirement_key is not None:
        from rest_framework import serializers
        context['requirementKey']=serializers.CharField(max_length=100).run_validation(requirement_key)
    command(actor, dept, 'PREPARE', context, key + ':prepare' if key else '')
    session = command(actor, dept, 'START_UPLOAD', context, key + ':start')
    if size > session['maxBytes']:
        raise ValidationError('PDF exceeds the approved requirement size')
    if private_storage.enabled():
        try:
            private_storage.put_immutable(session['uploadId'] + '.pdf', bytes(content), digest)
        except ValueError:
            raise ValidationError('The document identity or bytes are invalid') from None
        except IOError:
            raise StaffUnavailable('Private document storage is unavailable') from None
        result = command(actor, dept, 'COMPLETE_UPLOAD',
                         {**context, 'uploadId': session['uploadId'], 'sha256': digest, 'size': size}, key + ':complete')
    else:
        path = domain.object_path(session['uploadId'] + '.pdf')
        # Atomic no-replace publication. Crashes leave retryable immutable objects,
        # never a persistent lock or a half-written visible PDF.
        staging = path.with_name(uuid4().hex + '.staging')
        try:
            with staging.open('xb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(staging, path)
            except FileExistsError:
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValidationError('Retry key already identifies different uploaded bytes')
            # Persist the directory entry before the database advertises a ready
            # object on filesystems that expose POSIX directory synchronization.
            if hasattr(os, 'O_DIRECTORY'):
                directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            result = command(actor, dept, 'COMPLETE_UPLOAD',
                             {**context, 'uploadId': session['uploadId'], 'sha256': digest, 'size': size}, key + ':complete')
        finally:
            staging.unlink(missing_ok=True)
    return private_response(result)


def verified_file(actor,version_id,role=None):
    metadata = (_execute('SELECT public.smartpro_role_file(%s,%s,%s)',(actor,version_id,role)) if role else _execute('SELECT public.smartpro_document_file(%s,%s)', (actor, version_id)))
    if private_storage.enabled():
        try:
            data = private_storage.read(metadata['key'])
        except (OSError, ValueError):
            logger.warning('document_storage_rejected reason=unavailable')
            raise StaffUnavailable('Stored document is unavailable') from None
    else:
        path = domain.object_path(metadata['key'])
        try:
            if not path.is_file():
                raise FileNotFoundError
            with path.open('rb') as stream:
                data = stream.read(domain.MAX_SIZE + 1)
        except OSError:
            logger.warning('document_storage_rejected reason=unavailable')
            raise StaffUnavailable('Stored document is unavailable') from None
    if len(data) != metadata['bytes'] or len(data) > domain.MAX_SIZE:
        logger.warning('document_storage_rejected reason=size_mismatch')
        raise StaffUnavailable('Stored document is unavailable')
    if hashlib.sha256(data).hexdigest() != metadata['sha256']:
        logger.warning('document_storage_rejected reason=digest_mismatch')
        raise StaffUnavailable('Stored document failed its integrity check')
    return metadata,data


@api_view(['GET'])
def content(request, version_id):
    enabled()
    metadata,data=verified_file(request.user.id,version_id,getattr(request.user,'role',None))
    if request.query_params.get('preview')=='1':
        pages=pdf_pages(data)
        try: page=int(request.query_params.get('page','1'))
        except ValueError: raise ValidationError('Invalid preview page') from None
        if not 1<=page<=pages: raise ValidationError('Invalid preview page')
        binary=shutil.which('pdftoppm')
        if not binary: raise StaffUnavailable('Local PDF preview dependency is unavailable')
        with tempfile.TemporaryDirectory(prefix='smartpro-preview-') as directory:
            path=Path(directory)/'document.pdf';path.write_bytes(data)
            destination=Path(directory)/'page'
            try:
                process=subprocess.run([binary,'-f',str(page),'-l',str(page),'-singlefile','-scale-to','1280','-png',str(path),str(destination)],capture_output=True,timeout=10,check=False)
            except (OSError,subprocess.TimeoutExpired):
                raise StaffUnavailable('PDF preview did not complete') from None
            png=destination.with_suffix('.png')
            if process.returncode or not png.is_file(): raise StaffUnavailable('PDF preview could not be rendered')
            response=HttpResponse(png.read_bytes(),content_type='image/png')
            response['X-Document-Pages']=str(pages)
            response['Cache-Control']='private, no-store'
            response['X-Content-Type-Options']='nosniff'
            return response
    response = HttpResponse(data, content_type='application/pdf')
    disposition = 'attachment' if request.query_params.get('download') == '1' else 'inline'
    response['Content-Disposition'] = f'{disposition}; filename="synopsis-v{metadata["version"]}.pdf"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return response
