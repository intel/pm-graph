from distutils.core import setup

setup(name = 'analyze_suspend',
	version = '4.6',
	description = 'Tool for analyzing suspend/resume timing',
	scripts = ['analyze_suspend.py', 'analyze_boot.py'],
	packages = ['analyze_suspend'],
	package_dir = {'analyze_suspend': '.'},
	package_data = {'analyze_suspend': ['config/*.cfg']},
)
