#!/bin/python3.6

"""
一个小工具，可以从wps中复制文献内容，然后直接去google翻译
"""


import tkinter as tk

window = tk.Tk()  # 创建GUI
window.title('my window')
window.geometry('600x230')

# 这里是窗口的内容

var = tk.StringVar()  # 这时文字变量储存器


def convert():
    var = window.clipboard_get()  # 获取剪贴板内容
    clip = str(var).replace('\n', ' ').replace('', '')
    window.clipboard_clear()  # 清除剪贴板内容
    window.clipboard_append(clip)  # 向剪贴板追加内容


show_lable = tk.Label(window,
             text='先把文献内容复制到剪切板（使用wps），\n 然后点击convert，之后就可以直接去谷歌翻译了',  # 使用 textvariable 替换 text, 因为这个可以变化
             bg='white', font=('Microsoft Yahei', 16), width=90, height=5)
show_lable.pack()

b = tk.Button(window,
              text='convert',  # 显示在按钮上的文字
              width=15, height=2,
              command=convert)  # 点击按钮式执行的命令
b.pack()  # 按钮位置

window.mainloop()
