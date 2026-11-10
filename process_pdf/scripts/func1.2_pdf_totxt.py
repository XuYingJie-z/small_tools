# %% [markdown]
# # 提取 PDF 正文并整理段落，保存成 txt 文件

# 从上到下运行各单元，或直接运行整个文件；只读取现有文字层，不再运行 OCR。
# 适用于单栏、横向文字的扫描论文。段落和断词恢复采用可调规则，仍需人工核对。

# %% 选择 PDF 与页码
from pathlib import Path
from statistics import median
import re

import pymupdf

pdf_path = Path("../data/processed/pdf_1.pdf")
output_dir = Path("../data/func1.2_pdf_totxt")
output_dir.mkdir(parents=True, exist_ok=True)
output_prefix = "pdf_1_method"  # 可选，输出文件名前缀；留空则根据 pdf 文件名自动生成。

first_page = 41  # 阅读器中从 1 开始的物理页码，不是纸面上印刷的页码。
last_page = 68   # 包含此页。

# 比例相对于整页高度；例如 0.12 表示排除顶部 12%。请按实际页面调整。
header_ratio = 0.078
footer_ratio = 0.088

# %% 按固定比例排除页眉、页脚，保留文字与位置


if not (0 <= header_ratio < 1 and 0 <= footer_ratio < 1
        and header_ratio + footer_ratio < 1):
    raise ValueError("页眉和页脚比例必须非负，且合计小于 1。")

page_lines = []
with pymupdf.open(pdf_path) as pdf:
    if not 1 <= first_page <= last_page <= len(pdf):
        raise ValueError(f"页码范围应在 1–{len(pdf)} 内，且起始页不大于结束页。")
    for page_number in range(first_page, last_page + 1):
        page = pdf[page_number - 1]
        # 裁剪页眉页脚
        top = page.rect.y0 + page.rect.height * header_ratio
        bottom = page.rect.y1 - page.rect.height * footer_ratio
        fragments = []
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block["type"] != 0:  # 图片块不包含可提取的文字。
                continue
            for line in block["lines"]:
                text = "".join(span["text"] for span in line["spans"]).strip()
                x0, y0, x1, y1 = line["bbox"]
                # 按文字行中心筛选，避免裁剪边界穿过字符时只提取半行。
                if text and top <= (y0 + y1) / 2 <= bottom:
                    fragments.append({"text": text, "box": [x0, y0, x1, y1]})

        # 同一视觉行有时被 PDF 分成多个片段，先按位置拼回一行。
        fragments.sort(key=lambda item: (item["box"][1], item["box"][0]))
        rows = []
        for fragment in fragments:
            box = fragment["box"]
            if rows:
                previous_box = rows[-1]["box"]
                tolerance = 0.35 * min(box[3] - box[1], previous_box[3] - previous_box[1])
                same_row = abs((box[1] + box[3] - previous_box[1] - previous_box[3]) / 2) <= tolerance
            else:
                same_row = False
            if same_row:
                rows[-1]["parts"].append(fragment)
                rows[-1]["box"] = [
                    min(previous_box[0], box[0]), min(previous_box[1], box[1]),
                    max(previous_box[2], box[2]), max(previous_box[3], box[3]),
                ]
            else:
                rows.append({"parts": [fragment], "box": box.copy()})
        for row in rows:
            # 片段间先保留空格，后面的中文清理规则会去掉汉字之间的多余空格。
            row["text"] = " ".join(
                part["text"] for part in sorted(row.pop("parts"), key=lambda part: part["box"][0])
            )
        page_lines.append({"page": page_number, "lines": rows})
        print(f"第 {page_number} 页：保留 {len(rows)} 行，正文纵向范围 {top:.1f}–{bottom:.1f} point")

# %% 清理空格与英文行末断词
join_hyphenated_words = True  # 例如 schizophre- + nia → schizophrenia。
# 真实复合词的行末连字符可能被误删；若文档此类词很多，可关闭此选项后人工处理。


def clean_text(text):
    text = re.sub(r"\s+", " ", text).strip()
    # OCR 可能在汉字间插入空格；保留英文单词之间和中英文之间的已有空格。
    return re.sub(r"(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])", "", text)


