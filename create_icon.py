# -*- coding: utf-8 -*-
"""
生成简单的钢琴图标
运行此脚本生成 icon.ico 文件
"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_piano_icon():
    """创建一个简单的钢琴图标"""
    sizes = [16, 32, 48, 64, 128, 256]
    images = []
    
    for size in sizes:
        # 创建图像
        img = Image.new('RGBA', (size, size), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)
        
        # 背景圆形
        margin = size // 10
        draw.ellipse(
            [margin, margin, size - margin, size - margin],
            fill=(100, 149, 237),  # 矢车菊蓝
            outline=(70, 130, 180)
        )
        
        # 绘制简化的钢琴键
        key_area_top = size // 3
        key_area_bottom = size * 2 // 3
        key_width = size // 10
        start_x = size // 4
        
        # 白键
        for i in range(5):
            x = start_x + i * key_width
            draw.rectangle(
                [x, key_area_top, x + key_width - 1, key_area_bottom],
                fill='white',
                outline='gray'
            )
        
        # 黑键
        black_positions = [0, 1, 3]  # 简化的黑键位置
        for i in black_positions:
            x = start_x + i * key_width + key_width // 2
            draw.rectangle(
                [x, key_area_top, x + key_width // 2, key_area_top + (key_area_bottom - key_area_top) // 2],
                fill='black'
            )
        
        images.append(img)
    
    # 保存为ICO
    icon_path = os.path.join(os.path.dirname(__file__), 'icon.ico')
    images[0].save(
        icon_path,
        format='ICO',
        sizes=[(s, s) for s in sizes],
        append_images=images[1:]
    )
    print(f"图标已保存: {icon_path}")
    return icon_path


def create_simple_icon():
    """创建更简单的图标（不依赖复杂绘制）"""
    from PIL import Image
    
    # 256x256 主图像
    size = 256
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 圆形背景
    draw.ellipse([10, 10, 246, 246], fill=(65, 105, 225), outline=(25, 25, 112))
    
    # 音符符号 ♪
    try:
        # 尝试使用大字体
        font = ImageFont.truetype("arial.ttf", 120)
    except:
        font = ImageFont.load_default()
    
    # 绘制音符
    draw.text((80, 50), "♪", fill='white', font=font)
    
    # 生成多个尺寸
    sizes = [16, 32, 48, 64, 128, 256]
    images = [img.resize((s, s), Image.Resampling.LANCZOS) for s in sizes]
    
    icon_path = os.path.join(os.path.dirname(__file__), 'icon.ico')
    images[0].save(
        icon_path,
        format='ICO',
        sizes=[(s, s) for s in sizes],
        append_images=images[1:]
    )
    print(f"图标已保存: {icon_path}")
    return icon_path


if __name__ == "__main__":
    try:
        create_simple_icon()
    except ImportError:
        print("需要安装 Pillow: pip install Pillow")
        print("或者手动提供 icon.ico 文件")
