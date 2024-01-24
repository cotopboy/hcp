import os
import glob
import time
import threading
from sensor_data import TemperatureHolder
from temperature_csv_logger import CsvTemperatureLogger

class DS18B20Reader:

    temperatures = {}
    temperatureHolder:TemperatureHolder
    logger=()
    csvLogger = CsvTemperatureLogger()

    def __init__(self,logger):
        # Initialize the 1-Wire interface
        os.system('modprobe w1-gpio')
        os.system('modprobe w1-therm')
        self.logger = logger
        # Base directory for device files
        self.base_dir = '/sys/bus/w1/devices/'

        # Find device folders
        self.device_folders = glob.glob(self.base_dir + '28*')
        self.read_temperature()
        self.thread = threading.Thread(target=self.refresh_temperatures)
        self.thread.start()

    def _read_temp_raw(self, device_file):
        with open(device_file, 'r') as file:
            lines = file.readlines()
        return lines

    def _read_temp(self, device_folder):
        device_file = device_folder + '/w1_slave'
        lines = self._read_temp_raw(device_file)
        while lines[0].strip()[-3:] != 'YES':
            time.sleep(0.2)
            lines = self._read_temp_raw(device_file)
        equals_pos = lines[1].find('t=')
        if equals_pos != -1:
            temp_string = lines[1][equals_pos+2:]
            temp_c = float(temp_string) / 1000.0
            return temp_c
        
    def get_temperatures(self):
        return self.temperatureHolder

    def refresh_temperatures(self):
        while True:
            self.read_temperature()
            time.sleep(10)
    
    def read_temperature(self):
        for device_folder in self.device_folders:
                sensor_id = device_folder.split('/')[-1]
                self.temperatures[sensor_id] = self._read_temp(device_folder)

        
        self.temperatureHolder = TemperatureHolder(
                                                heatingInlet=self.temperatures["28-3ce1e380d089"], 
                                                heatingReturn=self.temperatures["28-3ce1e3802805"],
                                                mainInlet=self.temperatures["28-3ce1d458c862"],
                                                mainReturn=self.temperatures["28-3ce1e380b738"],
                                                waterInlet=self.temperatures["28-3ce1e380cd60"]
                                                )
        
        self.csvLogger.log_temperature([
                                        self.temperatureHolder.mainInlet,
                                        self.temperatureHolder.mainReturn,
                                        self.temperatureHolder.heatingInlet,
                                        self.temperatureHolder.heatingReturn,
                                        self.temperatureHolder.waterInlet
                                       ])
        
        self.logger.info(f"MIn: {self.temperatureHolder.mainInlet:.1f} MRe: {self.temperatureHolder.mainReturn:.1f}  HIn: {self.temperatureHolder.heatingInlet:.1f} HRe: {self.temperatureHolder.heatingReturn:.1f}  WIn:{self.temperatureHolder.waterInlet:.1f}")


        

