import os
import re

##################
# title：remove space
# 脚本作用是去除文件名中的空格
# 作用于脚本所在的文件夹
# 对文件和文件夹也都有效
##################


def remove_space():
    for i in os.listdir("./"):
        if i.find(" ") > 0:
            os.rename(i, re.sub(" ", "_", i))

def main():
    os.chdir(os.path.split(os.path.realpath(__file__))[0]) # 路径设置为脚本所在文件夹
    remove_space()


if __name__ == '__main__':
    main()
