"""Small valid, passive synthetic PDF fixture; no external dependencies."""
def pdf_bytes(text='Synthetic SMART-PRO synopsis'):
    safe=text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
    stream=f'BT /F1 18 Tf 54 760 Td ({safe}) Tj ET'.encode('ascii')
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
             b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
             b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    data=bytearray(b'%PDF-1.4\n'); offsets=[0]
    for number,obj in enumerate(objects,1):
        offsets.append(len(data)); data.extend(f'{number} 0 obj\n'.encode()+obj+b'\nendobj\n')
    start=len(data);data.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]: data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return bytes(data)
