
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

    def __init__(self,logger,t_reader:DS18B20Reader,hcp_event:HcpEvent):
        self.logger = logger
        self.t_reader = t_reader
        self.hcp_event = hcp_event
        self.thread = threading.Thread(target=self.check_temperature)
        self.thread.start()

    def check_temperature(self):
        while True:
            t = self.t_reader.get_temperatures()
            deltaMain = t.mainInlet - t.mainReturn
            if t.mainReturn > 75 and deltaMain < 3:
                self.logger.critical("no concumption detected...")
                self.hcp_event.trigger("no_concumption")

            if t.heatingInlet > 70 and t.waterInlet > 70:
                self.logger.critical("Heating up water tank detected...")
                self.hcp_event.trigger("heat_up_water_tank")

            time.sleep(15)