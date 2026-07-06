import cv2

# 画像を読み込む
img = cv2.imread("../input/sample.jpg")

# 読み込めたか確認
if img is None:
    print("画像が見つかりません")
else:
    print("読み込み成功")
    print("サイズ:", img.shape)