
from ds18b20_reader import DS18B20Reader
from heating_valve import HeatingValve
from settings import Settings
from app_logger import AppLogger
import time as t

sensor_reader = DS18B20Reader()
appLogger = AppLogger()
hcpLogger = appLogger.get_logger()
heatingValve = HeatingValve(logger=hcpLogger)
settings = Settings(logger=hcpLogger)

op = ""
reason = ""

while True:
    settings.load()
    temperatures = sensor_reader.get_temperatures()
    hcpLogger.info(f"MIn: {temperatures.mainInlet:.1f} MRe: {temperatures.mainReturn:.1f} HIn: {temperatures.heatingInlet:.1f} HRe: {temperatures.heatingReturn:.1f} Room:{temperatures.waterInlet:.1f}")


    if not settings.heating_active:
        hcpLogger.info("heating control is inactive...")
        heatingValve.close_to_zero()
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

    if temperatures.heatingInlet > 50:
        op = "-"
        reason = "Heating Inlet is higher than 50 , do nothing"

    if temperatures.heatingInlet > 60:
        op = "down"
        reason = "Heating Inlet is higher than 60 , try to turn down..."

    deltaMain = temperatures.mainInlet - temperatures.mainReturn
    if temperatures.mainReturn > 75 and deltaMain < 4:
        op = "-"
        hcpLogger.critical("no concumption, Closing Valve...")
        heatingValve.close_to_zero()

    if temperatures.heatingInlet > 70 and temperatures.waterInlet > 70:
        heatingValve.set_position_to_zero()
        op = "-"
        hcpLogger.critical("Waiting for cooling down 10 minutes...")
        t.sleep(600)
        if heatingValve.turn_up():
            t.sleep(120)
        continue
        
    if op == "up":
        hcpLogger.info(reason)
        if heatingValve.turn_up():
            t.sleep(120)
    elif op == "down":
        hcpLogger.info(reason)
        if heatingValve.turn_down():
            t.sleep(60)
    elif op == "-":
        hcpLogger.info(reason)
        t.sleep(30)
    else:
        t.sleep(30)
    

