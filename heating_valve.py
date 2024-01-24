import time as t
from turtle import position
import smbus
import sys
import os
import threading


DEVICE_BUS = 1
DEVICE_ADDR = 0x10
HEATING_ON_ADDR = 1
HEATING_DOWN_ADDR = 2
POWER_OFF_ADDR = 3


class HeatingValve:
    bus = smbus.SMBus(DEVICE_BUS)
    position = 0
    logger = ()
    lock = threading.Lock()

    def __init__(self,logger):
       self.logger = logger
       self.position = self.load_position()
       self.logger.info(f"Createing heatingValve object ! ⭐ Start position:{self.position}")

    def turn_up_to_ready_position(self):
        with self.lock:
            while self.position <= 8:
                self.position = self.position + 1
                self.save_position()
                self.logger.info(f"turn up ⬆️⬆️⬆️ position:{self.position}")  
                self.bus.write_byte_data(DEVICE_ADDR, HEATING_ON_ADDR, 0xFF)
                t.sleep(0.5)            
            
            self.bus.write_byte_data(DEVICE_ADDR, HEATING_ON_ADDR, 0x00)


    def turn_up(self):
        with self.lock:
            while self.position <= 8:
                self.position = self.position + 1
                self.save_position()
                self.logger.info(f"turn up ⬆️⬆️⬆️ position:{self.position}")  
                self.bus.write_byte_data(DEVICE_ADDR, HEATING_ON_ADDR, 0xFF)
                t.sleep(0.5)            
            
            self.bus.write_byte_data(DEVICE_ADDR, HEATING_ON_ADDR, 0x00)
                            
            if self.position <= 40:
                self.position = self.position + 1 
                self.save_position()
                self.logger.info(f"turn up ⬆️⬆️⬆️ position:{self.position}")        
                self.bus.write_byte_data(DEVICE_ADDR, HEATING_ON_ADDR, 0xFF)
                t.sleep(0.5)            
                self.bus.write_byte_data(DEVICE_ADDR, HEATING_ON_ADDR, 0x00)
                return True
            else:
                self.logger.info(f"➡️➡️➡️ Ignore turn up ⬆️⬆️⬆️ position:{self.position}")        
                return False

    def set_position_to(self, new_position):
        with self.lock:
            self.logger.info(f"⚠️⚠️⚠️ Reset from position:{self.position} to {new_position} ⚠️⚠️⚠️")     
            self.position = new_position
            self.save_position()

    def save_position(self):
        with open('./settings/position.txt', 'w') as file:
            file.write(str(self.position))
    
    def load_position(self):
        with open('./settings/position.txt', 'r') as file:
            return int(file.read())
            
    def close_to(self, target_position):
        with self.lock:
            if self.position > target_position :
                self.logger.info(f"⚠️⚠️⚠️ Start closing position:from {self.position} to {target_position} ⚠️⚠️⚠️")     
                while self.position > target_position:
                    self.position = self.position - 1
                    self.save_position()
                    self.logger.info(f"Current Position: {self.position}") 
                    self.bus.write_byte_data(DEVICE_ADDR, HEATING_DOWN_ADDR, 0xFF)
                    t.sleep(0.5)
                self.bus.write_byte_data(DEVICE_ADDR, HEATING_DOWN_ADDR, 0x00)
                self.logger.info(f"⚠️⚠️⚠️ End closing position:{self.position} ⚠️⚠️⚠️")  
                return True   
            else:
                self.logger.info(f"➡️➡️➡️ Ignore closing ....position:{self.position}")     
                return False

    def turn_down(self):
        with self.lock:
            if self.position > 10 :
                self.position = self.position - 1 
                self.save_position()
                self.logger.info(f"turn down ⬇️⬇️⬇️ position:{self.position}")
                self.bus.write_byte_data(DEVICE_ADDR, HEATING_DOWN_ADDR, 0xFF)
                t.sleep(0.5)
                self.bus.write_byte_data(DEVICE_ADDR, HEATING_DOWN_ADDR, 0x00)
                return True
            else:
                self.logger.info(f"➡️➡️➡️ Ignore turn down ⬇️⬇️⬇️ position:{self.position}")
                return False    


