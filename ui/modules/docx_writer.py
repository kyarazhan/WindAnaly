"""极简 DOCX 生成器（零依赖：zipfile + 手写 Office Open XML）。

支持：标题 / 段落 / 表格 / PNG 图片。满足 Reports 标签页的基础报告输出。
"""
import zipfile
from xml.sax.saxutils import escape
_CT = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''

_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''

_DOC_RELS_HEAD = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'''
_DOC_RELS_IMG = ('<Relationship Id="rIdImg{i}" Type="http://schemas.'
                 'openxmlformats.org/officeDocument/2006/relationships/image"'
                 ' Target="media/image{i}.png"/>')
_DOC_RELS_TAIL = '</Relationships>'


def _p(text, bold=False, size_half_pt=22, align='left'):
    rpr = (f'<w:rPr><w:b/><w:sz w:val="{size_half_pt}"/></w:rPr>' if bold
           else f'<w:rPr><w:sz w:val="{size_half_pt}"/></w:rPr>')
    return (f'<w:p><w:pPr><w:jc w:val="{align}"/></w:pPr>'
            f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')


def _table(rows):
    cols = max(len(r) for r in rows)
    out = ['<w:tbl><w:tblPr><w:tblBorders>'
           + ''.join(f'<w:{side} w:val="single" w:sz="4" w:color="999999"/>'
                     for side in ('top', 'left', 'bottom', 'right',
                                  'insideH', 'insideV'))
           + '</w:tblBorders></w:tblPr>']
    for r_i, row in enumerate(rows):
        out.append('<w:tr>')
        for c in range(cols):
            val = str(row[c]) if c < len(row) else ''
            bold = '<w:b/>' if r_i == 0 else ''
            out.append(f'<w:tc><w:tcPr/><w:p><w:r><w:rPr>{bold}'
                       f'<w:sz w:val="20"/></w:rPr>'
                       f'<w:t xml:space="preserve">{escape(val)}</w:t>'
                       f'</w:r></w:p></w:tc>')
        out.append('</w:tr>')
    out.append('</w:tbl>')
    return ''.join(out)


_IMG_P = ('<w:p><w:r><w:drawing>'
          '<wp:inline distT="0" distB="0" distL="0" distR="0">'
          '<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{did}" '
          'name="image{i}"/>'
          '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
          '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
          '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
          '<pic:nvPicPr><pic:cNvPr id="{did}" name="image{i}.png"/>'
          '<pic:cNvPicPr/></pic:nvPicPr>'
          '<pic:blipFill><a:blip r:embed="rIdImg{i}"/><a:stretch><a:fillRect/>'
          '</a:stretch></pic:blipFill>'
          '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/>'
          '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
          '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>'
          '</w:r></w:p>')


class DocxBuilder:
    """增量构建 DOCX：标题 / 段落 / 表格 / PNG 图片。"""

    def __init__(self):
        self._blocks: list[tuple] = []      # ('h'|'p'|'table'|'img', payload)
        self._img_n = 0

    def heading(self, text: str, level: int = 1):
        self._blocks.append(('h', (text, level)))

    def paragraph(self, text: str):
        self._blocks.append(('p', text))

    def table(self, rows: list[list[str]]):
        self._blocks.append(('table', rows))

    def image_png(self, png_bytes: bytes, width_px: int = 560,
                  height_px: int = 360):
        self._img_n += 1
        self._blocks.append(('img', (self._img_n, png_bytes, width_px,
                                     height_px)))

    def save(self, path: str):
        body = []
        rels = []
        media = {}
        img_idx = 0
        for kind, payload in self._blocks:
            if kind == 'h':
                text, level = payload
                body.append(_p(text, bold=True, size_half_pt=30 - 2 * level))
            elif kind == 'p':
                body.append(_p(payload))
            elif kind == 'table':
                body.append(_table(payload))
                body.append(_p(''))
            elif kind == 'img':
                img_idx += 1
                i, png, w_px, h_px = payload
                media[f'word/media/image{i}.png'] = png
                rels.append(_DOC_RELS_IMG.format(i=i))
                cx = int(w_px * 9525)
                cy = int(h_px * 9525)
                body.append(_IMG_P.format(i=i, did=i, cx=cx, cy=cy))
        doc_rels = (_DOC_RELS_HEAD + ''.join(rels) + _DOC_RELS_TAIL)
        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships" '
            'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/'
            'wordprocessingDrawing">'
            f'<w:body>{"".join(body)}'
            '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" '
            'w:left="1134"/></w:sectPr></w:body></w:document>')
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('[Content_Types].xml', _CT)
            z.writestr('_rels/.rels', _RELS)
            z.writestr('word/_rels/document.xml.rels', doc_rels)
            z.writestr('word/document.xml', document)
            for name, data in media.items():
                z.writestr(name, data)
