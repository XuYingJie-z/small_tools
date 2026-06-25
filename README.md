# small_tools

### 一些小工具
1. covert.py : 这个是一个复制pdf文字内容后消除换行符的小工具，消除后可以直接去谷歌翻译。直接点开就可以用了，自带GUI。
2. gene_func.py ：这个是从NCBI爬取基因功能的脚本，需要打开看下里面的代码，输入文件是一个csv。没写GUI。
3. google_trans.py ：是一个调用谷歌翻译的脚本，输入文件是一个csv。没写GUI。
4. remove_space.py：这是一个去除文件名中空格的小脚本
    - 用法：复制脚本到文件夹直接运行
    - 作用于脚本所在的文件夹中的所有文件
    - 对文件和文件夹也都有效
5. vedio_compress：基于 ffmpeg 的视频压缩脚本，用 tkinker 做了 GUI
6. get_interval.py ，一个用 numpy 写的区间查找的小工具
6. BCA_protein.py ： 处理 BCA 蛋白定量的代码，不是直接运行的，放在jupyter跑会更合适
6. pmid_endnote_tools.py : 从 Word XML/DOCX 文件中提取 PMID 占位符(例如[PMID: xxxxx])，并将其替换为 EndNote 引文。可以直接运行，也可以 jupyter 用法在脚本开头。
7. pdf_to_md.py：基于docling 的pdf 提取转换成 markdown，支持设置页眉页脚，适合放在 jupyter 跑，gpu 加速很重要，适合 colab，不需要很好的显卡
8. sanger_seq_phase.R : R 语言处理 sanger 一代测序鉴定基因型的问题，因为很多杂合需要拆链。可以 R 语言直接运行，也可以 jupyter，使用方法在文件内开头