def join_lines(left, right):
    """连接属于同一段落的两行，兼顾中英文与显式断词。"""
    left, right = left.rstrip(), right.lstrip()
    if not left or not right:
        return left + right
    if join_hyphenated_words and re.search(r"[A-Za-z][-\u00ad]$", left) and re.match(r"[a-z]", right):
        return left[:-1] + right
    if left.endswith(("-", "\u00ad")):
        return left + right
    # 中文换行通常不需要空格；英文跨行则保留单词边界。
    if re.search(r"[\u3400-\u9fff]$", left) or re.match(r"[\u3400-\u9fff，。；：！？、）】]", right):
        return left + right
    return left + " " + right


# %% 根据缩进、行距和标题位置恢复段落，并尝试跨页续接
indent_factor = 0.9       # 行首比正文左边界多缩进多少个行高时，视为新段落。
gap_factor = 1.5          # 相邻行顶部间距超过本页常规间距的此倍数时，视为新段落。
short_line_ratio = 0.75   # 上一行短于常规正文宽度的此比例且以句号等结尾时，另起段落。
merge_across_pages = True
merge_after_sentence = False  # 跨页时，上一页以完整句结束则默认不续接；可按需要开启。

paragraphs = []
previous = None
sentence_end = re.compile(r"[。！？.!?][\"'”’）)】\]]*$")

for page_data in page_lines:
    lines = page_data["lines"]
    if not lines:
        previous = None  # 空白页或裁剪后无文字时，不跨过该页合并。
        continue
    heights = [line["box"][3] - line["box"][1] for line in lines]
    line_height = median(heights)
    left_edges = sorted(line["box"][0] for line in lines)
    # 用偏左的分位位置估计正文左边界，减少个别边缘噪声的影响。
    body_left = left_edges[len(left_edges) // 5]
    body_right = max(line["box"][2] for line in lines)
    body_width = max(body_right - body_left, line_height)
    steps = [b["box"][1] - a["box"][1] for a, b in zip(lines, lines[1:])]
    normal_step = median([step for step in steps if step > 0] or [line_height])

    for line_index, line in enumerate(lines):
        text = clean_text(line["text"])
        x0, y0, x1, y1 = line["box"]
        indented = x0 - body_left > indent_factor * line_height
        short = x1 - x0 < short_line_ratio * body_width
        centered = abs((x0 + x1 - body_left - body_right) / 2) < line_height
        # ponytail: 仅以短且居中的行、少数明确标题识别标题；复杂标题或多栏需专门版面分析。
        heading = (short and centered) or bool(re.fullmatch(
            r"摘要|Abstract|关键词[：:]?.*|Key\s*words[：:]?.*", text, flags=re.IGNORECASE
        ))
        new_paragraph = previous is None or heading or previous["heading"] or indented
        if previous is not None and not new_paragraph:
            if line_index == 0:
                new_paragraph = (
                    not merge_across_pages
                    or (not merge_after_sentence and bool(sentence_end.search(previous["text"])))
                )
            else:
                new_paragraph = (
                    y0 - previous["y0"] > gap_factor * normal_step
                    or (previous["short"] and bool(sentence_end.search(previous["text"])))
                )
        if new_paragraph:
            paragraphs.append(text)
        else:
            paragraphs[-1] = join_lines(paragraphs[-1], text)
        previous = {"text": text, "y0": y0, "short": short, "heading": heading}

# %% 保存正文与逐行对照，便于检查裁剪范围和段落边界
if not output_prefix:
    output_prefix = f"{pdf_path.stem}_pages_{first_page}-{last_page}"
paragraph_path = output_dir / f"{output_prefix}_paragraphs.txt"
lines_path = output_dir / f"{output_prefix}_lines.txt"
# 重跑会覆盖这两个文本文件；原 PDF 不会被修改。
paragraph_path.write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")
lines_path.write_text(
    "\n\n".join(
        f"--- 第 {item['page']} 页 ---\n" + "\n".join(line["text"] for line in item["lines"])
        for item in page_lines
    ) + "\n",
    encoding="utf-8",
)
print(f"段落文本：{paragraph_path}")
print(f"逐行对照：{lines_path}")
print(f"共整理 {len(paragraphs)} 个段落；以下预览前 300 字：")
print("\n\n".join(paragraphs)[:300])
