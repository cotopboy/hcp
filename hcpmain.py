
from ds18b20_reader import DS18B20Reader
from heating_valve import HeatingValve
from settings import Settings
from app_logger import AppLogger
from event_monitor import *
from datetime import datetime, timedelta
import time as t

appLogger = AppLogger()
hcpEvent = HcpEvent()
hcpLogger = appLogger.get_logger()
sensor_reader = DS18B20Reader(logger=hcpLogger)
heatingValve = HeatingValve(logger=hcpLogger)
settings = Settings(logger=hcpLogger)
eventMonitor = EventMonitor(hcpLogger,sensor_reader,hcpEvent)
inEventHandling = False
inHeatupWaterTank = False
inHeatingTooHot = False
heatingTooHotTime = datetime.now() - timedelta(hours=1)
isHeatingActive = settings.heating_active


def hcp_evnet_handler(eventName):
    global inEventHandling
    global inHeatupWaterTank
    global heatingTooHotTime
    global inHeatingTooHot

    inEventHandling = True
    if eventName == "no_concumption":
        hcpLogger.critical("no concumption, Closing Valve...")
        inHeatupWaterTank = False
        heatingValve.close_to(0)

    if eventName == "heating_getting_too_hot":
        heatingValve.turn_down()

    if eventName == "heating_too_hot":        
        inHeatingTooHot = True
        heatingValve.close_to(0)
        inHeatupWaterTank = False


    if eventName == "heating_ok":
        inHeatingTooHot = False
    
    if eventName == "heat_up_water_tank":
        inHeatupWaterTank = True
        heatingValve.set_position_to(102)
    

    inEventHandling = False

hcpEvent.add_listener(hcp_evnet_handler)

if isHeatingActive:
    heatingValve.turn_up_to_ready_position()

while True:
   
    settings.load()
    temperatures = sensor_reader.get_temperatures()

    if inHeatingTooHot:
        hcpLogger.info("waiting...heating too hot...")
        t.sleep(10)
        continue

    if inHeatupWaterTank:
        hcpLogger.info("heating up water.....")
        t.sleep(10)
        continue

    if inEventHandling:
        hcpLogger.info("inEventHandling... wait...")
        t.sleep(10)
        continue

    if not settings.heating_active:
        hcpLogger.info(f"heating control is inactive...position:{heatingValve.position}")    
        if isHeatingActive:
            heatingValve.close_to_end()
            isHeatingActive = False
        t.sleep(60)
        continue
    else:
        isHeatingActive = True

    TARGET_TEMPERATURE = settings.target_temperature
    TARGET_TEMPERATURE_LOWER_LIMII = TARGET_TEMPERATURE  
    TARGET_TEMPERATURE_UPPER_LIMII = TARGET_TEMPERATURE + 10

    op = ""
    reason = ""
    
    if temperatures.heatingInlet < 30:
        op = "up"
        reason = "Heating Inlet is lower 30, try to turn up"

    if (temperatures.heatingInlet + temperatures.mainReturn) < 70:
        op = "up"
        reason = "Heating inlet + main.return is too low.., try to turn up."
    
    if temperatures.mainReturn < TARGET_TEMPERATURE_LOWER_LIMII :
        op = "up"
        reason = "Main Return Temperature is too low"

    if (temperatures.heatingInlet + temperatures.mainReturn) >= 95:
        op = "down"
        reason = "Heating inlet + main.return is too high.., try to turn down..."   
    
    if temperatures.mainReturn > TARGET_TEMPERATURE_UPPER_LIMII :
        op = "down"
        reason = "Main Return Temperature is too high"

    if op == "up":
        hcpLogger.info(reason)
        if heatingValve.turn_up():
            t.sleep(60)
    elif op == "down":
        hcpLogger.info(reason)
        if heatingValve.turn_down():
            t.sleep(30)
    elif op == "-":
        hcpLogger.info(reason)

    t.sleep(15)
       
    

