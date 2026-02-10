from pathlib import Path

from setuptools import find_packages, setup


setup(
    name="taxgrok",
    version="0.1.1",
    description="Local CLI tax-prep briefing tool powered by xAI + RAG",
    long_description=Path("README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="taxgrok",
    author_email="maintainers@taxgrok.dev",
    url="https://github.com/taxgrok/taxgrok",
    license="MIT",
    python_requires=">=3.9",
    packages=find_packages(exclude=("tests", "tests.*")),
    include_package_data=True,
    install_requires=["pypdf>=4.0.0"],
    entry_points={"console_scripts": ["taxgrok=taxgrok.cli:main"]},
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Environment :: Console",
    ],
)
