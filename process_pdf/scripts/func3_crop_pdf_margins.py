# %% 1. 设置输入 PDF（依赖：pip install pymupdf Pillow）
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile

import pymupdf
from PIL import Image, ImageChops

# 文件保存直接放在相同目录的 _cropped.pdf
input_path = Path("./pdf/Fig_v2_pure.pdf")  # 相对于当前工作目录，也可以填写绝对路径。
output_path = input_path.with_name(input_path.stem + "_cropped.pdf")


if input_path.suffix.lower() != ".pdf":
    raise ValueError("只接受 .pdf 文件。")
if not input_path.is_file():
    raise FileNotFoundError(input_path)


# %% 2. 逐页识别非白色内容，汇总所有页面的最外侧边界
white_threshold = 245  # RGB 三个通道均 >= 此值才算白色；调低会忽略更多浅色内容。
render_dpi = 144  # 仅用于识别边界，不会降低输出 PDF 中图片、文字或矢量图的清晰度。

if not 1 <= white_threshold <= 255:
    raise ValueError("white_threshold 应在 1 到 255 之间。")
if not isinstance(render_dpi, int) or render_dpi <= 0:
    raise ValueError("render_dpi 必须是正整数。")

content_rect = None
blank_pages = []
with pymupdf.open(input_path) as pdf:
    # 同时检查真实格式，避免其他文件仅通过改后缀被当成 PDF。
    if not pdf.is_pdf:
        raise ValueError("文件内容不是 PDF。")
    if pdf.needs_pass:
        raise ValueError("请先解密 PDF，再运行本脚本。")
    if not len(pdf):
        raise ValueError("PDF 中没有页面。")
    page_count = len(pdf)
    page_rect = pdf[0].rect
    scale = render_dpi / 72  # PDF 坐标单位为 point，72 point = 1 英寸。
    threshold_table = [255 if value < white_threshold else 0 for value in range(256)]

    for page_index, page in enumerate(pdf):
        # 统一框使用阅读器中显示的坐标，因此比较旋转后的页面宽高。
        # ponytail: 只处理原始显示尺寸一致的 PDF；混合尺寸需另行定义对齐或补白规则。
        if page.rect != page_rect:
            raise ValueError(f"第 {page_index + 1} 页尺寸与第 1 页不同，无法直接使用统一裁剪框。")

        pix = page.get_pixmap(dpi=render_dpi, colorspace=pymupdf.csRGB, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        red, green, blue = image.split()
        # 取三个通道的最小值，避免把亮黄色等彩色内容误当成白色。
        darkest = ImageChops.darker(ImageChops.darker(red, green), blue)
        bbox = darkest.point(threshold_table).getbbox()
        if bbox is None:
            blank_pages.append(page_index + 1)
            continue  # 空白页不参与计算边界，但仍会保留并使用同一个裁剪框。

        # 像素边界映射回显示坐标；使用渲染比例，避免像素取整造成尺寸偏差。
        bounds = pymupdf.Rect(
            (bbox[0] + pix.x) / scale, (bbox[1] + pix.y) / scale,
            (bbox[2] + pix.x) / scale, (bbox[3] + pix.y) / scale,
        ) & page_rect
        # 矩形并集取最靠外的左、上、右、下边界，保证包含每一页识别出的内容。
        content_rect = bounds if content_rect is None else content_rect | bounds

print(f"共 {page_count} 页；按当前阈值识别的空白页：{blank_pages or '无'}")


# %% 3. 给统一裁剪框添加少量留白，并限制在原页面以内
margin_mm = 3  # 四周额外保留的白边，单位毫米；设为 0 可紧贴识别到的内容。

if not isfinite(margin_mm) or margin_mm < 0:
    raise ValueError("margin_mm 必须是有限的非负数。")
margin = margin_mm * 72 / 25.4
if content_rect is None:
    crop_rect = pymupdf.Rect(page_rect)
    print("所有页面均判定为空白，保留原页面尺寸。")
else:
    crop_rect = pymupdf.Rect(
        content_rect.x0 - margin, content_rect.y0 - margin,
        content_rect.x1 + margin, content_rect.y1 + margin,
    ) & page_rect

print(f"统一裁剪框（point）：{tuple(round(value, 2) for value in crop_rect)}")
print(f"统一页面尺寸：{crop_rect.width * 25.4 / 72:.2f} × "
      f"{crop_rect.height * 25.4 / 72:.2f} mm")


# %% 4. 修改原 PDF 的可见范围并另存，不把页面重新编码成图片

# 先写临时文件，保存成功后再替换输出；重跑覆盖同名结果，原始 PDF 不变。
with NamedTemporaryFile(dir=output_path.parent, suffix=".pdf", delete=False) as temp:
    temp_path = Path(temp.name)
try:
    with pymupdf.open(input_path) as pdf:
        for page in pdf:
            # CropBox 要求未旋转坐标；同时加回已有裁剪框的偏移，兼容旋转和预先裁剪的页面。
            unrotated_rect = crop_rect * page.derotation_matrix
            offset = page.cropbox_position
            unrotated_rect += (offset.x, offset.y, offset.x, offset.y)
            page.set_cropbox(unrotated_rect)
        # 只修改可见边界，保留原有文字、矢量图和图片；不保证文件体积明显减小。
        pdf.save(temp_path, deflate=True)
    temp_path.replace(output_path)
finally:
    temp_path.unlink(missing_ok=True)

print(f"已保存：{output_path}")
