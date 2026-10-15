from setuptools import setup, find_packages

setup(
    name="human2api",
    version="0.5.0",
    description="Record browser, desktop, and Android tasks. Reuse workflows through CLI, REST, MCP, and Visual Studio.",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    package_data={"human2api": ["static/*", "examples/*.json"]},
    include_package_data=True,
    python_requires=">=3.10",
    install_requires=["cryptography>=41,<51"],
    entry_points={
        "console_scripts": [
            "h2a=human2api.cli:main",
        ],
    },
)
