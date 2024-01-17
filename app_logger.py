import logging

class AppLogger:
    def __init__(self, name="hcp", log_file="hcp.log"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

        # Create handlers
        file_handler = logging.FileHandler(log_file)
        stream_handler = logging.StreamHandler()

        # Create formatters and add it to handlers
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        stream_handler.setFormatter(formatter)

        # Add handlers to the logger
        self.logger.addHandler(file_handler)
        self.logger.addHandler(stream_handler)

    def get_logger(self):
        return self.logger
    


