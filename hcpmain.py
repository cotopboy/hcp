
from ds18b20_reader import DS18B20Reader
from heating_valve import HeatingValve
from settings import Settings
from app_logger import AppLogger
from event_monitor import *
import time as t

appLogger = AppLogger()
hcpEvent = HcpEvent()
hcpLogger = appLogger.get_logger()
sensor_reader = DS18B20Reader(logger=hcpLogger)
heatingValve = HeatingValve(logger=hcpLogger)
settings = Settings(logger=hcpLogger)
eventMonitor = EventMonitor(hcpLogger,sensor_reader,hcpEvent)
inEventHandling = False


def hcp_evnet_handler(eventName):
    global inEventHandling
    inEventHandling = True
    if eventName == "no_concumption":
        hcpLogger.critical("no concumption, Closing Valve...")
        heatingValve.close_to(4)
    
    if eventName == "heat_up_water_tank":
        heatingValve.set_position_to_zero()
        hcpLogger.critical("Waiting for cooling down 10 minutes...")
        t.sleep(600)

    inEventHandling = False

hcpEvent.add_listener(hcp_evnet_handler)

heatingValve.turn_up()

while True:
   
    settings.load()
    temperatures = sensor_reader.get_temperatures()

    if not settings.heating_active:
        hcpLogger.info("heating control is inactive...")
        heatingValve.close_to(0)
        t.sleep(60)
        continue

    TARGET_TEMPERATURE = settings.target_temperature
    TARGET_TEMPERATURE_LOWER_LIMII = TARGET_TEMPERATURE - 2 
    TARGET_TEMPERATURE_UPPER_LIMII = TARGET_TEMPERATURE + 3

    op = ""
    reason = ""
    
    if temperatures.heatingInlet < 30:
        op = "up"
        reason = "Heating Inlet is lower 30, try to turn up"
    
    if temperatures.mainReturn < TARGET_TEMPERATURE_LOWER_LIMII :
        op = "up"
        reason = "Main Return Temperature is too low"
       
    if temperatures.mainReturn > TARGET_TEMPERATURE_UPPER_LIMII :
        op = "down"
        reason = "Main Return Temperature is too high"

    if temperatures.heatingInlet > 60:
        op = "down"
        reason = "Heating Inlet is higher than 60 , try to turn down..."

    if inEventHandling:
        hcpLogger.info("inEventHandling... wait...")
        t.sleep(10)
        continue

    if op == "up":
        hcpLogger.info(reason)
        if heatingValve.turn_up():
            t.sleep(120)
    elif op == "down":
        hcpLogger.info(reason)
        if heatingValve.turn_down():
            t.sleep(120)
    elif op == "-":
        hcpLogger.info(reason)

    t.sleep(15)
       
    

