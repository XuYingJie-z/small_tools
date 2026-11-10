"""用 PyMuPDF 将 PDF 拆成单页文件，页码从 1 开始。"""

import argparse
from pathlib import Path

import pymupdf


def split_pdf(input_path, prefix, output_dir):
    if not prefix or prefix in {".", ".."} or "/" in prefix or "\\" in prefix:
        raise ValueError("前缀必须是非空文件名，不能包含路径分隔符。")
    output_dir = Path(output_dir)
    with pymupdf.open(input_path) as source:
        if not source.is_pdf or source.needs_pass:
            raise ValueError("请输入无需密码即可打开的 PDF。")
        paths = [output_dir / f"{prefix}_{i + 1}.pdf" for i in range(len(source))]
        for path in paths:
            if path.exists():
                raise FileExistsError(f"文件已存在，为避免覆盖已停止：{path}")
        output_dir.mkdir(parents=True, exist_ok=True)
        for i, path in enumerate(paths):
            with pymupdf.open() as page_pdf:
                page_pdf.insert_pdf(source, from_page=i, to_page=i)
                page_pdf.save(path, deflate=True)
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_pdf", type=Path, help="输入 PDF 路径")
    parser.add_argument("--prefix", required=True, help="输出文件名前缀")
    parser.add_argument("--output-dir", type=Path, help="输出目录，默认是输入文件所在目录")
    args = parser.parse_args()
    paths = split_pdf(args.input_pdf, args.prefix, args.output_dir or args.input_pdf.parent)
    print(f"已拆分为 {len(paths)} 个单页 PDF。")
