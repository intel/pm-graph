# params = mem: standard
# output file = skynet_mem.html
#!/bin/sh

../../analyze_suspend.py -dmesg skynet_mem_dmesg.txt -ftrace skynet_mem_ftrace.txt -verbose
