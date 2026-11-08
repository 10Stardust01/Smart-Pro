"""Read bounded departmental exports into the same mapped row contract."""
import csv
from io import BytesIO, StringIO
from pathlib import Path
import os
from time import monotonic
from zipfile import BadZipFile, ZipFile

from rest_framework.exceptions import ValidationError


def read_export(upload):
    limit = int(os.getenv('SMARTPRO_INTAKE_FILE_BYTES', str(2 * 1024 * 1024)))
    if not 0 < upload.size <= limit:
        raise ValidationError(f'Choose an export no larger than {limit} bytes')
    suffix = Path(upload.name).suffix.lower()
    if suffix == '.csv':
        try:
            text = upload.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            raise ValidationError('Use a UTF-8 CSV export') from None
        if '\x00' in text:
            raise ValidationError('CSV contains unsupported characters')
        try:
            return normalize_rows(csv.reader(StringIO(text, newline=''), strict=True))
        except csv.Error:
            raise ValidationError('CSV could not be read') from None
    if suffix != '.xlsx':
        raise ValidationError('Choose a CSV or XLSX export')
    return read_workbook(upload.read())


def read_workbook(content):
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException
    from xml.etree.ElementTree import ParseError

    try:
        with ZipFile(BytesIO(content)) as archive:
            parts = archive.infolist()
            if len(parts) > 256 or sum(part.file_size for part in parts) > 16 * 1024 * 1024:
                raise ValidationError('Workbook expands beyond the supported size')
            if len({part.filename for part in parts}) != len(parts):
                raise ValidationError('Workbook contains duplicate parts')
            for part in parts:
                content_part = archive.read(part)
                # Relationship targets can use arbitrary extensions. Strip NULs
                # for this check so UTF-16 and UTF-32 declarations are covered.
                declarations = content_part.replace(b'\x00', b'').upper()
                if b'<!DOCTYPE' in declarations or b'<!ENTITY' in declarations:
                    raise ValidationError('Workbook contains unsupported XML')
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=False, keep_links=False)
        try:
            if len(workbook.worksheets) != 1:
                raise ValidationError('Export one worksheet per import')
            sheet = workbook.worksheets[0]
            # Ignore declared dimensions, which can omit populated rows or invent empty cells.
            sheet.reset_dimensions()
            deadline = monotonic() + 5

            def rows():
                for row in sheet.iter_rows():
                    if monotonic() > deadline:
                        raise ValidationError('Workbook processing took too long. Export a compact worksheet.')
                    if any(cell.data_type in ('f', 'e') for cell in row):
                        raise ValidationError('Replace formulas and cell errors with values before importing')
                    yield [str(cell.value) if cell.value is not None else '' for cell in row]
            return normalize_rows(rows(), pad=True)
        finally:
            workbook.close()
    except (BadZipFile, InvalidFileException, ParseError, KeyError, UnicodeError, ValueError, OSError, RuntimeError, NotImplementedError):
        raise ValidationError('XLSX workbook could not be read') from None


def normalize_rows(source, *, pad=False):
    def trim_trailing(row):
        while row and not row[-1].strip():
            row.pop()
        return row

    header = next(source, [])
    if pad:
        header = trim_trailing(header)
    headers = [item.strip() for item in header]
    if (not 1 <= len(headers) <= 32 or any(not item or len(item) > 120 for item in headers)
            or len(set(headers)) != len(headers)):
        raise ValidationError('Export column names must be distinct and nonempty')
    rows = []
    mapped_bytes = 0
    for row in source:
        if not any(field.strip() for field in row):
            continue
        if pad:
            row = trim_trailing(row)
            row.extend([''] * max(0, len(headers) - len(row)))
        if len(row) != len(headers) or any(len(field) > 120 for field in row):
            raise ValidationError('Use complete rows with fields up to 120 characters')
        mapped_bytes += sum(len(field.encode('utf-8')) + 8 for field in row)
        if mapped_bytes > 2 * 1024 * 1024:
            raise ValidationError('Export exceeds the supported decoded data size')
        rows.append(row)
    if not rows:
        raise ValidationError('Include at least one record after the column names')
    return headers, rows
