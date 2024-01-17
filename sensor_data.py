from dataclasses import dataclass

@dataclass
class TemperatureHolder:
    heatingInlet: float
    heatingReturn: float
    mainInlet: float
    mainReturn: float
    Room:float
