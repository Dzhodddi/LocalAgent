from dataclasses import dataclass


@dataclass
class Item:
    name: str
    quantity: int
    price: float

    @property
    def value(self) -> float:
        return self.quantity * self.price
