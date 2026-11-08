"""Temporary PostgreSQL-backed HTTP harness; backend framework remains undecided."""
import os
import sys
import uuid
from pathlib import Path
from typing import Literal

import psycopg
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import domain

MAX_SIZE = domain.MAX_SIZE
connect = domain.connect
STORAGE = Path(os.environ.get('SMARTPRO_DATA_DIR', '.demo-data')) / 'files'
ALIASES = {
    'case-1': '19000000-0000-4000-8000-000000000001',
    'project-1': '15000000-0000-4000-8000-000000000001',
    'project-2': '15000000-0000-4000-8000-000000000002',
    'synopsis-1': '16000000-0000-4000-8000-000000000001',
    'synopsis-2': '16000000-0000-4000-8000-000000000002',
}
DEMO_USERS = {
    'student-a': '00000000-0000-4000-8000-000000000001',
    'student-b': '00000000-0000-4000-8000-000000000002',
    'faculty-a': '00000000-0000-4000-8000-000000000003',
    'student-outsider': '00000000-0000-4000-8000-000000000005',
    'faculty-other': '00000000-0000-4000-8000-000000000006',
    'tech-admin': '00000000-0000-4000-8000-000000000007',
}


class SubmitAttempt(BaseModel):
    documentVersionIds: list[str] = Field(min_length=1, max_length=10)
    expectedCaseVersion: int = Field(ge=1)


class ReviewerDecision(BaseModel):
    decision: Literal['APPROVE', 'REQUEST_CHANGES']
    comment: str = Field(default='', max_length=4000)
    expectedCaseVersion: int = Field(ge=1)


class ErrorDetail(BaseModel):
    code: str
    message: str
    errors: list[dict] | None = None


class ErrorResponse(BaseModel):
    detail: ErrorDetail


def identifier(value):
    if os.getenv('SMARTPRO_DEMO_AUTH') == 'YES':
        value = ALIASES.get(value, value)
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        domain.fail(404, 'OBJECT_NOT_FOUND', 'Invalid object identifier')


def principal(header):
    if os.getenv('SMARTPRO_DEMO_AUTH') != 'YES' or header not in DEMO_USERS:
        domain.fail(401, 'DEMO_AUTH_REQUIRED', 'No production identity adapter is configured')
    return DEMO_USERS[header]


def init_demo(reset=False):
    """Explicit test helper only; never invoked by a request or server startup."""
    if not reset:
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from db_setup import reset_test_database
    reset_test_database('api_seed.sql')


app = FastAPI(title='SMART-PRO Synopsis Workflow — CONTRACT EXPERIMENT ONLY', version='0.2.0',
              description='Temporary PostgreSQL-backed FastAPI harness. Synthetic opt-in identity; not production auth or a final framework decision.',
              responses={code: {'model': ErrorResponse} for code in [400, 401, 403, 404, 409, 422, 503]})


@app.exception_handler(RequestValidationError)
async def invalid_request(_request, exc):
    errors = [{'location': list(e['loc']), 'type': e['type'], 'message': e['msg']} for e in exc.errors()]
    return JSONResponse(status_code=422, content={'detail': {
        'code': 'INVALID_REQUEST', 'message': 'Request does not match the API contract', 'errors': errors}})


@app.exception_handler(domain.DomainError)
async def domain_error(_request, exc):
    return JSONResponse(status_code=exc.status, content={'detail': {'code': exc.code, 'message': exc.message}})


@app.exception_handler(psycopg.Error)
async def database_error(_request, exc):
    if exc.sqlstate in ('23505', '40001', '40P01', '55P03'):
        status, code = 409, 'DATABASE_CONFLICT'
    elif exc.sqlstate == '42501':
        status, code = 403, 'DATABASE_AUTHORITY_DENIED'
    elif exc.sqlstate and exc.sqlstate.startswith('23'):
        status, code = 422, 'DATABASE_INTEGRITY_REJECTED'
    else:
        status, code = 503, 'DATABASE_UNAVAILABLE'
    return JSONResponse(status_code=status, content={'detail': {'code': code, 'message': 'Database transaction rejected; no partial academic change committed'}})


@app.post('/api/v1/documents/{document_id}/upload-sessions', status_code=201)
def start_upload(document_id: str, x_demo_user: str | None = Header(None)):
    actor = principal(x_demo_user)
    return domain.start_upload(identifier(document_id), actor)


@app.put('/api/v1/upload-sessions/{upload_id}/content')
async def put_upload(upload_id: str, request: Request, x_demo_user: str | None = Header(None)):
    actor = principal(x_demo_user)
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_SIZE:
            domain.fail(422, 'BAD_FILE_SIZE', 'Oversized test file')
        content.extend(chunk)
    return await run_in_threadpool(domain.put_upload, identifier(upload_id), actor, bytes(content))


@app.post('/api/v1/upload-sessions/{upload_id}/complete', status_code=201)
def finish_upload(upload_id: str, x_demo_user: str | None = Header(None)):
    actor = principal(x_demo_user)
    return domain.finish_upload(identifier(upload_id), actor)


@app.post('/api/v1/submission-cases/{case_id}/attempts', status_code=201)
def submit_attempt(case_id: str, payload: SubmitAttempt, x_demo_user: str | None = Header(None), idempotency_key: str | None = Header(None)):
    actor = principal(x_demo_user)
    body = payload.model_dump()
    body['documentVersionIds'] = [identifier(x) for x in body['documentVersionIds']]
    return domain.submit_attempt(identifier(case_id), actor, body, idempotency_key)


@app.post('/api/v1/submission-attempts/{attempt_id}/decisions', status_code=201)
def decide(attempt_id: str, payload: ReviewerDecision, x_demo_user: str | None = Header(None), idempotency_key: str | None = Header(None)):
    actor = principal(x_demo_user)
    return domain.decide(identifier(attempt_id), actor, payload.model_dump(), idempotency_key)


@app.get('/api/v1/submission-cases/{case_id}')
def read_case(case_id: str, x_demo_user: str | None = Header(None)):
    actor = principal(x_demo_user)
    return domain.read_case(identifier(case_id), actor)


@app.get('/health')
def health():
    with domain.connect() as db:
        version = db.execute('SHOW server_version').fetchone()['server_version']
    return {'status': 'demo-only', 'database': 'PostgreSQL', 'version': version}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8765)
