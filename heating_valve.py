import time as t
import smbus
import sys


DEVICE_BUS = 1
DEVICE_ADDR = 0x10
HEATING_ON_ADDR = 1
HEATING_DOWN_ADDR = 2




class HeatingValve:
    bus = smbus.SMBus(DEVICE_BUS)
    logger = ()

    def __init__(self,logger):
       self.logger = logger
       self.logger.info(f"Createing heatingValve object")

    def turn_up(self):
        self.logger.info(f"turn up ⬆️⬆️⬆️")
        self.bus.write_byte_data(DEVICE_ADDR, HEATING_ON_ADDR, 0xFF)
        t.sleep(1)
        self.bus.write_byte_data(DEVICE_ADDR, HEATING_ON_ADDR, 0x00)

    def turn_down(self):
        self.logger.info(f"turn down ⬇️⬇️⬇️")
        self.bus.write_byte_data(DEVICE_ADDR, HEATING_DOWN_ADDR, 0xFF)
        t.sleep(1)
        self.bus.write_byte_data(DEVICE_ADDR, HEATING_DOWN_ADDR, 0x00)

