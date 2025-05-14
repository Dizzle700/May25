from setuptools import setup, find_packages

with open("yolo_dataset_creator/requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="yolo-dataset-creator",
    version="0.1.0",
    packages=find_packages(),
    install_requires=requirements,
    entry_points={
        'console_scripts': [
            'yolo-dataset-creator=yolo_dataset_creator.main:main',
        ],
    },
) 