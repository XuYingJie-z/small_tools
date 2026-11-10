# PDF 与文档处理

记录图片、PDF 和 Word 文档的处理脚本及其输入。具体输入可以按需要调整；脚本中的相对路径以运行时的工作目录为准。

>用 uv 的 pdf_process 环境

## func1.1 图片转 PDF

[func1.1_images_to_pdf.py](func1.1_images_to_pdf.py) 将图片合并为 PDF，并将图片中的**文字修改为可搜索、复制的 OCR 文字层**。

- 方法：使用 `PyMuPDF` 合并图片，使用 `PaddleOCR` 识别文字并添加文字层。
- 当前输入：`../data/rawdata/pdf_3/` 中的 JPG、JPEG、PNG 或 BMP 图片。

## func1.2 PDF 提取文字

[func1.2_pdf_totxt.py](func1.2_pdf_totxt.py) 提取 PDF 正文并整理段落，保存为 TXT。它可以配合图片转 PDF 脚本使用。

- 方法：使用 `PyMuPDF` 提取文字，并按版面位置和规则整理段落。
- 当前输入：`../data/processed/pdf_1.pdf` 的第 41–68 页。

## func2 拆分 PDF

[func2_split_pdf.py](func2_split_pdf.py) 将 PDF 拆成单页文件。

- 方法：使用 `PyMuPDF` 拆分 PDF。
- 输入：运行时指定的 PDF 文件。

## func3 裁剪 PDF 白边

[func3_crop_pdf_margins.py](func3_crop_pdf_margins.py) 裁剪 PDF 页面四周的白边。

- 方法：使用 `PyMuPDF` 和 `Pillow` 识别页面内容并裁剪白边。
- 当前输入：`./pdf/Fig_v2_pure.pdf`。

## func4 压缩 Word 中的图片

[func4_compress_docx_images.py](func4_compress_docx_images.py) 压缩 Word 文档中的图片，减小图片像素尺寸。

- 方法：使用标准库 `zipfile` 读取文档，使用 `Pillow` 压缩图片。
- 当前输入：`input.docx`。
