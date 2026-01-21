from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

setup(
    name="opportunity_management",
    version="1.0.0",
    description="Custom Opportunity Assignment and Notification Management for ERPNext",
    author="ALKHORA",
    author_email="as@alkhora.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
