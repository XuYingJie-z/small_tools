# codex 会用到的小工具

### codex_tree.py

- 查询和删除 session 树。删除 session 报错时会用
    - ~/xyj/software/codex_tools/codex_tree.py   我放在这里了
    - 用法：`python3 ~/xyj/software/codex_tools/codex_tree.py 01a1caf6-30fd-7713-b842-c944eacc8afb` 

    ```python
    python3 ~/xyj/software/codex_tools/codex_tree.py 01a1caf6-30fd-7713-b842-c944eacc8afb
    01a1c09e-5e46-7532-954c-f81977daee9b  [评估 Milo 分析细胞比例差异]
    └── 01a1caf6-30fd-7713-b842-c944eacc8afb  [Milo 在 pollen 数据中的情况]  <-- TARGET
        ├── 01a1ceec-3f08-7ed0-8726-3c683f73094a  [pollen 数据中的基本情况]
        │   └── 01a1e800-f725-7461-8ce5-d4f70845bacf  [pollen 数据中的基本情况]
        ├── 01a1d040-e7f2-7e20-a69b-e35301da7225  [Clar解 KNN 邻域划分]
        └── 01a1d043-abed-7b60-8b2b-76d6ad5c68d0  [milo算法]

    ## 预览要删除的节点
    python3 ~/xyj/software/codex_tools/codex_tree.py 01a1ceec-3f08-7ed0-8726-3c683f73094a --delete-tree 
    当前树中待删除的会话（共 2 个，按执行顺序）：
    1. 01a1e800-f725-7461-8ce5-d4f70845bacf  [pollen 数据中的基本情况]
    2. 01a1ceec-3f08-7ed0-8726-3c683f73094a  [pollen 数据中的基本情况]
    本次仅预览。确认后在同一命令末尾加 --apply 执行。

    ## 执行删除节点
    python3 ~/xyj/software/codex_tools/codex_tree.py 01a1ceec-3f08-7ed0-8726-3c683f73094a --delete-tree --apply

    ```



### clean_tmp_file.py

- 查询哪些项目有 `tmp/<session ID>/` 临时目录。删除 session 后，用来清理项目里留下的临时文件
    - ~/xyj/software/codex_tools/clean_tmp_file.py   我放在这里了
    - 用法：`python3 ~/xyj/software/codex_tools/clean_tmp_file.py --list-projects ~/xyj/project`

    ```python
    python3 ~/xyj/software/codex_tools/clean_tmp_file.py --list-projects ~/xyj/project
    /dssg/home/acct-bioxsyy/bioxsyy-xyj/xyj/project/organoid_scRNAseq
    /dssg/home/acct-bioxsyy/bioxsyy-xyj/xyj/project/organoid_scRNAseq/combine_GRIN2A
    /dssg/home/acct-bioxsyy/bioxsyy-xyj/xyj/project/organoid_scRNAseq/reference_data

    ## 预览指定项目中要删除的 session 临时目录
    python3 ~/xyj/software/codex_tools/clean_tmp_file.py ~/xyj/project/organoid_scRNAseq/reference_data
    待删除 /dssg/home/acct-bioxsyy/bioxsyy-xyj/xyj/project/organoid_scRNAseq/reference_data/tmp/01a168aa-bd75-7fe0-b932-32be61d4460a
    待删除 /dssg/home/acct-bioxsyy/bioxsyy-xyj/xyj/project/organoid_scRNAseq/reference_data/tmp/01a168ac-2223-7623-8dda-b337326b71a8
    待删除 /dssg/home/acct-bioxsyy/bioxsyy-xyj/xyj/project/organoid_scRNAseq/reference_data/tmp/01a17b30-62a6-73d2-9d8c-3b1fc9064cfb
    会话目录 3 个，保留 0 个，待删除 3 个。

    ## 执行删除 session 临时目录
    python3 ~/xyj/software/codex_tools/clean_tmp_file.py ~/xyj/project/organoid_scRNAseq/reference_data --delete

    ```

