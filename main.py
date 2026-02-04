from machine import Pin
import utime

# 1. Start as an INPUT with a PULL_UP. 
# This "tugs" the pin to 3.3V (OFF) without the Pico actively driving it yet.
BUZ = Pin(17, Pin.IN, Pin.PULL_UP)
utime.sleep_ms(10) 

# 2. Now switch to OUTPUT and immediately set the value to 1 (OFF).
# Because of the pull-up, the buzzer shouldn't have seen a "Low" signal.
BUZ.init(Pin.OUT, value=1)

import bootloader
bootloader.main()

