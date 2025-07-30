import paho.mqtt.client as mqtt
import time

class TemperatureMQTTSender:
    def __init__(self, broker, port, username, password, base_topic="home/hcp"):
        self.base_topic = base_topic
        self.client = mqtt.Client()
        self.client.username_pw_set(username, password)
        self.client.connect(broker, port, 60)
    
    def SendTemperature(self, sub_topic, value):
        full_topic = f"{self.base_topic}/{sub_topic}"
        payload = str(value)
        self.client.publish(full_topic, payload)
