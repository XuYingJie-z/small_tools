## 给一个值，看他在不在区间里，若在，返回区间的id
import numbers
import numpy as np

# 构造数据
interval_array = np.array(
    [
        [i, j]
        for i, j in zip(np.arange(1, 100, 9), np.arange(8, 108, 9))
    ],
    np.float64
)

query = 22


def get_interval(interval_array: np.ndarray, query: numbers.Number):
    query_array = np.array([-query, -query], np.float64)
    prod_res = (interval_array + query_array).prod(axis=1)
    if prod_res.min() > 0:
        print("This query not in interval") # 不在区间之内
    else:
        res_index = prod_res.argmin()
        return interval_array[res_index]

# 测试
get_interval(interval_array, 27)
get_interval(interval_array, 19)
get_interval(interval_array, 20)




