# /python3

import requests
from lxml import etree
import pandas as pd
import os
import time
from functools import wraps


def try_list_index(process_list, index):
    try:
        return process_list[index]
    except IndexError:
        return 'error'


def connect_error(function):
    # TODO：这个装饰器没有测试，不知道行不行
    @wraps(function)
    def try_function(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ConnectionError:
            # 主要就是为了处理这个 ConnectionError
            time.sleep(10)
            return function(*args, **kwargs)
    return try_function


@connect_error
def get_gene_id(session, gene_name: str, headers: dict, organism="Homo sapiens", sleep_time: int = 2):
    """
    获取 gene id 的函数，有时候可能获取不到

    :param headers: request的请求头
    :param sleep_time: 暂停时间,默认暂停2s
    :param session: request session, 这样是保证持续连接
    i.e: request_session = requests.Session()
    get_gene_id(request_session)
    :param gene_name: 需要获取的基因名 string
    :param organism: 必须是Homo sapiens这种NCBI使用的物种名称. 默认是人 string
    :return: 基因名对应的基因ID
    """

    # 获取页面信息
    url = 'https://www.ncbi.nlm.nih.gov/gene/?term=' + gene_name
    page_text = session.get(url=url, headers=headers)
    tree = etree.HTML(page_text.content)
    organism_list = tree.xpath('//tr[@class="rprt"]//td/em/text()')

    # 获取所有物种名和gene id名，数量是一致的
    gene_id_list = tree.xpath('//tr[@class="rprt"]//span[@class="gene-id"]/text()')
    gene_id_list = [i.replace("ID: ", "") for i in gene_id_list]

    # 物种名和id名合并起来，取出想要的物种
    gene_id_dic = dict(zip(organism_list, gene_id_list))
    gene_id = gene_id_dic.get(organism)

    time.sleep(sleep_time)  # 爬取之后要暂停几秒
    return gene_id


@connect_error
def get_gene_function(session, gene_name, gene_id, headers: dict, sleep_time: int = 2):
    """
    获取基因功能的函数
    :param headers: request的请求头
    :param sleep_time: 暂停时间,默认暂停2s
    :param session: request session, 这样是保证持续连接
    :param gene_name:基因名
    :param gene_id: ncbi 的 gene ID
    :return:
    """
    # 1.request 的部分
    url = "https://www.ncbi.nlm.nih.gov/gene/" + gene_id
    page_text = session.get(url=url, headers=headers)
    tree = etree.HTML(page_text.content)

    # 2.这里是gene功能
    organism_text = tree.xpath('//dl[@id="summaryDl"]/dd[@class="tax"]/a/text()')
    express_text = tree.xpath('//dl[@id="summaryDl"]/dd/a[@href="#gene-expression"]/../text()')
    summary_text = tree.xpath('//dl[@id="summaryDl"]/dd[10]/text()')

    # 3.这里是一部分，就是基因功能及对应的文章id
    func_text = tree.xpath('//ol[@class="generef-link"]/li/a/text()')
    ref_pubmed_id = tree.xpath('//ol[@class="generef-link"]/li/a/@href')

    func_summary = [
        " : ".join(i)
        for i in zip(ref_pubmed_id, func_text)
    ]

    func_summary = " \n \n".join(func_summary)  # 最后合并成一个字符串

    # 4.创建dataframe，列表必须写成[[]],里面的一个括号就是一行，这个就是一行内容
    pd_data = [[
        gene_name, gene_id, try_list_index(organism_text, 0),
        try_list_index(express_text, 0), try_list_index(summary_text, 0),
        func_summary
    ]]

    gene_data = pd.DataFrame(
        pd_data,
        columns=["gene_name", "gene_id", "organism", "express", "summary", "function"]
    )

    time.sleep(sleep_time)  # 爬取之后要暂停几秒
    return gene_data


def batch_gene_func(request_session, gene_list: list, headers: dict, organism="Homo sapiens"):
    """
    批量获取
    :param request_session:  request模块的 session 保证稳定连接
    :param gene_list: gene列表
    :param headers: 浏览器头
    :param organism: 必须是Homo sapiens这种NCBI使用的物种名称. 默认是人
    :return:
    """
    gene_dunc_dataframe = pd.DataFrame()  # 结果
    false_gene = []
    for gene in gene_list:
        gene_id = get_gene_id(request_session, gene, headers=headers, organism=organism)
        if gene_id is None:
            false_gene.append(gene)
            continue
        gene_func_data = get_gene_function(request_session, gene, gene_id, headers=headers)
        gene_dunc_dataframe = gene_dunc_dataframe.append(gene_func_data)
    gene_dunc_dataframe.append(false_gene) # 这句没测试过，不知道会不会报错
    return gene_dunc_dataframe


if __name__ == "__main__":
    session = requests.Session()  # session
    firefox_head = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:95.0) Gecko/20100101 Firefox/95.0'
    }

    gene_data = pd.read_csv("./combine_analysis/step1_promoter_hyper_downregulate_gene.csv")
    gene_list = gene_data["SYMBOL"]  # 需要查询的gene
    # gene_dunc_dataframe.to_csv(os.getcwd() + "\\" + "tmp.csv")

    result = batch_gene_func(session, list(set(gene_list) - set(result1["gene_name"])), headers=firefox_head, organism="Homo sapiens")
    result1 = result1.append(result)

    result1.to_csv("./combine_analysis/step1_promoter_hyper_downregulate_gene_function.csv")

# !!!!ConnectionError!!!!

