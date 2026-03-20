# -*- coding: utf-8 -*-
"""分析移调效果"""

# 众神眷恋的超范围音符
out_notes = [33, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 94, 97, 99, 103]
transpose = 2

print('移调+2后:')
for n in out_notes:
    adj = n + transpose
    in_range = 36 <= adj <= 83
    status = "在范围" if in_range else "超出"
    print(f'  MIDI {n} + 2 = {adj}, {status}')

print('\n分析: 移调+2后，MIDI 33变成35(仍然低于36)，82-103都超过83')
print('需要的重映射数量: 15个')

# 尝试不同移调值
print('\n尝试其他移调值:')
for t in [-12, -6, 0, 6, 12]:
    out_count = sum(1 for n in out_notes if not (36 <= n + t <= 83))
    print(f'  移调{t:+d}: {out_count}个超出范围')
