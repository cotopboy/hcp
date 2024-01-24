import csv
import datetime

class CsvTemperatureLogger:
    def __init__(self):
        # Initialize the last_written_date to None
        self.last_written_date = None
        self.file = None
        self.writer = None

    def _get_filename(self):
        # Get today's date
        today = datetime.date.today()
        # Create a filename with today's date
        return f"logs/temperature_log_{today.strftime('%Y%m%d')}.csv"

    def _open_new_file(self):
        # Close the existing file if it's open
        if self.file:
            self.file.close()

        # Open a new file for today
        filename = self._get_filename()
        self.file = open(filename, 'a', newline='')
        self.writer = csv.writer(self.file)
        
        # Write the header if the file is new
        if self.file.tell() == 0:
            self.writer.writerow(['Timestamp', 'MainInlet', 'MainReturn', 'HeatingInlet', 'HeatingReturn', 'WaterInlet'])

    def log_temperature(self, temperatures):
        # Check if we've moved to a new day
        today = datetime.date.today()
        if today != self.last_written_date:
            self._open_new_file()
            self.last_written_date = today

        # Get the current time
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Write the data
        self.writer.writerow([now] + temperatures)
        self.file.flush()

    def close(self):
        # Close the file when done
        if self.file:
            self.file.close()

# Usage Example
#logger = CsvTemperatureLogger()
#logger.log_temperature([23.5, 24.1, 22.8, 23.0, 24.4])
# Remember to close the logger when done
#logger.close()
