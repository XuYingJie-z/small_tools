# %% [markdown]
# # 图片合并与 PaddleOCR 文字层
# 
# 功能：图片合并成一个 PDF，并在每页上添加 OCR 文字层，使 PDF 可搜索、选择和复制。
# - pdf_process 环境, 在 /dssg/home/acct-bioxsyy/bioxsyy-xyj/xyj/software/uv_env/pdf_process/.venv/bin/activate
# - 我好像没安装 jupyter 直接用 python 也可以。也适合改成脚本直接跑
# - 保留原始图片外观；文字层用于搜索、选择和复制，不重新排版正文。

# %%
from pathlib import Path

import pymupdf
from natsort import natsorted




# %%
## 路径都在这里设置，最好不要一样，并行时不会相互占用


_input_name = "pdf_3"  

input_dir =  Path(f"../data/rawdata/{_input_name}")
output_dir = Path("../data/func1.1_images_to_pdf") 
output_dir.mkdir(parents=True, exist_ok=True)
## 输出 pdf
image_pdf_path = output_dir / f"{_input_name}_origin.pdf"
searchable_pdf_path = output_dir / f"{_input_name}.pdf"
ocr_dir = output_dir / f"{_input_name}_ocr"
ocr_dir.mkdir(exist_ok=True)


# %%

image_paths = natsorted(
    [p for p in input_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}],
    key=lambda p: p.name,
)
if not image_paths:
    raise FileNotFoundError(f"没有找到 JPG、PNG 或 BMP 图片：{input_dir}")

for page_number, image_path in enumerate(image_paths, start=1):
    print(f"第 {page_number} 页：{image_path.name}")
    if page_number > 20:
        print("仅显示前 20 页，后续页略。")
        break

print(len(image_paths), "张图片将被合并为 PDF。")    

# %%
# DPI 仅决定 PDF 页面的物理尺寸，不改变原图像素或 OCR 分辨率。
image_dpi = 150
# 按页保存原图的像素尺寸，后面将 OCR 的像素坐标换算为 PDF 页面坐标。
image_sizes = []
with pymupdf.open() as image_pdf:
    for image_path in image_paths:
        pixmap = pymupdf.Pixmap(str(image_path))
        image_sizes.append((pixmap.width, pixmap.height))
        # PDF 的长度单位为 point，1 英寸 = 72 point；每张图片对应一页。
        page = image_pdf.new_page(
            width=pixmap.width * 72 / image_dpi,
            height=pixmap.height * 72 / image_dpi,
        )
        page.insert_image(page.rect, filename=str(image_path))  # 原图铺满与其比例一致的页面。
    image_pdf.save(image_pdf_path, deflate=True)

print(f"图片 PDF：{image_pdf_path}")

# %%
from paddleocr import PaddleOCR

device = "cpu"  # GPU 服务器安装 paddlepaddle-gpu 后改为 "gpu:0"。
ocr = PaddleOCR(
    device=device,
    text_detection_model_name="PP-OCRv5_mobile_det",  # 检测文字区域；mobile 模型适合先用 CPU 测试。
    text_recognition_model_name="PP-OCRv5_mobile_rec",  # 识别区域内的文字，支持中英文。
    # 保持 OCR 坐标与原图一致；适用于当前正向扫描页。
    use_doc_orientation_classify=False,  # 不自动旋转整页。
    use_doc_unwarping=False,  # 不做文档弯曲矫正，避免改变原图中的文字位置。
    use_textline_orientation=False,  # 当前图片的文字行方向正常，无需额外方向模型。
    cpu_threads=4,  # CPU 推理线程数。
    enable_mkldnn=False,  # 此版使用已验证的非 MKL-DNN 推理路径。
)

# %%
# 内置 CJK 字体支持中文复制，无需单独安装中文字体。
font = pymupdf.Font("china-s")

min_score = 0.5 # 低于此置信度的文字不写入 PDF；JSON 仍保存本次 OCR 返回的结果。
line_counts = []

