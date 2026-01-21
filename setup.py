from setuptools import setup, find_packages

setup(
    name="opportunity_management",
    version="1.0.0",
    description="Custom Opportunity Assignment and Notification Management for ERPNext",
    author="Your Company",
    author_email="your@email.com",
    packages=find_packages(exclude=["tests", "tests.*"]),
    include_package_data=True,
    zip_safe=False,
    install_requires=[],
)
