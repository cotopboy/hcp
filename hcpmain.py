# another_script.py
from ds18b20_reader import DS18B20Reader
from heating_valve import HeatingValve
from settings import Settings
from app_logger import AppLogger
import time as t


IS_HEATING_ON = True


sensor_reader = DS18B20Reader()
appLogger = AppLogger()
hcpLogger = appLogger.get_logger()

heatingValve = HeatingValve(logger=hcpLogger)
settings = Settings(logger=hcpLogger)

op = ""
reason = ""

while True:
    if not IS_HEATING_ON:
        break

    settings.read_and_parse_file()
    TARGET_TEMPERATURE = settings.target_temperature
    TARGET_TEMPERATURE_LOWER_LIMII = TARGET_TEMPERATURE - 2 
    TARGET_TEMPERATURE_UPPER_LIMII = TARGET_TEMPERATURE + 3

    temperatures = sensor_reader.get_temperatures()

    op = ""
    reason = ""
    
    hcpLogger.info(f"MIn: {temperatures.mainInlet:.1f} MRe: {temperatures.mainReturn:.1f} HIn: {temperatures.heatingInlet:.1f} HRe: {temperatures.heatingReturn:.1f} Room:{temperatures.Room:.1f}")

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

    if temperatures.heatingInlet > 70:
        heatingValve.set_position_to_zero()
        op = "-"
        hcpLogger.critical("Waiting for cooling down 10 minutes...")
        t.sleep(600)
        heatingValve.turn_up()
        hcpLogger.critical("Waiting 10 minutes to keep water flow...")
        t.sleep(300)
        
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
    
