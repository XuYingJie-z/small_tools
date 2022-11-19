
# 操作 PDF 的类, 需要 pip install pymupdf
import fitz 

class PDFOperate:
    def __init__(self, file_path) -> None:
        self.doc = fitz.open("file_path")

    def pdf_split(self, from_page, to_page, output_path):
        """分割pdf，output_path：输出的新PDF保存位置"""
        doc2 = fitz.open()
        doc2.insert_pdf(self.doc, from_page = from_page, to_page = to_page, start_at = 0)
        doc2.save(output_path)
def main():
    # 测试pdf拆分功能
    pdf = PDFOperate("./tmp.pdf")
    pdf.pdf_split(3, 5, "./tmp2.pdf")

if __name__ == "__main__":
    main()


