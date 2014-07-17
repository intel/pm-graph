# params = freeze: standard
# output file = skynet_freeze.html
#!/bin/sh

../../analyze_suspend.py -dmesg skynet_freeze_dmesg.txt -ftrace skynet_freeze_ftrace.txt -verbose
