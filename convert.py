import tkinter as tk

from tkinter.constants import LEFT, RIGHT, YES

window = tk.Tk()  # 创建GUI
window.title('my window')
window.geometry('270x100')

# 这里是窗口的内容

var = tk.StringVar()  # 这时文字变量储存器


def convert():
    var = window.clipboard_get()  # 获取剪贴板内容
    clip = str(var).replace(".\n", ".\r \r").replace('\n', ' ').replace('', '').replace("  ", " ")
    window.clipboard_clear()  # 清除剪贴板内容
    window.clipboard_append(clip)  # 向剪贴板追加内容


# 使用说明
label_expression = tk.Label(
    window,
    text='先把文献内容复制到剪切板（使用wps），\n 然后点击convert，之后就可以直接去谷歌翻译了',  # 使用 textvariable 替换 text, 因为这个可以变化
    bg='white',
    font=('Microsoft Yahei', 9),
    width=80, height=2
)

label_expression.pack()  # 依次往下排列

# 窗口置顶功能
chek_topwindow = tk.BooleanVar()


def top_window():
    if chek_topwindow.get():
        window.wm_attributes('-topmost', 1)  # 置顶
    else:
        window.wm_attributes('-topmost', 0)  # 取消置顶


topwindow_button = tk.Checkbutton(
    window,
    text="窗口置顶",
    font=('Microsoft Yahei', 12),
    variable=chek_topwindow,
    onvalue=True,
    offvalue=False,
    command=top_window
)

topwindow_button.pack(side=LEFT, expand=YES)

# 翻译按钮
b = tk.Button(window,
              text='convert',  # 显示在按钮上的文字
              width=15, height=2,
              command=convert)  # 点击按钮式执行的命令
b.pack(side=RIGHT, expand=YES)  # 按钮位置

window.mainloop()
