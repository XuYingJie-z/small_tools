# %% [markdown]
# # 压缩 docx 中的图片，降低像素尺寸，保留原来的图片格式

# - 只有一个参数控制，就是下面的 dpi 


# %% 1. 设置输入文件和目标 DPI（依赖 Pillow：pip install Pillow）
from io import BytesIO
from math import ceil, isfinite
from pathlib import Path
import posixpath
from tempfile import NamedTemporaryFile
from urllib.parse import unquote
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from PIL import Image, UnidentifiedImageError

input_path = Path("input.docx")  # 相对路径以当前工作目录为准，也可以填写绝对路径。
dpi = 200  # 数值越低，保留的像素越少；图片在 Word 中的位置和显示尺寸不变。

if not isfinite(dpi) or dpi <= 0:
    raise ValueError("dpi must be a finite positive number")
if not input_path.is_file():
    raise FileNotFoundError(input_path)


# %% 2. 读取图片在文档中的显示尺寸，包括正文、页眉和页脚
# XML 命名空间简称表：这些网址只是标签的标识符，不会访问网络。
ns = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",  # 图形信息，如图片引用和宽高。
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",  # Word 中的放置方式。
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",  # 图片对象。
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",  # 引用与文件之间的关联。
}
image_sizes = {}  # 图片文件路径 -> 所需的最大显示宽度、高度，单位为英寸。
blocked_images = set()  # 存在无法可靠解析的用法时，整张图片保留原样。

# DOCX 本质上是 ZIP 包，可以直接读取内部 XML 和图片，无需解压到磁盘。
with ZipFile(input_path) as doc:
    names = set(doc.namelist())
    for part in sorted(names):
        if not part.startswith("word/") or not part.endswith(".xml"):
            continue
        folder, filename = posixpath.split(part)
        # 每个文档部件有自己的关联表，例如 document.xml 对应 _rels/document.xml.rels。
        rels_path = posixpath.join(folder, "_rels", filename + ".rels")
        if rels_path not in names:
            continue
        relationships = {}
        for rel in ET.fromstring(doc.read(rels_path)):
            # 只处理嵌入文档的图片，忽略指向外部文件或网址的链接。
            if (rel.get("Type", "").endswith("/image")
                    and rel.get("TargetMode") != "External"):
                target = unquote(rel.attrib["Target"])
                # 将相对路径和 URI 转义还原为 ZIP 内部路径；这里始终使用正斜杠。
                relationships[rel.attrib["Id"]] = posixpath.normpath(
                    posixpath.join(folder, target)
                ).lstrip("/")
        if not relationships:
            continue

        root = ET.fromstring(doc.read(part))
        handled = set()  # 记录已经成功读取显示尺寸的图片引用节点。
        # inline 是嵌入式图片，anchor 是浮动式图片。
        drawings = root.findall(".//wp:inline", ns) + root.findall(".//wp:anchor", ns)
        for drawing in drawings:
            picture = drawing.find("a:graphic/a:graphicData/pic:pic", ns)
            if picture is None:
                continue
            blip = picture.find("pic:blipFill/a:blip", ns)
            # 优先读取图片自身的尺寸，没有时再读取外层绘图对象的尺寸。
            extent = picture.find("pic:spPr/a:xfrm/a:ext", ns)
            if extent is None:
                extent = drawing.find("wp:extent", ns)
            if blip is None or extent is None:
                continue
            # ElementTree 用“{命名空间}属性名”表示 r:embed，再通过关联表找到图片文件。
            image_path = relationships.get(blip.get(f"{{{ns['r']}}}embed"))
            if image_path is None:
                continue
            crop = picture.find("pic:blipFill/a:srcRect", ns)
            # ponytail: 暂不处理裁剪图、组合图和旧式图片；需要支持时再补充坐标变换解析。
            if crop is not None and any(int(value) for value in crop.attrib.values()):
                continue
            width, height = int(extent.get("cx", 0)), int(extent.get("cy", 0))
            if width <= 0 or height <= 0:
                continue
            handled.add(blip)
            # Word 的尺寸单位是 EMU，914400 EMU = 1 英寸。
            # 同一图片可能在多处使用，宽高分别取最大需求，避免大尺寸位置被过度压缩。
            previous = image_sizes.get(image_path, (0, 0))
            image_sizes[image_path] = (
                max(previous[0], width / 914400),
                max(previous[1], height / 914400),
            )

        # 同一文件只要有一处引用未被正确解析，就不压缩，避免影响那一处的显示。
        for element in root.iter():
            if element in handled:
                continue
            for attr in ("embed", "link", "id"):
                image_path = relationships.get(element.get(f"{{{ns['r']}}}{attr}"))
                if image_path is not None:
                    blocked_images.add(image_path)

