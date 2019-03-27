import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="archivebox",
    version="0.3.0",
    author="Nick Sweeting",
    author_email="git@nicksweeting.com",
    description="The self-hosted internet archive.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/pirate/ArchiveBox",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
