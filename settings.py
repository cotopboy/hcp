class Settings:
    
    def __init__(self,logger):
        self.logger = logger
        self.target_temperature = None
        self.read_and_parse_file()

    def read_and_parse_file(self):
        try:
            with open("./settings/target_temperature.txt", 'r') as file:
                content = file.read()
                readoutValue = int(content.strip())
                if self.target_temperature != readoutValue:
                    self.target_temperature = readoutValue
                    self.logger.info(f"settings.target_temperature {self.target_temperature} °C")
                    
        except FileNotFoundError:
            print(f"Error: File {self.file_path} not found.")
        except ValueError:
            print("Error: The content of the file is not a valid integer.")
        except Exception as e:
            print(f"An error occurred: {e}")