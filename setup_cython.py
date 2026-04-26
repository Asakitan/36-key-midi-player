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
]


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
