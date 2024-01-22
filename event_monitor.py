
import time
import threading

from ds18b20_reader import DS18B20Reader


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
    waterInletTemperatures = [100,100,100,100]


    def __init__(self,logger,t_reader:DS18B20Reader,hcp_event:HcpEvent):
        self.logger = logger
        self.t_reader = t_reader
        self.hcp_event = hcp_event
        self.thread = threading.Thread(target=self.check_temperature)
        self.thread.start()

    def add_temperature(self, new_temp):
        # Add the new temperature
        self.waterInletTemperatures.append(new_temp)

        # Keep only the last 10 temperatures
        if len(self.waterInletTemperatures) > 5:
            self.waterInletTemperatures.pop(0)

    def is_water_inlet_increasing(self):
        # Check if each temperature is higher than the previous one
        for i in range(1, len(self.waterInletTemperatures)):
            if self.waterInletTemperatures[i] <= self.waterInletTemperatures[i - 1]:
                return False
            
        return True

    def check_temperature(self):
        while True:
            t = self.t_reader.get_temperatures()
            self.add_temperature(t.waterInlet)

            deltaMain = t.mainInlet - t.mainReturn
            if t.mainReturn > 75 and deltaMain < 3:
                self.logger.critical("no concumption detected...")
                self.isInHeatUpWaterMode = False
                self.hcp_event.trigger("no_concumption")


            if deltaMain > 10 and t.mainInlet > 80 and t.waterInlet > 70 and self.is_water_inlet_increasing() and not self.isInHeatUpWaterMode:
                self.logger.critical("Heating up water tank detected...")
                if not self.isInHeatUpWaterMode:
                    self.hcp_event.trigger("heat_up_water_tank")
                    self.isInHeatUpWaterMode = True

            if t.heatingInlet >70:
                self.logger.critical("Heating too hot detected...")                
                self.hcp_event.trigger("heating_too_hot")
                self.isInHeatUpWaterMode = False

            time.sleep(15)