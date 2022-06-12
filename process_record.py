
import pyautogui

def change_word_format():
    # word里面改变字符的格式，坐标是写死的
    pyautogui.click(1259, 983,button='left') 
    pyautogui.click(328, 99,button='left') 
    pyautogui.click(339, 220,button='left') 




if __name__ == "__main__":
    for i in range(1,10):
        change_word_format()
        print("complete")

