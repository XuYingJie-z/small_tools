#!/usr/bin/env python3
"""
从 Word XML/DOCX 文件中提取 PMID 占位符，并将其替换为 EndNote 临时引文。

Examples
--------
  ## 包含两步，
  # 第一步先提取出 Pubmed id，然后用这个 id list 去 pubmed 下载引用文件，导入到 endnote
  python pmid_endnote_tools.py extract input.docx -o pubmed_query.txt --list-output pmids.txt
  
  # 从 end note 中导出 pubmed id 和 endnote 引文格式的对照表 endnote_mapping.csv，替换为 endnote 引文格式
  python pmid_endnote_tools.py replace input.xml endnote_mapping.csv -o input_endnote.xml

Notes
-----
提取器支持英文方括号和中文全角方括号中的 PMID 占位符，包括
"PMID: 34140304" 这样的显式标签格式，以及 "[22829357, 28988033]"
这样的无标签 PMID 列表。
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

import pandas as pd


BRACKET_RE = re.compile(r"[\[\u3010]([^\]\u3011]{0,2000})[\]\u3011]")
LABELED_PMID_RE = re.compile(r"PMID\s*[:\uff1a]?\s*(\d+)", re.IGNORECASE)
DIGITS_RE = re.compile(r"(?<!\d)(\d{1,9})(?!\d)")
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

COMMON_OOXML_PARTS_RE = re.compile(
    r"^word/(document|footnotes|endnotes|comments|header\d+|footer\d+)\.xml$"
)


@dataclass
class ReplacementReport:
    """
    记录 PMID 替换过程的统计信息。

    Attributes
    ----------
    replacements : int
        成功替换的引文组数量。
    skipped_missing : int
        因映射表缺失 PMID 而跳过的引文组数量。
    missing_pmids : set[str] | None
        替换过程中发现但未在映射表中找到的 PMID 集合。
    """

    replacements: int = 0
    skipped_missing: int = 0
    missing_pmids: set[str] | None = None

    def __post_init__(self) -> None:
        if self.missing_pmids is None:
            self.missing_pmids = set()


class WordPmidDocument:
    """
    读取、修改并保存 Word `.docx` 或 Word XML 文档。

    Parameters
    ----------
    path : str or pathlib.Path
        输入的 Word 文件路径，支持 `.docx` 和单文件 XML。
    min_unlabeled_digits : int, optional
        无标签数字被视为 PMID 所需的最小位数，默认值为 7。

    Attributes
    ----------
    path : pathlib.Path
        当前处理的输入文件路径。
    is_docx : bool
        输入文件是否为 `.docx`。
    """

    TEXT_TAGS = {"t", "delText", "instrText"}

    def __init__(self, path: str | Path, min_unlabeled_digits: int = 7) -> None:
        """
        初始化 Word PMID 文档对象并立即读取文件内容。

        Parameters
        ----------
        path : str or pathlib.Path
            输入的 `.docx` 或 XML 文件路径。
        min_unlabeled_digits : int, optional
            无标签 PMID 数字的最小长度，默认值为 7。
        """
        self.path = Path(path)
        self.min_unlabeled_digits = min_unlabeled_digits
        self.is_docx = self.path.suffix.lower() == ".docx"
        self._docx_items: list[tuple[zipfile.ZipInfo, bytes]] = []
        self._xml_bytes: bytes | None = None
        self.read()

    def read(self) -> None:
        """
        将 Word 文件内容读取到内存。

        Notes
        -----
        `.docx` 会作为 zip 包读取并保留所有内部文件；XML 文件则直接读取
        原始字节。替换操作会在内存中修改这些字节，直到调用 `save()`。
        """
        # ==============================================================
        # DOCX 是 zip 容器，需要保留每个内部文件的 ZipInfo 和原始字节
        # 这样保存时可以尽量维持原包结构
        # ==============================================================
        if self.is_docx:
            with zipfile.ZipFile(self.path, "r") as zin:
                self._docx_items = [
                    (info, zin.read(info.filename)) for info in zin.infolist()
                ]
            return

        # ==============================================================
        # 单文件 XML 不需要解包，直接保存原始字节等待后续解析或替换
        # ==============================================================
        self._xml_bytes = self.path.read_bytes()

    def save(self, output_path: str | Path) -> None:
        """
        将当前内存中的文档状态保存到目标路径。

        Parameters
        ----------
        output_path : str or pathlib.Path
            输出文件路径。输入为 `.docx` 时会保存为 zip 格式；输入为 XML
            时会写出 XML 字节。

        Raises
        ------
        ValueError
            当 XML 文档尚未加载时抛出。
        """
        output_path = Path(output_path)
        # ==============================================================
        # 对 DOCX 逐项写回 zip，未被修改的内部文件保持原样
        # ==============================================================
        if self.is_docx:
            with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                for info, data in self._docx_items:
                    zout.writestr(info, data)
            return

        if self._xml_bytes is None:
            raise ValueError("No XML document has been loaded.")
        output_path.write_bytes(self._xml_bytes)

    def read_text(self) -> str:
        """
        读取文档中的可见文本。

        Returns
        -------
        str
            从正文、脚注、尾注、批注、页眉和页脚中拼接得到的文本。

        Notes
        -----
        该方法只用于提取 PMID。它会丢失 XML 节点位置，因此不用于写回替换。
        """
        # ==============================================================
        # DOCX 中正文、注释、页眉页脚等内容分散在多个 word/*.xml 文件里
        # 这里只读取可能包含正文文本或引用占位符的常见 OOXML 部件
        # ==============================================================
        if self.is_docx:
            pieces = [
                self._xml_to_text(data)
                for info, data in self._docx_items
                if COMMON_OOXML_PARTS_RE.match(info.filename)
            ]
            return "\n".join(pieces)

        if self._xml_bytes is None:
            raise ValueError("No XML document has been loaded.")
        return self._xml_to_text(self._xml_bytes)

    def extract_pmids(self) -> list[str]:
        """
        从当前 Word 文档中提取去重后的 PMID 列表。

        Returns
        -------
        list[str]
            按首次出现顺序排列的 PMID 字符串列表。
        """
        pmids: list[str] = []
        # ==============================================================
        # PMID 提取只需要纯文本，不需要保留 Word XML 节点位置
        # ==============================================================
        for match in BRACKET_RE.finditer(self.read_text()):
            pmids.extend(
                self.extract_pmids_from_bracket_text(
                    match.group(1), self.min_unlabeled_digits
                )
            )
        return list(dict.fromkeys(pmids))

    def replace_pmids(self, mapping: dict[str, str]) -> ReplacementReport:
        """
        在内存中将 PMID 占位符替换为 EndNote 临时引文。

        Parameters
        ----------
        mapping : dict[str, str]
            PMID 到 EndNote 临时引文内容的映射。值不需要包含外层花括号，
            例如 `"34140304": "Christofield, 2021 #21"`。

        Returns
        -------
        ReplacementReport
            替换结果统计，包括成功替换数量和缺失 PMID。

        Notes
        -----
        替换不能只基于 `read_text()` 的结果完成，因为 Word 会把一段文字拆成
        多个 XML 文本节点。该方法直接操作 XML 节点，以便尽量保留原格式。
        """
        report = ReplacementReport()

        # ==============================================================
        # DOCX 只修改可能包含正文或引用占位符的 OOXML 部件
        # 其他内部文件原样写回，避免破坏文档结构
        # ==============================================================
        if self.is_docx:
            updated_items: list[tuple[zipfile.ZipInfo, bytes]] = []
            for info, data in self._docx_items:
                if COMMON_OOXML_PARTS_RE.match(info.filename):
                    data = self._replace_in_xml_bytes(data, mapping, report)
                updated_items.append((info, data))
            self._docx_items = updated_items
            return report

        if self._xml_bytes is None:
            raise ValueError("No XML document has been loaded.")
        self._xml_bytes = self._replace_in_xml_bytes(self._xml_bytes, mapping, report)
        return report

    @staticmethod
    def extract_pmids_from_bracket_text(
        text: str, min_unlabeled_digits: int = 7
    ) -> list[str]:
        """
        从单个括号引文组内部提取 PMID。

        Parameters
        ----------
        text : str
            一个括号组内部的文本，例如 `"PMID: 34140304"` 或
            `"22829357, 28988033"`。
        min_unlabeled_digits : int, optional
            无标签数字被视为 PMID 所需的最小位数，默认值为 7。

        Returns
        -------
        list[str]
            去重后的 PMID 列表，保留首次出现顺序。
        """
        found: list[str] = []

        # ==============================================================
        # 显式带 PMID 标签的数字可信度最高，优先提取
        # ==============================================================
        found.extend(match.group(1) for match in LABELED_PMID_RE.finditer(text))

        # ==============================================================
        # 无标签数字列表也可能是 PMID；用最小位数避免把 [34] 这类序号误判
        # ==============================================================
        for match in DIGITS_RE.finditer(text):
            value = match.group(1)
            ## PMID 通常为多位数字，短数字更可能是普通参考文献编号
            if len(value) >= min_unlabeled_digits:
                found.append(value)

        return list(dict.fromkeys(found))

    @staticmethod
    def _register_namespaces(xml_bytes: bytes) -> None:
        """
        注册 XML 命名空间以减少写回时的前缀变化。

        Parameters
        ----------
        xml_bytes : bytes
            待解析的 XML 字节。

        Notes
        -----
        该方法主要用于提高写回 XML 的可读性。即使部分命名空间注册失败，
        生成的 XML 通常仍然是合法的。
        """
        try:
            for _event, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("start-ns",)):
                prefix, uri = elem
                ## `xml` 是保留前缀，ElementTree 不需要也不允许重复注册
                if prefix == "xml":
                    continue
                try:
                    ET.register_namespace(prefix, uri)
                except ValueError:
                    # Some prefixes are reserved by ElementTree. The XML remains valid.
                    pass
        except ET.ParseError:
            pass

    @classmethod
    def _xml_to_text(cls, xml_bytes: bytes) -> str:
        """
        从 Word XML 字节中提取文本。

        Parameters
        ----------
        xml_bytes : bytes
            Word XML 或 OOXML 部件的原始字节。

        Returns
        -------
        str
            拼接后的文本内容。解析失败时返回按 UTF-8 忽略错误解码的文本。
        """
        try:
            cls._register_namespaces(xml_bytes)
            root = ET.fromstring(xml_bytes)
        except ET.ParseError:
            return xml_bytes.decode("utf-8", errors="ignore")

        pieces: list[str] = []
        
        # ==============================================================
        # Word 的可见文本通常位于 w:t，删除文本和域代码文本也可能含 PMID
        # ==============================================================
        for elem in root.iter():
            tag_name = elem.tag.rsplit("}", 1)[-1]
            if tag_name in cls.TEXT_TAGS and elem.text:
                pieces.append(elem.text)
        ## 兼容非标准 XML：如果没有典型 Word 文本节点，则退回到所有文本节点
        if not pieces:
            pieces.extend(elem.text for elem in root.iter() if elem.text)
        return "".join(pieces)

    def _replace_in_xml_bytes(
        self,
        xml_bytes: bytes,
        mapping: dict[str, str],
        report: ReplacementReport,
    ) -> bytes:
        """
        在一个 XML 部件中替换 PMID 占位符。

        Parameters
        ----------
        xml_bytes : bytes
            待处理的 XML 字节。
        mapping : dict[str, str]
            PMID 到 EndNote 临时引文内容的映射。
        report : ReplacementReport
            用于累计替换统计信息的报告对象。

        Returns
        -------
        bytes
            替换后的 XML 字节。
        """
        self._register_namespaces(xml_bytes)
        root = ET.fromstring(xml_bytes)

        # ==============================================================
        # 优先按段落处理，确保跨 run 拆分的同一段引用可以被整体识别
        # ==============================================================
        paragraphs = [elem for elem in root.iter() if elem.tag.rsplit("}", 1)[-1] == "p"]
        if paragraphs:
            for paragraph in paragraphs:
                text_nodes = [
                    elem for elem in paragraph.iter() if elem.tag.rsplit("}", 1)[-1] == "t"
                ]
                self._replace_in_text_nodes(text_nodes, mapping, report)
        else:
            ## 兼容没有 Word 段落结构的 XML，直接处理所有文本节点
            text_nodes = [elem for elem in root.iter() if elem.tag.rsplit("}", 1)[-1] == "t"]
            self._replace_in_text_nodes(text_nodes, mapping, report)

        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _replace_in_text_nodes(
        self,
        text_nodes: list[ET.Element],
        mapping: dict[str, str],
        report: ReplacementReport,
    ) -> None:
        """
        在一组连续 XML 文本节点中替换 PMID 占位符。

        Parameters
        ----------
        text_nodes : list[xml.etree.ElementTree.Element]
            同一段落内的 Word 文本节点。
        mapping : dict[str, str]
            PMID 到 EndNote 临时引文内容的映射。
        report : ReplacementReport
            替换统计对象，会在原地更新。

        Notes
        -----
        Word 可能把一个 PMID 占位符拆进多个 `<w:t>` 节点。本方法先把同一
        段落的文本拼成逻辑字符串，再将替换结果映射回原始节点。
        """
        # ==============================================================
        # 将多个 Word 文本节点拼成一个逻辑段落，支持跨 run 匹配 PMID 组
        # ==============================================================
        pieces = [node.text or "" for node in text_nodes]
        paragraph_text = "".join(pieces)
        if not paragraph_text:
            return

        # ==============================================================
        # 先收集所有替换范围，暂不立即修改文本，避免字符偏移提前变化
        # ==============================================================
        replacements: list[tuple[int, int, str]] = []
        for match in BRACKET_RE.finditer(paragraph_text):
            pmids = self.extract_pmids_from_bracket_text(
                match.group(1), self.min_unlabeled_digits
            )
            if not pmids:
                continue

            missing_pmids = [pmid for pmid in pmids if pmid not in mapping]
            if missing_pmids:
                report.skipped_missing += 1
                report.missing_pmids.update(missing_pmids)
                continue

            citation = "{" + "; ".join(mapping[pmid] for pmid in pmids) + "}"
            ## 记录的是逻辑段落字符串中的起止位置，后面再映射回具体 XML 节点
            replacements.append((match.start(), match.end(), citation))
            report.replacements += 1

        if not replacements:
            return

        # ==============================================================
        # 建立逻辑段落字符位置到 XML 文本节点的映射表
        # ==============================================================
        spans: list[tuple[int, int, ET.Element]] = []
        cursor = 0
        for node, piece in zip(text_nodes, pieces):
            spans.append((cursor, cursor + len(piece), node))
            cursor += len(piece)

        # ==============================================================
        # 从右向左应用替换，保证较早位置的字符偏移不会被后续修改影响
        # ==============================================================
        for start, end, new_text in reversed(replacements):
            start_index = start_offset = end_index = end_offset = None
            for index, (span_start, span_end, _elem) in enumerate(spans):
                if start_index is None and span_start <= start <= span_end:
                    start_index = index
                    start_offset = start - span_start
                if end_index is None and span_start <= end <= span_end:
                    end_index = index
                    end_offset = end - span_start
                if start_index is not None and end_index is not None:
                    break

            if start_index is None or start_offset is None:
                ## 理论上不应发生；作为兜底，将位置绑定到最后一个文本节点末尾
                start_index = len(spans) - 1
                start_offset = spans[start_index][1] - spans[start_index][0]
            if end_index is None or end_offset is None:
                end_index = len(spans) - 1
                end_offset = spans[end_index][1] - spans[end_index][0]

            if start_index == end_index:
                node = spans[start_index][2]
                original = node.text or ""
                value = original[:start_offset] + new_text + original[end_offset:]
                node.text = value
                ## 前后空格在 Word XML 中需要显式 preserve，否则可能被压缩
                if value.startswith(" ") or value.endswith(" "):
                    node.set(XML_SPACE, "preserve")
                continue

            start_node = spans[start_index][2]
            end_node = spans[end_index][2]
            start_original = start_node.text or ""
            end_original = end_node.text or ""

            updates = [(start_node, start_original[:start_offset] + new_text)]
            updates.extend(
                (spans[index][2], "") for index in range(start_index + 1, end_index)
            )
            updates.append((end_node, end_original[end_offset:]))
            for node, value in updates:
                node.text = value
                ## 清空中间节点而不是删除节点，可以尽量保留原有 run 格式结构
                if value.startswith(" ") or value.endswith(" "):
                    node.set(XML_SPACE, "preserve")


def load_mapping(path: Path) -> dict[str, str]:
    """
    读取无表头 TSV 格式的 PMID 到 EndNote 临时引文映射表。

    Parameters
    ----------
    path : pathlib.Path
        映射表路径。文件应为两列、制表符分隔、无表头，例如
        `34140304<TAB>{Christofield, 2021 #21}`。

    Returns
    -------
    dict[str, str]
        PMID 到 EndNote 临时引文内容的映射。返回值中的引文不包含外层花括号。

    Raises
    ------
    ValueError
        当文件中没有可用的 PMID/引文记录时抛出。
    """
    # ==============================================================
    # EndNote 导出的映射表固定为无表头 TSV：第一列 PMID，第二列临时引文
    # ==============================================================
    table = pd.read_csv(
        path,
        sep="\t",
        header=None,
        names=["pmid", "citation"],
        usecols=[0, 1],
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    # ==============================================================
    # 清理 PMID 和引文文本；单条引文外层花括号稍后会重新统一添加
    # ==============================================================
    table["pmid"] = table["pmid"].str.strip()
    table["citation"] = (
        table["citation"]
        .str.strip()
        .str.replace(r"^\{|\}$", "", regex=True)
        .str.strip()
    )
    # ==============================================================
    # 只保留 PMID 合法且引文非空的行
    # ==============================================================
    table = table[
        table["pmid"].str.fullmatch(r"\d{1,9}", na=False)
        & table["citation"].ne("")
    ]
    if table.empty:
        raise ValueError(f"Mapping file contains no usable PMID/citation rows: {path}")

    return dict(zip(table["pmid"], table["citation"]))


def command_extract(args: argparse.Namespace) -> int:
    """
    执行 PMID 提取命令并写出 PubMed 查询文本。

    Parameters
    ----------
    args : argparse.Namespace
        命令行解析结果，应包含输入文件、输出路径和最小数字长度等参数。

    Returns
    -------
    int
        命令退出码，成功时返回 0。
    """
    input_path = Path(args.input)
    output_path = (
        Path(args.output)
        if args.output
        else input_path.with_name(input_path.stem + "_pubmed_query.txt")
    )

    document = WordPmidDocument(input_path, args.min_digits)
    pmids = document.extract_pmids()
    
    ## PubMed 批量检索格式：多个 PMID 使用 OR 连接，并附加 [PMID] 字段限定
    query = " OR ".join(f"{pmid}[PMID]" for pmid in pmids)

    output_path.write_text(query + ("\n" if query else ""), encoding="utf-8")

    if args.list_output:
        pmid_list = "\n".join(pmids) + ("\n" if pmids else "")
        Path(args.list_output).write_text(pmid_list, encoding="utf-8")

    print(f"Found {len(pmids)} unique PMID(s).")
    print(f"PubMed query written to: {output_path}")
    if args.list_output:
        print(f"PMID list written to: {args.list_output}")
    return 0


def command_replace(args: argparse.Namespace) -> int:
    """
    执行 PMID 到 EndNote 临时引文的替换命令。

    Parameters
    ----------
    args : argparse.Namespace
        命令行解析结果，应包含输入文件、映射表路径和输出路径。

    Returns
    -------
    int
        命令退出码，成功时返回 0。
    """
    input_path = Path(args.input)
    mapping_path = Path(args.mapping)
    output_path = (
        Path(args.output)
        if args.output
        else input_path.with_name(input_path.stem + "_endnote" + input_path.suffix)
    )

    mapping = load_mapping(mapping_path)
    if not mapping:
        raise ValueError("No usable PMID -> EndNote citation mapping was loaded.")

    # ==============================================================
    # 读取 Word、在内存中替换 PMID、最后保存为新的 Word 文件
    # ==============================================================
    document = WordPmidDocument(input_path, args.min_digits)
    report = document.replace_pmids(mapping)
    document.save(output_path)

    print(f"Loaded {len(mapping)} PMID mapping(s).")
    print(f"Replaced {report.replacements} citation group(s).")
    if report.skipped_missing:
        missing = ", ".join(sorted(report.missing_pmids))
        print(f"Skipped {report.skipped_missing} group(s) because mapping was missing: {missing}")
    print(f"Output written to: {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """
    构建命令行参数解析器。

    Returns
    -------
    argparse.ArgumentParser
        包含 `extract` 和 `replace` 两个子命令的解析器。
    """
    parser = argparse.ArgumentParser(
        description="Extract PMID placeholders and replace them with EndNote temporary citations."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser("extract", help="extract PMIDs and write a PubMed query txt")
    extract.add_argument("input", help="input .xml or .docx file")
    extract.add_argument("-o", "--output", help="output PubMed query txt")
    extract.add_argument("--list-output", help="optional output txt with one PMID per line")
    extract.add_argument(
        "--min-digits",
        type=int,
        default=7,
        help="minimum digit length for unlabeled bracket numbers; default: 7",
    )
    ## 调用函数直接绑定到子命令
    extract.set_defaults(func=command_extract)

    replace = subparsers.add_parser("replace", help="replace PMID placeholders with EndNote citations")
    replace.add_argument("input", help="input .xml or .docx file")
    replace.add_argument("mapping", help="CSV/TSV PMID mapping exported from EndNote")
    replace.add_argument("-o", "--output", help="output .xml or .docx file")
    replace.add_argument(
        "--min-digits",
        type=int,
        default=7,
        help="minimum digit length for unlabeled bracket numbers; default: 7",
    )
    ## 调用函数直接绑定到子命令
    replace.set_defaults(func=command_replace)

    return parser


def main(argv: list[str] | None = None) -> int:
    """
    命令行入口函数。

    Parameters
    ----------
    argv : list[str] or None, optional
        待解析的命令行参数。为 None 时使用系统传入的命令行参数。

    Returns
    -------
    int
        命令退出码，成功时返回 0，异常时返回 1。
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