print(f"Found displayed sizes for {len(image_sizes)} images")


# %% 3. 降低超标 JPEG/PNG 的像素尺寸，保留原来的图片格式
replacements = {}  # 只保存确实变小的图片数据，供最后写回 DOCX。
with ZipFile(input_path) as doc:
    media_paths = [name for name in doc.namelist()
                   if name.startswith("word/media/") and not name.endswith("/")]
    for image_path in media_paths:
        if image_path not in image_sizes or image_path in blocked_images:
            continue
        original = doc.read(image_path)
        try:
            with Image.open(BytesIO(original)) as img:
                # 矢量图、其他格式和动画保留原样。
                if img.format not in {"JPEG", "PNG"} or getattr(img, "is_animated", False):
                    continue
                width_inches, height_inches = image_sizes[image_path]
                # 目标像素数 = 显示尺寸（英寸）× dpi，再除以原像素数得到缩放比例。
                # 宽高取较大的比例以同时满足两边需求；上限为 1，确保不会放大原图。
                scale = min(1, max(width_inches * dpi / img.width,
                                   height_inches * dpi / img.height))
                # 宽高使用同一比例，向上取整并至少保留 1 个像素。
                size = (max(1, ceil(img.width * scale)), max(1, ceil(img.height * scale)))
                if size == img.size:
                    continue
                # 调色板图和黑白位图先转换模式，以便平滑缩放；有透明背景时保留透明通道。
                pixels = img
                if img.mode in {"P", "1"}:
                    pixels = img.convert("RGBA" if "transparency" in img.info else "RGB")
                resized = pixels.resize(size, Image.Resampling.LANCZOS)
                # 保留色彩配置、EXIF 和原 DPI 标签；实际压缩来自像素减少，而不是修改标签。
                options = {key: img.info[key] for key in ("icc_profile", "exif", "dpi")
                           if key in img.info}
                if "transparency" in img.info and img.mode not in {"P", "1"}:
                    options["transparency"] = img.info["transparency"]
                if img.format == "JPEG":
                    options["quality"] = 85  # JPEG 编码质量固定，日常只调整上面的 dpi。
                buffer = BytesIO()
                resized.save(buffer, format=img.format, optimize=True, **options)
                compressed = buffer.getvalue()
                # 重新编码偶尔会使文件变大，此时保留原图。
                if len(compressed) < len(original):
                    replacements[image_path] = compressed
                    print(f"{Path(image_path).name}: {img.size} -> {size}, "
                          f"{len(original) / 1024:.0f} -> {len(compressed) / 1024:.0f} KiB")
        except (UnidentifiedImageError, OSError) as error:
            print(f"Skipped {image_path}: {error}")


# %% 4. 在原文件旁另存结果，其余文档内容保持不变
output_path = input_path.with_name(input_path.stem + "_compressed.docx")
# 先写同目录临时文件，完整写入并校验后再替换输出文件，避免中途中断留下不完整结果。
with NamedTemporaryFile(dir=output_path.parent, suffix=".docx", delete=False) as temp:
    temp_path = Path(temp.name)
try:
    with ZipFile(input_path) as source, ZipFile(temp_path, "w") as output:
        output.comment = source.comment
        for entry in source.infolist():
            # 仅替换选中的图片数据；排版 XML、文字和关联表等均按原内容复制。
            data = replacements[entry.filename] if entry.filename in replacements else source.read(entry)
            output.writestr(entry, data)
    with ZipFile(temp_path) as output:
        # 检查 ZIP 各条目的完整性，不涉及 Word 排版渲染。
        assert output.testzip() is None, "Output archive failed its integrity check"
    temp_path.replace(output_path)  # 重跑会覆盖同名压缩结果，原始 DOCX 不变。
finally:
    temp_path.unlink(missing_ok=True)

# 统计整个 DOCX 的实际体积；未修改数量包括无需降采样和不支持处理的媒体文件。
before, after = input_path.stat().st_size, output_path.stat().st_size
print(f"Saved: {output_path}")
print(f"Compressed: {len(replacements)}; unchanged/skipped: {len(media_paths) - len(replacements)}")
print(f"Size: {before / 1024**2:.2f} -> {after / 1024**2:.2f} MiB "
      f"({(1 - after / before) * 100:.1f}% smaller)")
