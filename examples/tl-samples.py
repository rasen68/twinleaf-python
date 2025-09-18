#!/usr/bin/env python3

import twinleaf

dev = twinleaf.Device()

# columns = [] # All samples
columns = ["imu.accel*"] # Wildcard
# columns = ["imu.accel.x", "imu.accel.y", "imu.accel.z"] # Specific columns

for sample in dev._samples(n=None, columns=columns):
       print(sample)
