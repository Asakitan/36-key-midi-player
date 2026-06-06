from setuptools import Extension, setup

try:
    from Cython.Build import cythonize
except ImportError as exc:
    raise SystemExit(
        "Cython is required to build optional speedups. Install Cython or "
        "run the app without the compiled extension."
    ) from exc


extensions = [
    Extension("linkstart_cy", ["linkstart_cy.pyx"]),
    # SAO 菜单加速 (从 sao_auto 移植): UI 度量/调色 + 子像素合成
    Extension("_sao_cy_uihelpers", ["_sao_cy_uihelpers.pyx"]),
    Extension("_sao_cy_pixels", ["_sao_cy_pixels.pyx"]),
]

# _sao_cy_pixels 操作 numpy 缓冲, 需要 numpy 头文件
try:
    import numpy as _np
    for _ext in extensions:
        _ext.include_dirs.append(_np.get_include())
except Exception:
    pass


setup(
    name="28midi-cython-speedups",
    ext_modules=cythonize(
        extensions,
        build_dir="build/cython",
        compiler_directives={
            "language_level": 3,
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
        },
    ),
)
