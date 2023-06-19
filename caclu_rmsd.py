# from pymol import cmd
# 使用 Pool 进行多进程计算的一个脚本
import os
import pandas as pd
import numpy as np
from multiprocessing import Pool



def load_pdb(file_path):
    
    # 加载pdb
    os.chdir(file_path)
    file_list = os.listdir(file_path)
    for i in file_list:
        cmd.load(i)
    
    # 创建 dataframe
    df = pd.DataFrame(
        np.zeros((len(file_list), len(file_list))), 
        columns=  [i.split(".")[0] for i in file_list], 
        index= [i.split(".")[0] for i in file_list]
    )
    return df

def melt_df(df: pd.core.frame.DataFrame):
    res = df.assign(index=df.index).copy()
    # 1. 把index变成一列  2. 宽边长  3. 把行名和列名拼成一个 list，然后去重
    res = pd.melt(res, id_vars=["index"], var_name='column', value_name='myValname')
    res = res.assign(detect_dup=res.apply(lambda x: sorted([str(x[0]), str(x[1])]) ,axis=1))
    res.drop_duplicates(subset=["detect_dup"], inplace=True)
    res.drop(columns=["detect_dup"], inplace=True)

    return res


def calcu_xxx(df: pd.core.frame.DataFrame):
    # TODO 名字改一下
    # 输入的是 melt_df 的结果
    def calculate(x:pd.core.series):
        if x["index"] == x["column"]:  # 这个名字是 melt_df 中指定的
            return 1
        else:
            return cmd.align(x["index"], x["column"])[0]  # !!!调用 pymol 的计算结果
    res = df.copy()
    res["value"] = res.apply(calculate, axis=1)  # 这里不知道会不会报错
    return res

def multi_calcu(df: pd.core.frame.DataFrame, num_process: int, num_parts: int):
    # num_process: 进程数
    # num_parts： 把dataframe 分成多少块，每个进程处理一块
    df_parts = np.array_split(df, num_parts)
    res_list = []
    with Pool(processes=num_process) as pool:
        for i in df_parts:
            one_task = pool.apply_async(calcu_xxx, (i, )) 
            res_list.append(one_task.get(timeout=5000))  # TODO timeout 可能要设置一下
        res = pd.concat(res_list)  #
        return res.pivot(index='index', columns='column', values="value").T 
    

def main():
    ## 正式
    file_path = "C:/Users/LJR/Desktop/jieduan"
    filelist_df = load_pdb(file_path)
    filelist_melt = melt_df(filelist_df)
    res = multi_calcu(filelist_melt, 5, 5)
    res.to_csv("C:/Users/LJR/Desktop/jieduan/1.csv")

    ## 测试
    # file_list = range(10)
    # filelist_df = res = pd.DataFrame(
    # np.zeros((len(file_list), len(file_list))), 
    # columns=  [i for i in file_list], 
    # index= [i for i in file_list]
    # )
    # filelist_melt = melt_df(filelist_df)
    # print(filelist_melt)





if __name__ == "__main__":
    main()
    



