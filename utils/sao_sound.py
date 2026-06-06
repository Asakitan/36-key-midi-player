# -*- coding: utf-8 -*-
"""utils.sao_sound — 转发到本项目根部的 sao_sound 模块。

sao_auto 把音效放在 utils/ 包下; 本项目历史上是根部 sao_sound.py。
新移植的菜单代码用 `from utils.sao_sound import ...`, 这里做薄转发,
保证全工程只有一个音效系统 / 一个 pygame mixer, 不重复初始化。
"""
from sao_sound import (  # noqa: F401
    SAO_SOUNDS,
    play_sound,
    get_sao_font,
    get_cjk_font,
)

# 兼容性: 透传 sao_sound 的其余公共名 (若新代码用到更多 API)
import sao_sound as _ss  # noqa: E402
for _name in dir(_ss):
    if not _name.startswith('_') and _name not in globals():
        globals()[_name] = getattr(_ss, _name)
del _ss, _name
