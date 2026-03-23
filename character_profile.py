# -*- coding: utf-8 -*-
"""
角色识别与配置模块
基于 StarResonanceDamageCounter 项目的人物职业数据

功能:
  - 尝试从星痕共鸣游戏获取当前人物名称和职业 (需要本地服务运行)
  - 无法识别时提供用户手动输入界面
  - 保存/加载用户配置
"""

import os
import json
import ctypes
import time
import tkinter as tk
from typing import Optional, Tuple

# ═══════════════════════════════════════════════
#  职业数据 (来源: StarResonanceDamageCounter)
# ═══════════════════════════════════════════════

# 职业ID到名称映射 (来自 algo/packet.js ProfessionType)
PROFESSIONS = {
    1:  '雷影剑士',
    2:  '冰魔导师',
    3:  '涤罪恶火·战斧',
    4:  '青岚骑士',
    5:  '森语者',
    8:  '雷霆一闪·手炮',
    9:  '巨刃守护者',
    10: '暗灵祈舞·仪刀',
    11: '神射手',
    12: '神盾骑士',
    13: '灵魂乐手',
}

# 职业列表 (用于UI选择)
PROFESSION_LIST = list(PROFESSIONS.values())

# 技能到角色类型映射 (来自 algo/packet.js SKILL_TO_ROLE_MAP)
SKILL_TO_ROLE = {
    1241:    '射线',
    55302:   '协奏',
    20301:   '愈合',
    1518:    '惩戒',
    2306:    '狂音',
    120902:  '冰矛',
    1714:    '居合',
    44701:   '月刃',
    220112:  '鹰弓',
    2203622: '鹰弓',
    1700827: '狼弓',
    1419:    '空枪',
    1418:    '重装',
    2405:    '防盾',
    2406:    '光盾',
    199902:  '岩盾',
}

# 配置文件路径
_PROFILE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'player_profile.json')

# ═══════════════════════════════════════════════
#  配置管理
# ═══════════════════════════════════════════════

