# params = disk: standard
# output file = skynet_disk.html
#!/bin/sh

../../sleepgraph.py -dmesg skynet_disk_dmesg.txt -ftrace skynet_disk_ftrace.txt -verbose
