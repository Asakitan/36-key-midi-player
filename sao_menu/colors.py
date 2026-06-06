# -*- coding: utf-8 -*-
"""SAO 配色常量 (split from sao_theme.py — verbatim)."""

# ──────────────────────── 配色 ────────────────────────
class SAOColors:
    """SAO Utils 原版配色 (来自 Vue 组件 CSS)"""
    # 遮罩 / 背景
    OVERLAY_BG = '#000000'
    OVERLAY_ALPHA = 0.70

    # 圆形按钮
    CIRCLE_BORDER = '#bcc4ca'
    CIRCLE_BG = '#f7f8f8'
    CIRCLE_ICON = '#959aa0'

    # 激活态 (金色)
    ACTIVE_BORDER = '#f3af12'
    ACTIVE_BG = '#f4ebd7'
    ACTIVE_ICON = '#6d5d40'

    # 悬停
    HOVER_BG = '#edf7fa'
    HOVER_ICON = '#718995'

    # 子菜单
    CHILD_BG = '#f8f8f8'
    CHILD_HOVER = '#f4eee1'
    CHILD_HOVER_FG = '#625846'
    CHILD_TEXT = '#646364'
    CHILD_LINE = '#bcc4ca'
    CHILD_ICON = '#8f959b'

    # 左侧信息面板
    INFO_BG = '#fbfbfb'
    INFO_BOTTOM = '#ecebea'
    INFO_TITLE_BORDER = '#c7ccd0'
    INFO_TRIANGLE = '#f4f4f4'

    # Alert 对话框
    ALERT_BG = '#ffffffe6'
    ALERT_PANEL = '#ecebeac9'
    ALERT_TITLE_FG = '#646364'
    ALERT_CONTENT_FG = '#646060'
    ALERT_SHADOW = '#00000022'
    CLOSE_RED = '#d13d4f'
    OK_BLUE = '#428ce6'

    # HP 血条
    HP_BG = '#cdddf880'
    HP_HOVER = '#e5e7ec99'
    HP_FONT_COLOR = '#e1dede'
    HP_GREEN_L = '#d3ea7c'
    HP_GREEN_R = '#9ad334'
    HP_YELLOW_L = '#ebee70'
    HP_YELLOW_R = '#f4fa49'
    HP_RED_L = '#f88c7a'
    HP_RED_R = '#ef684e'
    HP_BORDER = '#dad7d7'

    # LINK START
    LS_COLORS = ['#ff0000', '#ffff00', '#00ff00', '#0000ff',
                 '#ff00ff', '#00ffff', '#ffffff', '#ff8800']

    # 通用
    WHITE = '#ffffff'
    WHITE85 = '#ffffffd9'
    FONT_SAO = ('Segoe UI', 11)      # fallback; use _sao_font() at runtime
    FONT_ROUND = ('Microsoft YaHei UI', 10)  # fallback; use _cjk_font() at runtime

    # ── 深色应用背景 (SAO 菜单之下的播放器壳) ──
    APP_BG = '#0a0e14'
    APP_CARD = '#111820'
    APP_BORDER = '#1a3a4e'
    APP_TEXT = '#e8f4f8'
    APP_TEXT2 = '#7eb8c9'
    APP_TEXT_DIM = '#3d6070'
    APP_ACCENT = '#4de8f4'
    APP_BLUE = '#2196f3'
    APP_GREEN = '#4caf50'
    APP_RED = '#ff4444'
    APP_ORANGE = '#ff9800'
    APP_GOLD = '#ffd700'

    # ── Frosted-Glass 磨砂玻璃设计令牌 (SAO 身份面板 / HUD) ──
    SURFACE_LIGHT = (248, 248, 248)
    SURFACE_LIGHT_HEX = '#f8f8f8'
    TEXT_PRIMARY = (100, 99, 100)
    TEXT_PRIMARY_HEX = '#646364'
    TEXT_SECONDARY = (140, 135, 138)
    TEXT_SECONDARY_HEX = '#8c878a'
    ACCENT_GOLD_WARM = (212, 156, 23)     # 金色强调 (等级 / STA)
    ACCENT_GOLD_WARM_HEX = '#d49c17'
    ACCENT_CYAN_SOFT = (88, 152, 190)     # 青蓝柔和 (NErVGear / HP 值)
    ACCENT_CYAN_SOFT_HEX = '#5898be'
    CORNER_CYAN = (104, 228, 255)         # 角标 — SAO 青
    CORNER_GOLD = (212, 156, 23)          # 角标 — SAO 金


