from playwright.sync_api import sync_playwright
import pandas as pd
import time
import re

def run(playwright, trans_list: list):
    """
    进行谷歌翻译的函数
    :param playwright: playwright对象
    :param trans_list: 需要翻译的内容
    :return: 返回两个 list
    """
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    context.set_default_timeout(0)

    # Open new page
    page1 = context.new_page()
    page1.set_default_timeout(0)
    page1.set_default_navigation_timeout(0)

    page2 = context.new_page()
    page2.set_default_timeout(0)
    page2.set_default_navigation_timeout(0)
    # Go to https://translate.google.cn/?sl=en&tl=zh-CN&op=translate
    page1.goto("https://translate.google.cn/?sl=en&tl=zh-CN&op=translate")
    page2.goto("https://translate.google.cn/?sl=en&tl=zh-CN&op=translate")

    # Click [aria-label="原文"]
    # page.click("[aria-label=\"原文\"]")

    # Fill [aria-label="原文"]

    # 一个简单的并行，把需要翻译的内容分成两部分，分开在两个网页上翻译
    result1 = []
    result2 = []
    trans_num = len(trans_list)
    trans_lis_1 = trans_list[0:trans_num // 2]
    trans_lis_2 = trans_list[trans_num // 2:trans_num]

    for i,j in zip(trans_lis_1, trans_lis_2):

        # 把内容分别输入到两个网页中进行翻译，然后休息3s
        with page1.expect_navigation():
            page1.fill("[aria-label=\"原文\"]", i)
        with page2.expect_navigation():
            page2.fill("[aria-label=\"原文\"]", j)
        time.sleep(3)

        # 通过正则把内容匹配出来
        trans_res_1 = page1.inner_text("c-wiz[role=\"region\"]")
        trans_res_1 = re.findall(u"Pubmed.*\u3002", trans_res_1)
        trans_res_1 = "\n \n ".join(trans_res_1)
        result1.append(trans_res_1)

        trans_res_2 = page2.inner_text("c-wiz[role=\"region\"]")
        trans_res_2 = re.findall(u"Pubmed.*\u3002", trans_res_2)
        trans_res_2 = "\n \n ".join(trans_res_2)
        # trans_res_2 = re.findall(r"翻译结果.*这是结束", trans_res_2)
        result2.append(trans_res_2)

        # 把内容清除掉，等待浏览器反应1s，准备进行下一次翻译
        page1.click("[aria-label=\"清除原文\"]")
        page2.click("[aria-label=\"清除原文\"]")
        time.sleep(1)


    # tmp = page.inner_text("c-wiz[role=\"region\"]")
    # page.click("[aria-label=\"清除原文\"]")
    # print(tmp)

    page1.close()
    page2.close()
    # ---------------------
    context.close()
    browser.close()
    return result1, result2

if __name__ == '__main__':

    # 准备需要翻译的内容
    trans_list = pd.read_csv("./combine_analysis/step1_promoter_hypo_upregulate_gene_function.csv")
    trans_list = pd.read_csv("./combine_analysis/step1_promoter_hyper_downregulate_gene_function.csv")

    trans_list_use = trans_list["function"].copy()
    trans_list_use = [i + "\n this is end" for i in trans_list_use] # 每句后面加上一个这是结束 TODO 这里好像可以不用，以后再来测试一下

    # 开始翻译
    with sync_playwright() as playwright:
        result1, result2 = run(playwright, trans_list_use)

    # 合并保存
    result3 = result1 + result2
    trans_list["function_trans"] = result3
    trans_list.to_csv("./combine_analysis/step1_promoter_hyper_downregulate_gene_function.csv")