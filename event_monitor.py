
import time
import threading

from ds18b20_reader import DS18B20Reader
from temperature_mqtt_sender import TemperatureMQTTSender


class HcpEvent:
    def __init__(self):
        self.listeners = []

    def add_listener(self, listener):
        self.listeners.append(listener)

    def trigger(self, *args, **kwargs):
        for listener in self.listeners:
            listener(*args, **kwargs)

class EventMonitor:
    isInHeatUpWaterMode = False
    isInHeatingTooHot = False
    waterInletTemperatures = [100,100,100,100]
    heatingInletTemperatures = [100,100,100,100]


    def __init__(self,logger,t_reader:DS18B20Reader,hcp_event:HcpEvent, sender:TemperatureMQTTSender):
        self.logger = logger
        self.t_reader = t_reader
        self.hcp_event = hcp_event
        self.sender = sender
        self.thread = threading.Thread(target=self.check_temperature)
        self.thread.daemon = True
        self.thread.start()

    def add_temperature(self, waterIn,heatingIn):
        # Add the new temperature
        self.waterInletTemperatures.append(waterIn)

        self.heatingInletTemperatures.append(heatingIn)

        # Keep only the last 10 temperatures
        if len(self.waterInletTemperatures) > 5:
            self.waterInletTemperatures.pop(0)
            self.heatingInletTemperatures.pop(0)

    def is_water_inlet_increasing(self):
        # Check if each temperature is higher than the previous one
        for i in range(1, len(self.waterInletTemperatures)):
            if self.waterInletTemperatures[i] <= self.waterInletTemperatures[i - 1]:
                return False
            
        return True
    
    def is_water_inlet_decreasing(self):
        # Check if each temperature is lower than the previous one
        for i in range(1, len(self.waterInletTemperatures)):
            if self.waterInletTemperatures[i] >= self.waterInletTemperatures[i - 1]:
                return False
            
        return True
    
    def is_heating_inlet_increasing(self):
        # Check if each temperature is higher than the previous one
        for i in range(1, len(self.heatingInletTemperatures)):
            if self.heatingInletTemperatures[i] <= self.heatingInletTemperatures[i - 1]:
                return False
            
        return True

    def check_temperature(self):
        while True:
            t = self.t_reader.get_temperatures()
            
            self.sender.SendTemperature("mainInlet",t.mainInlet)
            self.sender.SendTemperature("mainReturn",t.mainReturn)
            self.sender.SendTemperature("waterInlet",t.waterInlet)
            self.sender.SendTemperature("heatingInlet",t.heatingInlet)
            self.sender.SendTemperature("heatingReturn",t.heatingReturn)

            self.add_temperature(t.waterInlet, t.heatingInlet)

            deltaMain = t.mainInlet - t.mainReturn
            if t.mainReturn > 65 and deltaMain < 3:
                self.logger.critical("no concumption detected...")
                self.isInHeatUpWaterMode = False
                self.hcp_event.trigger("no_concumption")

            if t.heatingInlet > 55 and self.is_heating_inlet_increasing():
                self.logger.info ("heating > 55 and keep increasing....")
                self.hcp_event.trigger("heating_getting_too_hot")

            if deltaMain > 10 and t.mainInlet > 70 and t.waterInlet > 60 and self.is_water_inlet_increasing() and not self.isInHeatUpWaterMode:
                self.logger.critical("Heating up water tank detected...")
                if not self.isInHeatUpWaterMode:
                    self.hcp_event.trigger("heat_up_water_tank")
                    self.isInHeatUpWaterMode = True

            if t.heatingInlet > 65 and self.is_heating_inlet_increasing():
                self.isInHeatUpWaterMode = False
                
                if not self.isInHeatingTooHot:
                    self.logger.critical("Heating too hot detected...")                
                    self.hcp_event.trigger("heating_too_hot")                    
                    self.isInHeatingTooHot = True

            if self.isInHeatingTooHot and t.heatingInlet < 45:
                self.logger.info("Heating too hot is cancled...")
                self.hcp_event.trigger("heating_ok")
                self.isInHeatingTooHot = False

            time.sleep(15)