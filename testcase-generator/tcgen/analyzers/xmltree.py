"""라인 번호를 보존하는 경량 XML 트리 (표준 라이브러리 expat 사용).

네임스페이스 접두어(xf:, w2:, ev: ...)는 선언 여부와 무관하게 로컬명으로 처리한다.
"""
import xml.parsers.expat

from .common import AnalyzeError


class Node:
    __slots__ = ("tag", "raw_tag", "attrs", "children", "text", "line", "parent", "pieces")

    def __init__(self, raw_tag, attrs, line, parent):
        self.raw_tag = raw_tag
        self.tag = raw_tag.split(":")[-1]
        self.attrs = {}
        for k, v in attrs.items():
            self.attrs[k] = v
            self.attrs.setdefault(k.split(":")[-1], v)
        self.children = []
        self.text = ""
        self.pieces = []   # 텍스트와 자식 노드를 문서 순서대로 보관
        self.line = line
        self.parent = parent

    def get(self, *names, default=None):
        for n in names:
            if n in self.attrs and self.attrs[n] != "":
                return self.attrs[n]
        return default

    def iter(self):
        yield self
        for c in self.children:
            yield from c.iter()

    def find_all(self, *tags):
        tags = set(tags)
        return [n for n in self.iter() if n.tag in tags]

    def find(self, *tags):
        for n in self.iter():
            if n is not self and n.tag in tags:
                return n
        return None

    def all_text(self):
        return "".join(p if isinstance(p, str) else p.all_text() for p in self.pieces)


def parse_xml(text):
    # 선언된 encoding 과 무관하게 이미 디코딩된 문자열을 파싱한다.
    body = text.lstrip("﻿")
    if body.startswith("<?xml"):
        end = body.find("?>")
        if end != -1:
            body = body[end + 2:]
    parser = xml.parsers.expat.ParserCreate()
    root_holder = []
    stack = []

    def start(name, attrs):
        parent = stack[-1] if stack else None
        node = Node(name, attrs, parser.CurrentLineNumber, parent)
        if parent is not None:
            parent.children.append(node)
            parent.pieces.append(node)
        else:
            root_holder.append(node)
        stack.append(node)

    def end(name):
        stack.pop()

    def chars(data):
        if stack:
            stack[-1].text += data
            stack[-1].pieces.append(data)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    parser.buffer_text = True
    try:
        parser.Parse(body, True)
    except xml.parsers.expat.ExpatError as e:
        offset = text[: len(text) - len(body)].count("\n")
        raise AnalyzeError(f"XML 파싱 오류: {xml.parsers.expat.ErrorString(e.code)}",
                           line=e.lineno + offset, column=e.offset)
    if not root_holder:
        raise AnalyzeError("XML 루트 요소가 없습니다.")
    return root_holder[0]
