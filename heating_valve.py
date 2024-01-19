import time as t
from turtle import position
import smbus
import sys
import os


DEVICE_BUS = 1
DEVICE_ADDR = 0x10
HEATING_ON_ADDR = 1
HEATING_DOWN_ADDR = 2
POWER_OFF_ADDR = 3


class HeatingValve:
    bus = smbus.SMBus(DEVICE_BUS)
    position = 0
    logger = ()

    def __init__(self,logger):
       self.logger = logger
       self.position = self.load_position()
       self.logger.info(f"Createing heatingValve object ! ⭐ Start position:{self.position}")

    def turn_up(self):

        while self.position <= 4:
            self.position = self.position + 1
            self.save_position()
            self.logger.info(f"turn up ⬆️⬆️⬆️ position:{self.position}")  
            self.bus.write_byte_data(DEVICE_ADDR, HEATING_ON_ADDR, 0xFF)
            t.sleep(1)            
            self.bus.write_byte_data(DEVICE_ADDR, HEATING_ON_ADDR, 0x00)
            t.sleep(1)
            
           
        if self.position <= 20:
            self.position = self.position + 1 
            self.save_position()
            self.logger.info(f"turn up ⬆️⬆️⬆️ position:{self.position}")        
            self.bus.write_byte_data(DEVICE_ADDR, HEATING_ON_ADDR, 0xFF)
            t.sleep(1)            
            self.bus.write_byte_data(DEVICE_ADDR, HEATING_ON_ADDR, 0x00)
            return True
        else:
            self.logger.info(f"➡️➡️➡️ Ignore turn up ⬆️⬆️⬆️ position:{self.position} > 20")        
            return False

    def set_position_to_zero(self):
        self.logger.info(f"⚠️⚠️⚠️ Reset from position:{self.position}  to 0 ⚠️⚠️⚠️")     
        self.position = 0
        self.save_position()

    def save_position(self):
        with open('./settings/position.txt', 'w') as file:
            file.write(str(self.position))
    
    def load_position(self):
        with open('./settings/position.txt', 'r') as file:
            return int(file.read())

    def close_to_zero(self):
        if self.position > 0 :
            self.logger.info(f"⚠️⚠️⚠️ Start closing position:{self.position} ⚠️⚠️⚠️")     
            while self.position > 0:
                self.position = self.position - 1
                self.save_position()
                self.bus.write_byte_data(DEVICE_ADDR, HEATING_DOWN_ADDR, 0xFF)
                t.sleep(1)
                self.bus.write_byte_data(DEVICE_ADDR, HEATING_DOWN_ADDR, 0x00)
                t.sleep(1)
            self.logger.info(f"⚠️⚠️⚠️ End closing  position:{self.position} ⚠️⚠️⚠️")  
            return True   
        else:
            self.logger.info(f"➡️➡️➡️ Ignore closing ....position:{self.position}")     
            return False

    def turn_down(self):
        if self.position > 5 :
            self.position = self.position - 1 
            self.save_position()
            self.logger.info(f"turn down ⬇️⬇️⬇️ position:{self.position}")
            self.bus.write_byte_data(DEVICE_ADDR, HEATING_DOWN_ADDR, 0xFF)
            t.sleep(1)
            self.bus.write_byte_data(DEVICE_ADDR, HEATING_DOWN_ADDR, 0x00)
            return True
        else:
            self.logger.info(f"➡️➡️➡️ Ignore turn down ⬇️⬇️⬇️ position:{self.position} <= 5")
            return False    


