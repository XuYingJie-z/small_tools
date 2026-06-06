from pathlib import Path


from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling_core.types.doc import CoordOrigin, ImageRefMode, PictureItem, TextItem

# ==============================================================
# 设置输入 PDF 路径和输出目录。
# ==============================================================
## 需要转换的源 PDF 文件。
source = "./drive/MyDrive/docling/aay3983_zhang_sm.pdf"
## 生成 Markdown 文件的输出目录。
output_dir = Path(".//drive/MyDrive/docling/output_result")
output_dir.mkdir(parents=True, exist_ok=True)
## Markdown 引用图片时使用的图片目录。
image_dir = output_dir / "images"
image_dir.mkdir(parents=True, exist_ok=True)

# ==============================================================
# 配置 PDF 转换行为。
# ==============================================================
pipeline_options = PdfPipelineOptions()
## 数值越高，提取图片越清晰，但文件体积和处理耗时也会增加。
pipeline_options.images_scale = 2.0
## 开启 OCR，用于识别扫描件或图片型 PDF 中的文字。
pipeline_options.do_ocr = True
## 必须开启，否则 PictureItem.get_image(doc) 可能无法返回裁剪后的图片。
pipeline_options.generate_picture_images = True
# pipeline_options.generate_table_images = True

## 创建 PDF 转换器。
converter = DocumentConverter(
    format_options={
        ## 只对 PDF 输入应用这套转换配置。
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
    }
)


# 将 PDF 转换为 DoclingDocument。
print("Processing document...")
result = converter.convert(source)
## Docling 转换后得到的主文档对象。
doc = result.document

# ==============================================================
# 配置页眉页脚过滤规则。设置过滤页眉页脚
# 如果页眉页脚仍有残留，可以调大比例；如果误删正文内容，可以调小比例。
# ==============================================================
## 页面顶部多少比例视为页眉区域。
TOP_MARGIN_RATIO = 0.14
## 页面底部多少比例视为页脚区域。
BOTTOM_MARGIN_RATIO = 0.10
## 需要从页眉页脚区域删除的元素类型。
HEADER_FOOTER_ITEM_TYPES = (PictureItem, TextItem)

# ==============================================================
# 在保存图片和导出 Markdown 前，先删除页眉页脚元素。
# 这里会同时删除重复 logo、页眉图片、页码、期刊名等文本内容。
# ==============================================================
skipped_item_counter = 0
## 先收集待删除元素，遍历结束后再统一删除，避免边遍历边修改文档结构。
items_to_delete = []

for element, _level in doc.iterate_items():
    ## 只检查配置中指定的元素类型。
    if isinstance(element, HEADER_FOOTER_ITEM_TYPES):
        should_skip_item = False

        ## prov 中记录了元素所在页码和 bbox 位置信息。
        if element.prov:
            prov = element.prov[0]
            ## 根据页码取出页面尺寸
            page = doc.pages.get(prov.page_no)

            if page and page.size:
                bbox = prov.bbox

                ## 将 bbox 统一转换成左上角坐标系，方便判断顶部和底部区域。
                if bbox.coord_origin == CoordOrigin.BOTTOMLEFT:
                    bbox = bbox.to_top_left_origin(page.size.height)

                ## 元素整体位于页眉区域时为 True，元素整体位于页脚区域时为 True。
                in_top_margin = bbox.b <= page.size.height * TOP_MARGIN_RATIO
                in_bottom_margin = bbox.t >= page.size.height * (1 - BOTTOM_MARGIN_RATIO)

                print(
                    f"Item check: {type(element).__name__}, {element.self_ref}, "
                    f"page={prov.page_no}, "
                    f"top_margin={in_top_margin}, "
                    f"bottom_margin={in_bottom_margin}, "
                    f"bbox_top={bbox.t:.2f}, bbox_bottom={bbox.b:.2f}, "
                    f"page_height={page.size.height:.2f}"
                )

                ## 如果元素完整落在页眉或页脚区域，就标记为待删除。
                if in_top_margin or in_bottom_margin:
                    should_skip_item = True

        if should_skip_item:
            items_to_delete.append(element)
            skipped_item_counter += 1
            print(f"Skipped header/footer item: {type(element).__name__}, {element.self_ref}")

## 在保存图片和导出 Markdown 前，从 Docling 文档结构中删除页眉页脚元素。
if items_to_delete:
    doc.delete_items(node_items=items_to_delete)

# ==============================================================
# 保存剩余正文图片，并更新 Markdown 中引用图片的路径。
# 页眉页脚图片已经在上一步从文档中删除。
# ==============================================================
image_counter = 0

for element, _level in doc.iterate_items():
    ## 只需要为剩余的 PictureItem 保存图片文件。
    if isinstance(element, PictureItem):
        ## 安全获取该图片元素对应的裁剪图片。
        pil_img = element.get_image(doc)

        if pil_img:
            ## 使用 Docling 的 self_ref 末尾编号生成稳定的图片文件名。
            image_id = element.self_ref.split("/")[-1]
            image_filename = f"image_{image_id}.png"
            image_path = image_dir / image_filename

            ## 将提取出的图片保存到 images 目录。
            pil_img.save(image_path)
            image_counter += 1
            print(f"Saved image: {image_filename}")

            ## 重写图片 URI，让 Markdown 引用刚刚保存的相对路径。
            if element.image:
                element.image.uri = f"images/{image_filename}"

## 将过滤后的文档导出为 Markdown。 REFERENCED 模式会生成图片链接，而不是把图片以内联形式写入 Markdown。
md_content = doc.export_to_markdown(image_mode=ImageRefMode.REFERENCED)

## 最终 Markdown 文件路径。
md_file_path = output_dir / "Qian.md"
## 以 UTF-8 写入 Markdown 文本。
with open(md_file_path, "w", encoding="utf-8") as f:
    f.write(md_content)

# ==============================================================
# 输出本次转换的简要统计信息。
# ==============================================================
print("\nDone.")
print(f"Saved body images: {image_counter}")
print(f"Skipped header/footer items: {skipped_item_counter}")
print(f"Markdown file: {md_file_path}")