with pymupdf.open(image_pdf_path) as pdf:
    for page_index, image_path in enumerate(image_paths):
        # predict 返回可迭代的结果；这里一次只传入一张图片，因此取第一个结果。
        result = next(iter(ocr.predict(str(image_path))))
        result.save_to_json(str(ocr_dir / f"{image_path.name}.json"))
        page = pdf[page_index]
        image_width, image_height = image_sizes[page_index]
        # 分别换算横纵坐标，使文字层与对应 PDF 页上的原图位置匹配。
        scale_x = page.rect.width / image_width
        scale_y = page.rect.height / image_height
        line_count = 0

        # 三个列表分别是文字、置信度和四边形框；strict=True 可发现列表长度不一致。
        for text, score, polygon in zip(
            result["rec_texts"], result["rec_scores"], result["rec_polys"], strict=True
        ):
            if not text.strip() or score < min_score:
                continue

            # 取四边形的横纵坐标极值，并将外接矩形限制在页面范围内。
            x0 = max(0, min(float(p[0]) for p in polygon) * scale_x)
            y0 = max(0, min(float(p[1]) for p in polygon) * scale_y)
            x1 = min(page.rect.width, max(float(p[0]) for p in polygon) * scale_x)
            y1 = min(page.rect.height, max(float(p[1]) for p in polygon) * scale_y)
            if x1 <= x0 or y1 <= y0:
                continue  # 跳过裁剪后没有面积的文字框。

            # ascender / descender 是相对于字号的字体上下边界，用框高反推字号。
            fontsize = (y1 - y0) / (font.ascender - font.descender)
            text_width = font.text_length(text, fontsize=fontsize)
            if text_width <= 0:
                continue
            # insert_text 的插入点是文字基线的起点，不是文字框左上角。
            baseline = pymupdf.Point(x0, y0 + fontsize * font.ascender)
            page.insert_text(
                baseline,
                text,
                fontname="china-s",
                fontsize=fontsize,
                render_mode=3,  # 不可见，但可以搜索、选择和复制。
                # 围绕基线起点横向缩放，使整行宽度贴合 OCR 框；纵向比例保持为 1。
                morph=(baseline, pymupdf.Matrix((x1 - x0) / text_width, 1)),
            )
            line_count += 1

        line_counts.append(line_count)
        print(f"[{page_index + 1}/{len(image_paths)}] {image_path.name}：写入 {line_count} 行")

    # 清理冗余 PDF 对象并压缩数据流；另存文件，保留前面的纯图片 PDF。
    pdf.save(searchable_pdf_path, garbage=4, deflate=True)

# %%
page_texts = []
with pymupdf.open(image_pdf_path) as original, pymupdf.open(searchable_pdf_path) as result_pdf:
    assert len(result_pdf) == len(image_paths), "输出页数与图片数量不一致"
    for page_index, page in enumerate(result_pdf):
        text = page.get_text()  # 从已保存的 PDF 读取文字层，而不是直接使用 OCR 的字符串。
        if line_counts[page_index]:
            assert text.strip(), f"第 {page_index + 1} 页的文字层无法提取"
        else:
            print(f"提示：第 {page_index + 1} 页没有识别出满足阈值的文字，请检查原图或 JSON。")
        # 将前后两页以相同设置渲染为图片，比对像素摘要，确认隐藏文字未改变外观。
        assert page.get_pixmap().digest == original[page_index].get_pixmap().digest, (
            f"第 {page_index + 1} 页添加文字层后外观发生变化"
        )
        page_texts.append(text)

text_path = output_dir / "searchable.txt"
# 用换页符 \f 分隔各页；可检查识别结果，但文字可提取并不代表 OCR 内容完全准确。
text_path.write_text("\n\f\n".join(page_texts), encoding="utf-8")
print(f"可搜索 PDF：{searchable_pdf_path}")
print(f"提取文字：{text_path}")


