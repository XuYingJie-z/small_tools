import os
import zlib
import threading
from PIL import Image
import tkinter as tk
import threading
import tkinter.messagebox  # 引入弹窗库，防止解释器弹出报错。
import ffmpeg
import windnd



class CompressApp:
    def __init__(self, window):
        self.window = window
        self.frame = tk.Frame(window)
        self.frame.grid()
        # 下面就是一系列组件，核心就是 essential_entry 和后面的两个 button
        self.tk_label(row=0,text='  输入以下信息，可以为空， 一般码率为3500，帧率为30')
        self.tk_label(row=1)  # 分割一下
        self.essential_entry(row=2)
        self.tk_label(row=3)  # 分割一下
        self.clear_button(row=4)
        self.run_button(row=4)
        # 拖拽文件识别路径,可以多个文件一起拖入
        windnd.hook_dropfiles(self.window, func=self.get_dragged_files)


    def essential_entry(self, row):
        # 几种信息
        label_coderate = tk.Label(self.frame, text='码率', font=("微软雅黑", 12), width=5).grid(row=row, column=0)
        self.entry_coderate = tk.Entry(self.frame, show=None, width=5)
        self.entry_coderate.grid(row=row, column=1)

        label_frame = tk.Label(self.frame, text='帧数', font=("微软雅黑", 12), width=5).grid(row=row, column=2)
        self.entry_frame = tk.Entry(self.frame, show=None, width=5)
        self.entry_frame.grid(row=row, column=3)

        label_process = tk.Label(self.frame, text='线程', font=("微软雅黑", 12),width=5).grid(row=row, column=4)
        self.entry_process = tk.Entry(self.frame, show=None, width=5)
        self.entry_process.grid(row=row, column=5)

    def run_button(self, row):
        # 运行按钮
        self.run_button = tk.Button(self.frame, text='开始运行', font=("微软雅黑", 12), command=self.compress, width=8,height=2)
        self.run_button.grid(row=row, column=1, columnspan=3)

    def clear_button(self, row):
        # 清空按钮，把 file_path 清空
        self.clear_button = tk.Button(self.frame, text='clear', font=("微软雅黑", 12), command=self.clear_button_func, width=8,height=2)
        self.clear_button.grid(row=row, column=3, columnspan=3)

    def tk_label(self, row, text="--------------------"):
        seprate_line = tk.Label(self.frame, text=text, font=("微软雅黑", 14), height=2).grid(row=row, column=0, columnspan=6)


    def get_dragged_files(self, files):
        # 拖入文件获取路径
        msg = [item.decode('gbk') for item in files]    # windows 是 gbk 编码
        self.filePath = msg

    def clear_button_func(self):
        self.filePath = None

    def compress(self):
        for file in self.filePath:
            compress = CompressVideo(file, self.window, self.compress_param, self.compress_multiprocess)
            compress.single_compress(self.window)

    @property
    def compress_param(self):
        # 返回压缩参数,第一个码率单位一般是 kbps，所以这里直接扩大1000倍
        coderate = self.entry_coderate.get() + "000"
        frame = self.entry_frame.get()
        return (coderate, frame)

    @property
    def compress_multiprocess(self):
        # 返回多线程参数
        multi_process = self.entry_process.get()
        return multi_process

    @staticmethod
    def display_complete():
        tk.messagebox.showinfo(title='display_messagebox', message='压缩完成')

    @staticmethod
    def display_message(window, error_info):
        # 参数是 window 的窗口主体
        text = tk.Label(window, height=3, text=error_info, font=("微软雅黑", 13))
        text.grid(row=1,column=0,columnspan=5)



class CompressVideo:
    # 输出路径统一和输入路径一样
    # 输出文件名：在输入文件名后面加 _compress
    def __init__(self, filePath, window, compress_param, multiprocess):
        # window 是 window 的窗口主体
        self.filePath = filePath  # 文件或文件夹地址
        self.compress_param = compress_param # 压缩参数，元组类型,第一个是码率，2是帧率
        self.multiprocess = multiprocess # 调用线程数
        # 检查 ffmpeg 是否安装了
        self.check_ffmpeg(window)

    def single_compress(self, window):
        # 压缩一个文件,检查下是否是视频，window 是tk 窗口本体
        if self.check_is_video() is not True:
            # 不是视频就显示下错误，然后退出
            CompressApp.display_message(window, "不是视频文件")
            return False

        CompressApp.display_message(window, f"准备压缩 {self.filePath}") # 开始压缩
        """核心命令在这里"""
        compress_command = f"ffmpeg -i {self.filePath}  -c:v libx264 "
        # 1. 加上帧数和码率的参数
        compress_param_prifix = (" -b:v ", " -r ")
        vedio_info = self.get_video_info()
        for i, j in enumerate(zip(self.compress_param, vedio_info)):
            # GUI 的输入不为空，且输入的帧数比原视频帧数小，才采用输入的帧数
            if  j[0] != "":
                if int(j[0]) < int(j[1]):
                    compress_command = compress_command + compress_param_prifix[i] + str(j[0])
        # 2. 加上线程数
        if self.multiprocess != "":
            compress_command += f" -threads {str(self.multiprocess)} "

        # 3. 加上输出文件名
        compress_command += self.get_output_filename()
        print(compress_command) # 最后检查
        os.system(compress_command)

        CompressApp.display_message(window, f"压缩完成 {self.filePath}")  # 开始压缩


    def check_ffmpeg(self, window):
        # 检查 ffmpeg 是否安装了
        if os.system("ffmpeg -h") != 0:
            CompressApp.display_message(window, "没有安装ffmpeg")
            raise  ValueError("没有安装ffmpeg")

    def check_is_video(self):
        videoSuffixSet = {"WMV", "ASF", "ASX", "RM", "RMVB", "MP4", "3GP", "MOV", "M4V", "AVI", "DAT", "MKV", "FIV",
                          "VOB"}
        suffix = self.filePath.rsplit(".", 1)[-1].upper()
        if suffix in videoSuffixSet:
            return True
        else:
            return False


    def get_video_info(self):
        # 获取视频的码率和帧率，目的是如果输入的压缩帧率比原视频还大，那就用原视频的帧率
        probe = ffmpeg.probe(self.filePath)

        # 获取码率和帧率，帧率是一个分数，所以看起来麻烦一点
        kbps = int(probe['format']['bit_rate'])
        frame_number = \
            int(int(probe['streams'][0]['r_frame_rate'].split('/')[0]) /
                int(probe['streams'][0]['r_frame_rate'].split('/')[1]))
        return (kbps, frame_number)

    def get_output_filename(self):
        # 输出就是输入加上 compress
        output = self.filePath.rsplit(".")
        output[-2] = output[-2] + "_compress" # -1 是文件后缀
        return ".".join(output)


def main():
    threading.Thread(target=gui_thread).start()


def gui_thread():
    window = tk.Tk()
    window.geometry('600x300')  # 窗口大小
    compress_app = CompressApp(window)
    window.mainloop()


if __name__ == '__main__':
    main()