def load_profile() -> dict:
    """加载玩家配置 (名称 + 职业 + 等级 + 经验)"""
    try:
        if os.path.exists(_PROFILE_FILE):
            with open(_PROFILE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {
                    'username': data.get('username', ''),
                    'profession': data.get('profession', ''),
                    'level': data.get('level', 1),
                    'xp': data.get('xp', 0),
                    'songs_played': data.get('songs_played', 0),
                    'play_time': data.get('play_time', 0),
                }
    except Exception:
        pass
    return {'username': '', 'profession': '', 'level': 1, 'xp': 0,
            'songs_played': 0, 'play_time': 0}


def save_profile(username: str, profession: str, level: int = 1,
                 xp: int = 0, songs_played: int = 0, play_time: float = 0):
    """保存玩家配置"""
    # 先读取旧数据, 合并
    old = {}
    try:
        if os.path.exists(_PROFILE_FILE):
            with open(_PROFILE_FILE, 'r', encoding='utf-8') as f:
                old = json.load(f)
    except Exception:
        pass
    old.update({
        'username': username,
        'profession': profession,
        'level': level,
        'xp': xp,
        'songs_played': songs_played,
        'play_time': play_time,
    })
    try:
        with open(_PROFILE_FILE, 'w', encoding='utf-8') as f:
            json.dump(old, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ═══════════════════════════════════════════════
#  等级系统 — 弹琴积累经验, 每完成一首歌获得 XP
# ═══════════════════════════════════════════════

# 升级经验表 (level → 需要的累计 XP)
# 前10级较快升级, 后面逐渐变慢
def xp_for_level(level: int) -> int:
    """计算达到某等级需要的累计 XP"""
    if level <= 1:
        return 0
    # 每级需要: base * level^1.5
    base = 50
    total = 0
    for lv in range(2, level + 1):
        total += int(base * (lv ** 1.3))
    return total


def calc_level(xp: int) -> tuple:
    """根据 XP 计算等级和进度
    Returns: (level, current_xp_in_level, xp_needed_for_next)
    """
    level = 1
    while True:
        next_xp = xp_for_level(level + 1)
        if xp < next_xp:
            prev_xp = xp_for_level(level)
            return (level, xp - prev_xp, next_xp - prev_xp)
        level += 1
        if level > 999:
            return (999, 0, 1)


def add_song_xp(profile: dict, song_duration: float = 0) -> tuple:
    """
    完成一首歌后增加经验
    
    Args:
        profile: 当前配置 dict
        song_duration: 歌曲时长(秒)
    
    Returns:
        (new_profile, leveled_up: bool, old_level, new_level)
    """
    xp_gain = 30  # 基础完成奖励
    # 根据歌曲时长加成
    if song_duration > 30:
        xp_gain += int(song_duration / 10)  # 每10秒+1
    if song_duration > 120:
        xp_gain += 20  # 长曲加成
    
    old_xp = profile.get('xp', 0)
    old_level = profile.get('level', 1)
    
    new_xp = old_xp + xp_gain
    new_level, _, _ = calc_level(new_xp)
    
    profile['xp'] = new_xp
    profile['level'] = new_level
    profile['songs_played'] = profile.get('songs_played', 0) + 1
    profile['play_time'] = profile.get('play_time', 0) + song_duration
    
    leveled_up = new_level > old_level
    
    # 保存
    save_profile(
        profile.get('username', 'Player'),
        profile.get('profession', ''),
        new_level, new_xp,
        profile.get('songs_played', 0),
        profile.get('play_time', 0)
    )
    
    return (profile, leveled_up, old_level, new_level)


# ═══════════════════════════════════════════════
#  从游戏服务获取角色信息
# ═══════════════════════════════════════════════

def try_detect_character() -> Optional[Tuple[str, str]]:
    """
    尝试从 StarResonanceDamageCounter 本地服务获取角色信息。
    
    服务地址: http://localhost:8989/api/uid-mappings
    
    Returns:
        (username, profession) 或 None
    """
    try:
        import requests
        # 尝试从本地服务获取数据
        resp = requests.get('http://localhost:8989/api/data', timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, dict):
                # 获取第一个玩家的信息
                players = data.get('players', {})
                for uid, player_info in players.items():
                    name = player_info.get('name', '')
                    prof = player_info.get('profession', '')
                    if name:
                        return (name, prof)
        
        # 尝试从 uid-mappings 获取
        resp2 = requests.get('http://localhost:8989/api/uid-mappings', timeout=2)
        if resp2.status_code == 200:
            mappings = resp2.json()
            if mappings and isinstance(mappings, dict):
                # 返回第一个映射
                for uid, name in mappings.items():
                    if name:
                        return (name, '')
    except Exception:
        pass
    
    # 尝试从本地 uid_mapping.json 读取
    try:
        mapping_path = os.path.join('E:\\VC\\StarResonanceDamageCounter', 'uid_mapping.json')
        if os.path.exists(mapping_path):
            with open(mapping_path, 'r', encoding='utf-8') as f:
                mappings = json.load(f)
                if mappings and isinstance(mappings, dict):
                    for uid, name in mappings.items():
                        if name:
                            return (name, '')
    except Exception:
        pass
    
    return None


def get_or_ask_profile(parent_widget=None, settings=None) -> Tuple[str, str]:
    """
    获取玩家配置。优先级:
    1. 已保存的配置
    2. 游戏服务自动检测
    3. 弹出输入对话框
    
    Returns:
        (username, profession)
    """
    # 1. 检查已保存的配置
    profile = load_profile()
    if profile['username']:
        return (profile['username'], profile['profession'])
    
    # 2. 尝试自动检测
    detected = try_detect_character()
    if detected:
        name, prof = detected
        save_profile(name, prof)
        return (name, prof)
    
    # 3. 返回空, 让调用者决定是否弹出对话框
    return ('', '')


# ═══════════════════════════════════════════════
#  SAO 风格欢迎对话框 (纯 tkinter, 无 sao_theme 依赖)
# ═══════════════════════════════════════════════

class SAOWelcomeDialog:
    """
    SAO 风格角色注册对话框
    '欢迎来到艾恩格朗特！请输入你的昵称，选择你的职业'
    
    设计对标 SAO-UI 白色对话框风格:
    - 白色底 + 金色装饰
    - 标题区 + 内容区 + 按钮区三段式
    - 展开动画
    - 尺寸: 520x520 确保所有内容放得下
    """

    def __init__(self, parent, on_done=None):
        """
        parent: 父窗口 (Toplevel 或 Tk)
        on_done: 回调 callback(username, profession) — 用户确认后调用
        """
        self._parent = parent
        self._on_done = on_done
        self._result = None

        self._dlg = tk.Toplevel(parent)
        self._dlg.overrideredirect(True)
        self._dlg.attributes('-topmost', True)
        self._dlg.configure(bg='#e0e0e0')

        # Win32 圆角 + 阴影
        try:
            self._dlg.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self._dlg.winfo_id())
            val = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val), 4)
            # 系统阴影
            cls_style = ctypes.windll.user32.GetClassLongW(hwnd, -26)
            ctypes.windll.user32.SetClassLongW(hwnd, -26, cls_style | 0x00020000)
        except Exception:
            pass

        final_w, final_h = 520, 520
        initial_w = 135

        # 居中
        sx = self._dlg.winfo_screenwidth()
        sy = self._dlg.winfo_screenheight()
        px = (sx - final_w) // 2
        py = (sy - final_h) // 2

        self._final_w = final_w
        self._final_h = final_h
        self._px = px
        self._py = py

        self._dlg.geometry(f'{initial_w}x{final_h}+{px + (final_w - initial_w) // 2}+{py}')

        # ── 主容器 ──
        main = tk.Frame(self._dlg, bg='#ffffff')
        main.pack(fill=tk.BOTH, expand=True)

        # ── 标题区 (100px) ──
        header = tk.Frame(main, bg='#ffffff', height=100)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        # 金色装饰线 (top)
        tk.Frame(header, bg='#f3af12', height=3).pack(fill=tk.X)

        tk.Frame(header, height=8, bg='#ffffff').pack()

        # 标题
        self._title_lbl = tk.Label(header, text='', bg='#ffffff',
                                    fg='#646364', font=('Segoe UI', 16, 'bold'))
        self._title_lbl.pack()

        tk.Frame(header, height=4, bg='#ffffff').pack()

        self._subtitle_lbl = tk.Label(header, text='', bg='#ffffff',
                                       fg='#f3af12', font=('Microsoft YaHei UI', 11))
        self._subtitle_lbl.pack()

        tk.Frame(header, height=6, bg='#ffffff').pack()

        # 分隔线 (SAO 风格: 灰线 + 金色高光)
        sep_cv = tk.Canvas(main, height=3, bg='#ffffff', highlightthickness=0)
        sep_cv.pack(fill=tk.X, padx=30)
        sep_cv.bind('<Configure>', lambda e: self._draw_sep(sep_cv, e.width))

        # ── 内容区 ──
        content = tk.Frame(main, bg='#f5f5f5')
        content.pack(fill=tk.BOTH, expand=True)

        # 内部 padding
        inner = tk.Frame(content, bg='#f5f5f5')
        inner.pack(fill=tk.BOTH, expand=True, padx=36, pady=16)

        # 昵称输入
        tk.Label(inner, text='◇  请输入你的昵称', bg='#f5f5f5',
                 fg='#646364', font=('Microsoft YaHei UI', 11),
                 anchor='w').pack(fill=tk.X, pady=(8, 5))

        name_frame = tk.Frame(inner, bg='#d1d1d6', bd=0)
        name_frame.pack(fill=tk.X, ipady=1, pady=(0, 16))
        self._name_entry = tk.Entry(name_frame, font=('Segoe UI', 13),
                                     bg='#ffffff', fg='#333333',
                                     relief='flat', bd=0,
                                     insertbackground='#f3af12')
        self._name_entry.pack(fill=tk.X, padx=2, pady=2, ipady=8)

        # 职业选择
        tk.Label(inner, text='◇  选择你的职业', bg='#f5f5f5',
                 fg='#646364', font=('Microsoft YaHei UI', 11),
                 anchor='w').pack(fill=tk.X, pady=(4, 8))

        # 职业列表 — 3x4 grid
        prof_frame = tk.Frame(inner, bg='#f5f5f5')
        prof_frame.pack(fill=tk.X, pady=(0, 8))

        self._selected_prof = tk.StringVar(value=PROFESSION_LIST[0])
        self._prof_btns = []

        cols = 3
        for idx, prof in enumerate(PROFESSION_LIST):
            r, c = divmod(idx, cols)
            btn = tk.Radiobutton(
                prof_frame, text=prof, variable=self._selected_prof,
                value=prof, font=('Microsoft YaHei UI', 9),
                bg='#f5f5f5', fg='#646364',
                selectcolor='#fff8e8', activebackground='#fff0d0',
                activeforeground='#f3af12',
                indicatoron=False, relief='flat', bd=0,
                highlightthickness=2, highlightbackground='#d1d1d6',
                highlightcolor='#f3af12',
                padx=8, pady=6, cursor='hand2',
                command=self._on_prof_select
            )
            btn.grid(row=r, column=c, padx=3, pady=3, sticky='ew')
            self._prof_btns.append(btn)
        for c in range(cols):
            prof_frame.columnconfigure(c, weight=1)

        # 分隔线
        tk.Frame(main, bg='#e0e0e0', height=1).pack(fill=tk.X, padx=30)

        # ── 按钮区 (83px — SAO-UI Alert 标准尺寸) ──
        footer = tk.Frame(main, bg='#ffffff', height=83)
        footer.pack(fill=tk.X)
        footer.pack_propagate(False)

        btn_container = tk.Frame(footer, bg='#ffffff')
        btn_container.place(relx=0.5, rely=0.5, anchor='center')

        # OK 蓝圆 (对标 SAO-UI Alert .ok)
        ok_cv = tk.Canvas(btn_container, width=48, height=48,
                          bg='#ffffff', highlightthickness=0, cursor='hand2')
        ok_cv.pack(side=tk.LEFT, padx=28)
        ok_cv.create_oval(3, 3, 45, 45, outline='#428ce6', width=3, fill='')
        ok_cv.create_oval(10, 10, 38, 38, fill='#ffffff', outline='')
        ok_cv.create_oval(15, 15, 33, 33, fill='#428ce6', outline='')
        ok_cv.bind('<Button-1>', lambda e: self._confirm())
        ok_cv.bind('<Enter>', lambda e: ok_cv.configure(cursor='hand2'))

        # 跳过 (X) 红圆 (对标 SAO-UI Alert .close)
        skip_cv = tk.Canvas(btn_container, width=48, height=48,
                            bg='#ffffff', highlightthickness=0, cursor='hand2')
        skip_cv.pack(side=tk.LEFT, padx=28)
        skip_cv.create_oval(3, 3, 45, 45, outline='#d13d4f', width=3, fill='')
        skip_cv.create_oval(12, 12, 36, 36, fill='#d13d4f', outline='')
        skip_cv.create_line(18, 18, 30, 30, fill='#ffffff', width=2.5)
        skip_cv.create_line(18, 30, 30, 18, fill='#ffffff', width=2.5)
        skip_cv.bind('<Button-1>', lambda e: self._skip())

        # 拖拽
        self._drag = {'x': 0, 'y': 0}
        for w in [header, self._title_lbl, self._subtitle_lbl]:
            w.bind('<Button-1>', self._start_drag)
            w.bind('<B1-Motion>', self._do_drag)

        # 展开动画
        self._dlg.after(50, self._animate_expand)
        # Enter 键确认
        self._name_entry.bind('<Return>', lambda e: self._confirm())

    def _on_prof_select(self):
        """职业选中时的视觉反馈"""
        pass  # RadioButton 已自动处理

    def _draw_sep(self, canvas, w):
        """绘制 SAO 风格分隔线 (灰线 + 金色高光渐淡)"""
        canvas.delete('all')
        canvas.create_line(0, 1, w, 1, fill='#aaaaaa', width=1)
        # 金色渐淡 (从左到中间)
        half = int(w * 0.5)
        canvas.create_line(0, 0, half, 0, fill='#f3af12', width=1)
        for i in range(20):
            xp = half + i * int(w * 0.025)
            if xp >= w:
                break
            alpha = max(0, int(243 * (1 - i / 20)))
            gc = f'#{alpha:02x}{int(alpha * 0.71):02x}{int(alpha * 0.07):02x}'
            canvas.create_line(xp, 0, xp + int(w * 0.025), 0, fill=gc, width=1)

    def _animate_expand(self):
        """宽度展开动画 (135px → final_w, 500ms)"""
        t0 = time.time()
        dur = 0.5
        initial_w = 135
        fw = self._final_w
        fh = self._final_h
        px = self._px

        def _step():
            if not self._dlg.winfo_exists():
                return
            elapsed = time.time() - t0
            t = min(1.0, elapsed / dur)
            # ease-out cubic
            et = 1 - (1 - t) ** 3
            w = int(initial_w + (fw - initial_w) * et)
            x = px + (fw - w) // 2
            self._dlg.geometry(f'{w}x{fh}+{x}+{self._py}')
            if t < 1.0:
                self._dlg.after(16, _step)
            else:
                # 动画完成, 显示文字
                self._reveal_text()
        _step()

    def _reveal_text(self):
        """渐显标题文字"""
        self._title_lbl.configure(text='◇  WELCOME  ◇')
        self._subtitle_lbl.configure(text='欢迎来到 艾恩格朗特')
        self._name_entry.focus_force()

    def _confirm(self):
        name = self._name_entry.get().strip()
        if not name:
            # 闪烁输入框提示
            self._name_entry.configure(bg='#fff0f0')
            self._dlg.after(300, lambda: self._name_entry.configure(bg='#ffffff'))
            return
        prof = self._selected_prof.get()
        save_profile(name, prof)
        self._result = (name, prof)
        self._close()
        if self._on_done:
            self._on_done(name, prof)

    def _skip(self):
        """跳过 — 使用默认名称"""
        default_name = 'Player'
        default_prof = PROFESSION_LIST[0]
        save_profile(default_name, default_prof)
        self._result = (default_name, default_prof)
        self._close()
        if self._on_done:
            self._on_done(default_name, default_prof)

    def _close(self):
        try:
            self._dlg.destroy()
        except Exception:
            pass

    def _start_drag(self, e):
        self._drag['x'] = e.x_root
        self._drag['y'] = e.y_root

    def _do_drag(self, e):
        dx = e.x_root - self._drag['x']
        dy = e.y_root - self._drag['y']
        x = self._dlg.winfo_x() + dx
        y = self._dlg.winfo_y() + dy
        self._dlg.geometry(f'+{x}+{y}')
        self._drag['x'] = e.x_root
        self._drag['y'] = e.y_root


def show_welcome_dialog(parent, on_done=None):
    """
    显示 SAO 风格欢迎/角色注册对话框。
    
    Args:
        parent: 父窗口
        on_done: callback(username, profession) 用户确认后调用
    
    Returns:
        SAOWelcomeDialog 实例
    """
    return SAOWelcomeDialog(parent, on_done=on_done)
