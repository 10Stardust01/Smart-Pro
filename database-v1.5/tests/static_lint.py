#!/usr/bin/env python3
"""Limited offline schema consistency check; NOT a PostgreSQL parser/execution test."""
import re
from pathlib import Path
root=Path(__file__).resolve().parent.parent
files=sorted((root/'migrations').glob('*.sql'))
src='\n'.join(x.read_text() for x in files)
# Identify actual definitions; do not mistake similarly named index clauses for tables.
tables=set(re.findall(r'\bCREATE\s+TABLE\s+(\w+)\s*\(',src,re.I))
functions=set(re.findall(r'\bCREATE\s+FUNCTION\s+(\w+)\s*\(',src,re.I))
refs=re.findall(r'\bREFERENCES\s+(\w+)\s*\(',src,re.I)
refs+=re.findall(r'\bREFERENCES\s+(\w+)\s*\)',src,re.I)
# Include references where no column list follows.
refs+=re.findall(r'\bREFERENCES\s+(\w+)\s*\(id\)',src,re.I)
missing={x for x in refs if x not in tables}
assert not missing, f'Foreign keys reference missing tables: {sorted(missing)}'
triggers=re.findall(r'\bEXECUTE\s+FUNCTION\s+(\w+)\s*\(',src,re.I)
missing_fns={x for x in triggers if x not in functions}
assert not missing_fns, f'Triggers use missing functions: {sorted(missing_fns)}'
for file in files:
    content=file.read_text()
    assert content.count('BEGIN;')==1 and content.count('COMMIT;')==1, f'transaction wrapper mismatch in {file.name}'
    assert content.count('$$')%2==0, f'unmatched function delimiter in {file.name}'
for key in ('submission_cases','submission_attempts','submission_items','approval_decisions',
            'scheme_versions','scheme_modes','mode_criteria','review_roster_members',
            'team_criterion_scores','student_criterion_scores','result_releases',
            'result_student_scores','idempotency_records','outbox_events'):
    assert key in tables, f'expected entity missing: {key}'
print(f'OFFLINE STATIC CHECK PASS: {len(tables)} tables, {len(functions)} trigger functions, '
      f'{len(triggers)} trigger hooks, {len(refs)} FK references, {len(files)} ordered migration files')
print('LIMITATION: This cannot establish SQL syntax, server compatibility or runtime behavior. Run psql tests.')

# Additional limited lexical check: referenced multi-column keys exist and are unique.
# Not a replacement for real PostgreSQL parsing.
def split_top_level(source):
    parts=[]; depth=0; start=0; quoted=False
    for i,ch in enumerate(source):
        if ch=="'": quoted=not quoted
        elif not quoted and ch=='(': depth+=1
        elif not quoted and ch==')': depth-=1
        elif not quoted and ch==',' and depth==0:
            parts.append(source[start:i].strip()); start=i+1
    parts.append(source[start:].strip())
    return parts

def column_list(s):
    return tuple(x.strip().lower() for x in s.split(','))

models={}
for match in re.finditer(r'\bCREATE\s+TABLE\s+(\w+)\s*\(',src,re.I):
    tab=match.group(1).lower(); i=match.end(); depth=1; in_quote=False; start=i
    while depth and i<len(src):
        ch=src[i]
        if ch=="'": in_quote=not in_quote
        elif not in_quote and ch=='(': depth+=1
        elif not in_quote and ch==')': depth-=1
        i+=1
    body=src[start:i-1]
    entries=split_top_level(body)
    columns=set(); unique=set(); fk=[]
    for entry in entries:
        z=re.match(r'^(\w+)\s+(uuid|text|integer|bigint|date|timestamptz|numeric|jsonb|char)\b',entry,re.I)
        if z:
            columns.add(z.group(1).lower())
            if re.search(r'\bPRIMARY KEY\b|\bUNIQUE\b',entry,re.I): unique.add((z.group(1).lower(),))
        m=re.search(r'\b(?:PRIMARY KEY|UNIQUE)\s*\(([^)]+)\)',entry,re.I)
        if m: unique.add(column_list(m.group(1)))
        m=re.search(r'\bFOREIGN KEY\s*\(([^)]+)\)\s*REFERENCES\s+(\w+)\s*\(([^)]+)\)',entry,re.I|re.S)
        if m: fk.append((column_list(m.group(1)),m.group(2).lower(),column_list(m.group(3))))
    models[tab]={'columns':columns,'unique':unique,'fk':fk}

checked=0
for tab,model in models.items():
    for local,referenced,remote in model['fk']:
        assert len(local)==len(remote),f'{tab}->{referenced} mismatched FK lengths'
        assert set(local)<=model['columns'],f'{tab} missing local FK columns {set(local)-model["columns"]}'
        assert referenced in models,f'{tab}: missing referenced table {referenced}'
        target=models[referenced]
        assert set(remote)<=target['columns'],f'{tab}->{referenced}: missing referenced columns {set(remote)-target["columns"]}'
        assert remote in target['unique'],f'{tab}->{referenced}: referenced key {remote} is not declared UNIQUE/PK'
        checked+=1
print(f'OFFLINE COMPOSITE KEY CHECK PASS: {checked} explicit FOREIGN KEY declarations match declared unique/primary keys')
