import os
import glob
import time
from sensor_data import TemperatureHolder

class DS18B20Reader:
    def __init__(self):
        # Initialize the 1-Wire interface
        os.system('modprobe w1-gpio')
        os.system('modprobe w1-therm')

        # Base directory for device files
        self.base_dir = '/sys/bus/w1/devices/'

        # Find device folders
        self.device_folders = glob.glob(self.base_dir + '28*')

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
        temperatures = {}
        
        for device_folder in self.device_folders:
            sensor_id = device_folder.split('/')[-1]
            temperatures[sensor_id] = self._read_temp(device_folder)


        # for sensor, temperature in temperatures.items():
        #     print(f"Sensor {sensor}: {temperature} °C")            
        # Sensor 28-3ce1e3802805: 35.937 °C
        # Sensor 28-3ce1e380cd60: 20.187 °C
        # Sensor 28-3ce1e380d089: 38.25 °C
        # Sensor 28-3ce1e380b738: 35.812 °C
        # Sensor 28-3ce1d458c862: 74.25 °C


        temperatureHolder = TemperatureHolder(heatingInlet=temperatures["28-3ce1e380d089"], 
                                              heatingReturn=temperatures["28-3ce1e3802805"],
                                              mainInlet=temperatures["28-3ce1d458c862"],
                                              mainReturn=temperatures["28-3ce1e380b738"],
                                              Room=temperatures["28-3ce1e380cd60"]
                                              )

        return temperatureHolder

